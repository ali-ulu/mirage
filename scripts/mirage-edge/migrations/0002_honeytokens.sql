-- MIRAGE Task 01 (Production) — honeytokens tablosu
--
-- Task 02 (honeytoken XLSX üretici) ve Task 03 (beacon receiver) arasındaki
-- köprü. Her üretilen honeytoken buraya kaydedilir; beacon geldiğinde
-- token ile eşleştirilir.
--
-- RLS aktif: service_role tam yetkili, anon kapalı.

create table if not exists public.honeytokens (
    id              uuid primary key default gen_random_uuid(),
    token           uuid not null unique,  -- public token (URL'de görünen)
    base_url        text not null,
    full_url        text not null,
    label           text not null default '',
    row_count       integer not null default 0,
    columns         jsonb not null default '[]'::jsonb,
    -- Takım/owner (multi-tenant SaaS için)
    team_id         uuid,
    -- File metadata (opsiyonel — eğer dosya diske yazıldıysa)
    file_name       text,
    file_sha256     text,
    file_size_bytes integer,
    -- Lifecycle
    issued_at       timestamptz not null default now(),
    expires_at      timestamptz,  -- NULL = no expiry
    revoked_at      timestamptz,  -- soft delete
    -- Triggered counter (DB-side trigger ile güncellenir)
    triggered_count integer not null default 0,
    first_triggered_at timestamptz,
    last_triggered_at  timestamptz
);

create index if not exists idx_honeytokens_token       on public.honeytokens (token);
create index if not exists idx_honeytokens_team         on public.honeytokens (team_id);
create index if not exists idx_honeytokens_issued_at    on public.honeytokens (issued_at desc);
create index if not exists idx_honeytokens_triggered    on public.honeytokens (triggered_count desc) where triggered_count > 0;

-- RLS
alter table public.honeytokens enable row level security;

create policy "service_role_all_honeytokens" on public.honeytokens
    for all to service_role using (true) with check (true);

-- Trigger: triggered_beacons insert edildiğinde ilgili honeytoken kaydını güncelle
create or replace function public.update_honeytoken_on_beacon()
returns trigger
language plpgsql
security definer
as $$
begin
    update public.honeytokens
    set
        triggered_count    = triggered_count + 1,
        first_triggered_at = coalesce(first_triggered_at, new.received_at),
        last_triggered_at  = new.received_at
    where token = new.token;
    return new;
end;
$$;

drop trigger if exists trg_update_honeytoken on public.triggered_beacons;
create trigger trg_update_honeytoken
    after insert on public.triggered_beacons
    for each row
    execute function public.update_honeytoken_on_beacon();

comment on table public.honeytokens is 'MIRAGE: Üretilen honeytoken kayıtları (Task 01 ↔ Task 02 ↔ Task 03 köprüsü)';
comment on column public.honeytokens.token is 'Public token UUID (XLSX URLinde görünen)';
comment on column public.honeytokens.team_id is 'Multi-tenant: hangi takım bu tokenı üretti';
comment on column public.honeytokens.triggered_count is 'DB-side trigger ile artırılır (race-condition-safe)';
