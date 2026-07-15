-- MIRAGE Task 03 — Supabase / PostgreSQL Şema Migration
--
-- Bu migration, MIRAGE deception altyapısının veri katmanını oluşturur.
-- 3 ana tablo:
--   1. attackers          — Benzersiz saldırgan IP'leri ve metadata
--   2. triggered_beacons  — Tetiklenen her honeytoken olayı (birebir log)
--   3. sabotage_logs      — Audit trail / event log
--
-- Güvenlik:
--   - RLS (Row Level Security) aktif — service role tam yetkili, anon yok
--   - Tüm tablolarda created_at/updated_at otomatik
--   - IP adresi inet tipinde saklanır (regex ile validate edilmiş hal zaten)
--   - Token UUID tipinde (foreign-key yok — token'lar honeytoken sunucusunda
--     registry'de tutuluyor, burada sadece raw log)

-- =============================================================================
-- Extensions
-- =============================================================================
create extension if not exists "pgcrypto";  -- gen_random_uuid()
-- inet is a built-in PostgreSQL type; no extension is required.

-- =============================================================================
-- Tablo 1: attackers
-- =============================================================================
create table if not exists public.attackers (
    id              uuid primary key default gen_random_uuid(),
    ip              inet not null,
    first_seen      timestamptz not null default now(),
    last_seen       timestamptz not null default now(),
    hit_count       integer not null default 1,
    last_user_agent text,
    -- İlk gördüğümüz token (en çok hangi dosyayı açtılar, görme adına)
    last_token      uuid,
    -- Coarse geo info (Supabase function ile doldurulabilir)
    country_code    text,
    asn             text,
    notes           text,
    -- Etiketler (manual tagging için): "confirmed-apt", "false-positive", etc.
    tags            text[] not null default '{}',

    unique (ip)
);

-- last_seen ve hit_count artık trigger ile güncellenecek (upsert'ten ayrı)
create index if not exists idx_attackers_last_seen on public.attackers (last_seen desc);
create index if not exists idx_attackers_first_seen on public.attackers (first_seen desc);
create index if not exists idx_attackers_country on public.attackers (country_code);

-- =============================================================================
-- Tablo 2: triggered_beacons
-- =============================================================================
create table if not exists public.triggered_beacons (
    id           uuid primary key default gen_random_uuid(),
    token        uuid not null,
    ip           inet not null,
    user_agent   text,
    received_at  timestamptz not null default now(),
    -- Headers'ın subset'i (debugging için)
    raw_headers  jsonb,
    -- Hangi ofis uygulamasının açtığı tespiti ( LibreOffice / Excel / Numbers / vs. )
    opener_app   text generated always as (
        case
            when user_agent ilike '%libreoffice%' then 'libreoffice'
            when user_agent ilike '%microsoft office%' then 'excel'
            when user_agent ilike '%excel%' then 'excel'
            when user_agent ilike '%numbers%' then 'numbers'
            when user_agent ilike '%google%' then 'google-sheets'
            when user_agent ilike '%mozilla%' then 'browser'
            else 'unknown'
        end
    ) stored
);

create index if not exists idx_beacons_received_at on public.triggered_beacons (received_at desc);
create index if not exists idx_beacons_token on public.triggered_beacons (token);
create index if not exists idx_beacons_ip on public.triggered_beacons (ip);
create index if not exists idx_beacons_opener on public.triggered_beacons (opener_app);

-- =============================================================================
-- Tablo 3: sabotage_logs (audit trail)
-- =============================================================================
create table if not exists public.sabotage_logs (
    id           uuid primary key default gen_random_uuid(),
    event_type   text not null,  -- 'beacon_triggered', 'token_issued', 'rate_limited', etc.
    token        uuid,
    ip           inet,
    details      jsonb,
    created_at   timestamptz not null default now()
);

create index if not exists idx_logs_event_type on public.sabotage_logs (event_type);
create index if not exists idx_logs_created_at on public.sabotage_logs (created_at desc);

-- =============================================================================
-- Trigger: triggered_beacons insert edildiğinde attackers tablosunu güncelle
-- =============================================================================
-- Edge function yalnızca triggered_beacons insert eder; attacker upsert ve sayaç
-- güncellemesi DB-side trigger ile tek kaynak olarak yönetilir.

create or replace function public.upsert_attacker_on_beacon()
returns trigger
language plpgsql
security definer
as $$
begin
    insert into public.attackers (ip, first_seen, last_seen, hit_count, last_user_agent, last_token)
    values (new.ip, new.received_at, new.received_at, 1, new.user_agent, new.token)
    on conflict (ip) do update
    set last_seen       = excluded.last_seen,
        hit_count       = public.attackers.hit_count + 1,
        last_user_agent = excluded.last_user_agent,
        last_token      = excluded.last_token;
    return new;
end;
$$;

drop trigger if exists trg_upsert_attacker on public.triggered_beacons;
create trigger trg_upsert_attacker
    after insert on public.triggered_beacons
    for each row
    execute function public.upsert_attacker_on_beacon();

-- =============================================================================
-- Trigger: triggered_beacons insert edildiğinde sabotage_logs'a event yaz
-- (Edge function bunu manuel yapmıyor — DB-side garanti)
-- =============================================================================
create or replace function public.log_beacon_event()
returns trigger
language plpgsql
security definer
as $$
begin
    insert into public.sabotage_logs (event_type, token, ip, details, created_at)
    values (
        'beacon_triggered',
        new.token,
        new.ip,
        jsonb_build_object(
            'user_agent', new.user_agent,
            'opener_app', new.opener_app,
            'received_at', new.received_at
        ),
        new.received_at
    );
    return new;
end;
$$;

drop trigger if exists trg_log_beacon on public.triggered_beacons;
create trigger trg_log_beacon
    after insert on public.triggered_beacons
    for each row
    execute function public.log_beacon_event();

-- =============================================================================
-- RLS Policies
-- =============================================================================
-- Edge function service role key ile çalışır — RLS bypass.
-- Anon authenticated key ile erişim tamamen kapalı.
alter table public.attackers          enable row level security;
alter table public.triggered_beacons  enable row level security;
alter table public.sabotage_logs      enable row level security;

-- Service role her şeyi yapabilir (RLS bypass eder ama policy explicit olsun)
create policy "service_role_all_attackers"   on public.attackers
    for all to service_role using (true) with check (true);
create policy "service_role_all_beacons"     on public.triggered_beacons
    for all to service_role using (true) with check (true);
create policy "service_role_all_logs"        on public.sabotage_logs
    for all to service_role using (true) with check (true);

-- Anon kullanıcıların READ erişimi YOK (bu tablolar dahili kullanım için)
-- Eğer dashboard authenticated kullanıcılar içinse, "authenticated" rolüne
-- read policy eklenebilir. Şimdilik kapalı.

-- =============================================================================
-- Comments
-- =============================================================================
comment on table public.attackers         is 'MIRAGE: Benzersiz saldırgan IP kayıtları';
comment on table public.triggered_beacons is 'MIRAGE: Tetiklenen her honeytoken olayı';
comment on table public.sabotage_logs     is 'MIRAGE: Audit trail (tüm olaylar)';
comment on column public.triggered_beacons.opener_app is
    'Office uygulaması otomatik tespiti (Excel/LibreOffice/Numbers/...)';
