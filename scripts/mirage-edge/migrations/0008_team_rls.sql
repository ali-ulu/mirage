-- MIRAGE — 0008: Tenant bazlı RLS (team_id izolasyonu)
--
-- Neden?
--   0007 `team_id` kolonlarını ekledi (veri izolasyonu), ama RLS hâlâ yalnızca
--   `service_role`'e izin veriyordu (deny-by-default). `team_id` veriyi
--   etiketler; ERIŞİM kararı RLS policy'sidir. Bu migration, authenticated
--   istemcilerin YALNIZCA üye oldukları takımların satırlarını görüp
--   ekleyebilmesini sağlar.
--
-- Model (Supabase-native):
--   - `team_members(user_id, team_id)`: kim hangi takımda. FastAPI service_role
--     ile yönetir (üyelik yazımı uygulama katmanına ait).
--   - `current_team_ids()`: çağıranın JWT `sub` claim'inden erişebildiği takım
--     id'lerini çözer. Supabase'te `auth.uid()` bu GUC'un üzerine kuruludur;
--     burada doğrudan `request.jwt.claim.sub` okunur ki policy yerel PostgreSQL
--     + `set request.jwt.claim.sub = '<uuid>'` ile davranışsal test edilebilsin
--     (auth şemasına bağımlılık yok).
--   - Tenant policy'leri: SELECT + INSERT, `team_id = any(current_team_ids())`.
--     UPDATE/DELETE policy'si YOK → deny-by-default (canary/triage append-only
--     trigger'ları zaten reddeder). NULL team_id (tenant'sız) satırlar
--     authenticated'a görünmez; service_role görür.
--
-- service_role policy'leri (0002/0005/0006) DEĞİŞMEZ: uygulama yolu (FastAPI)
-- service_role kullanır; tenant policy'leri yalnızca authenticated rolü için
-- ek kapıdır. İki policy birleşimi OR'dur; service_role `using (true)` ile tüm
-- satırları görür, authenticated yalnızca kendi takımını.
--
-- Idempotent: tekrar çalıştırılabilir.

-- =============================================================================
-- Üyelik tablosu
-- =============================================================================
create table if not exists public.team_members (
    user_id    uuid not null,
    team_id    uuid not null,
    role       text not null default 'member'
        check (role in ('owner', 'admin', 'member')),
    created_at timestamptz not null default now(),
    primary key (user_id, team_id)
);

create index if not exists idx_team_members_team on public.team_members (team_id);
create index if not exists idx_team_members_user on public.team_members (user_id);

alter table public.team_members enable row level security;

drop policy if exists "service_role_all_team_members" on public.team_members;
create policy "service_role_all_team_members" on public.team_members
    for all to service_role using (true) with check (true);

-- Kullanıcı yalnızca kendi üyelik satırlarını görebilir (üyeliği keşfetmek için).
drop policy if exists "authenticated_read_own_memberships" on public.team_members;
create policy "authenticated_read_own_memberships" on public.team_members
    for select to authenticated
    using (user_id = nullif(current_setting('request.jwt.claim.sub', true), '')::uuid);

comment on table public.team_members is
    'MIRAGE: kullanıcı-takım üyeliği (RLS ile tenant izolasyonunun temeli)';

-- =============================================================================
-- Çağıranın erişebildiği takımlar
-- =============================================================================
create or replace function public.current_team_ids()
returns uuid[]
language sql
stable
as $$
    select coalesce(
        array(
            select tm.team_id
            from public.team_members tm
            where tm.user_id =
                nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
        ),
        '{}'::uuid[]
    );
$$;

comment on function public.current_team_ids() is
    'MIRAGE: çağıranın JWT sub claim''inden çözülen takım id''leri (RLS helper)';

-- =============================================================================
-- honeytokens — tenant SELECT + INSERT
-- =============================================================================
drop policy if exists "team_read_honeytokens" on public.honeytokens;
create policy "team_read_honeytokens" on public.honeytokens
    for select to authenticated
    using (team_id = any (public.current_team_ids()));

drop policy if exists "team_insert_honeytokens" on public.honeytokens;
create policy "team_insert_honeytokens" on public.honeytokens
    for insert to authenticated
    with check (team_id = any (public.current_team_ids()));

-- =============================================================================
-- prompt_canaries — tenant SELECT + INSERT (append-only)
-- =============================================================================
drop policy if exists "team_read_prompt_canaries" on public.prompt_canaries;
create policy "team_read_prompt_canaries" on public.prompt_canaries
    for select to authenticated
    using (team_id = any (public.current_team_ids()));

drop policy if exists "team_insert_prompt_canaries" on public.prompt_canaries;
create policy "team_insert_prompt_canaries" on public.prompt_canaries
    for insert to authenticated
    with check (team_id = any (public.current_team_ids()));

-- =============================================================================
-- beacon_triage — tenant SELECT + INSERT (append-only)
-- =============================================================================
drop policy if exists "team_read_beacon_triage" on public.beacon_triage;
create policy "team_read_beacon_triage" on public.beacon_triage
    for select to authenticated
    using (team_id = any (public.current_team_ids()));

drop policy if exists "team_insert_beacon_triage" on public.beacon_triage;
create policy "team_insert_beacon_triage" on public.beacon_triage
    for insert to authenticated
    with check (team_id = any (public.current_team_ids()));

comment on table public.honeytokens is
    'MIRAGE honeytokens (RLS: service_role tümü, authenticated yalnızca kendi takımı)';
comment on table public.prompt_canaries is
    'MIRAGE prompt canaries (RLS: service_role tümü, authenticated yalnızca kendi takımı)';
comment on table public.beacon_triage is
    'MIRAGE beacon triyaj (append-only; RLS: service_role tümü, authenticated yalnızca kendi takımı)';
