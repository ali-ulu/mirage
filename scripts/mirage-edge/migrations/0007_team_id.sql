-- MIRAGE — 0007: Multi-tenant team_id (prompt_canaries, beacon_triage)
--
-- 0002 zaten `honeytokens.team_id` taşıyor; ancak prompt-layer canary kayıtları
-- (0005) ve triyaj defteri (0004) tenant'sızdı. Bu migration her iki tabloya
-- nullable `team_id uuid` ve team_id sorguları için index ekler.
--
-- Nullable: mevcut (tenant'sız) kayıtlar korunur; tenant zorunluluğu ayrı bir
-- iş kararıdır (bu migration onu dayatmaz).
--
-- Mevcut token tekilliği (prompt_canaries.token unique) KORUNUR: token uuid4'tür
-- ve tablo genelinde tekildir; tenant kapsamı için tekilliği gevşetmek gereksiz
-- risk (NULL çiftlerinde yinelenen token'a izin verirdi).
--
-- Idempotent: tekrar çalıştırılabilir.

-- =============================================================================
-- prompt_canaries
-- =============================================================================
alter table public.prompt_canaries
    add column if not exists team_id uuid;

create index if not exists idx_prompt_canaries_team
    on public.prompt_canaries (team_id);

comment on column public.prompt_canaries.team_id is
    'Multi-tenant: hangi takım bu canary''yi üretti (opsiyonel)';

-- =============================================================================
-- beacon_triage
-- =============================================================================
alter table public.beacon_triage
    add column if not exists team_id uuid;

create index if not exists idx_beacon_triage_team
    on public.beacon_triage (team_id);

comment on column public.beacon_triage.team_id is
    'Multi-tenant: triyaj kaydının ait olduğu takım (opsiyonel)';
