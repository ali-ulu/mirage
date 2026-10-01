-- MIRAGE — 0004: Beacon triyaj kayıtları
--
-- Kanıt zincirine bağlı bir triyaj sonucunu saklar. Triage bir LLM veya
-- deterministik sezgisel (heuristic) ile üretilebilir; hangisi olduğu `source`
-- alanında açıkça belirtilir (ör. "llm:openai", "heuristic").
--
-- Neden ayrı tablo?
--   - `triggered_beacons` APPEND-ONLY kanıt zinciridir ve yalnızca edge
--     function tarafından yazılır (0003). Triyaj ise FastAPI tarafında,
--     kanıt yazıldıktan sonra üretilir; kanıt zincirinin kripto bütünlüğüne
--     dokunmadan ayrı bir append-only defterde tutulur.
--   - Böylece triyaj yeniden çalıştırılsa bile kanıt zinciri değişmez.
--
-- Triyaj kayıtları da append-only'dir: bir değerlendirme üretildikten sonra
-- değiştirilemez/silinemez (denetlenebilirlik). Yeni değerlendirme yalnızca
-- INSERT ile eklenir.
--
-- Idempotent: tekrar çalıştırılabilir.

-- =============================================================================
-- Tablo: beacon_triage
-- =============================================================================
create table if not exists public.beacon_triage (
    id                 uuid primary key default gen_random_uuid(),
    -- Triyajı yapılan honeytoken (triggered_beacons.token ile aynı UUID uzayı;
    -- 0001'de olduğu gibi foreign-key yok — registry honeytoken sunucusunda).
    token              uuid not null,
    -- İlişkili kanıt kaydının zincir sırası (varsa; kanıt zincirine bağ).
    chain_seq          bigint,
    severity           text not null,
    confidence         double precision not null default 0,
    rationale          text not null default '',
    recommended_action text not null,
    -- Üreten kaynak: "llm:openai" | "llm:anthropic" | "heuristic"
    source             text not null,
    -- Kanıt zinciri doğrulama sonucu (opsiyonel bağlam).
    chain_verified     boolean,
    -- LLM kullanıldıysa model adı.
    model              text,
    created_at         timestamptz not null default now(),
    constraint ck_beacon_triage_severity
        check (severity in ('low', 'medium', 'high', 'critical')),
    constraint ck_beacon_triage_action
        check (recommended_action in ('ignore', 'monitor', 'investigate', 'escalate')),
    constraint ck_beacon_triage_confidence
        check (confidence >= 0 and confidence <= 1)
);

create index if not exists idx_beacon_triage_token
    on public.beacon_triage (token);
create index if not exists idx_beacon_triage_created_at
    on public.beacon_triage (created_at desc);

comment on table public.beacon_triage is
    'MIRAGE beacon triyaj kayıtları (append-only değerlendirme defteri)';
comment on column public.beacon_triage.source is
    'Triyajı üreten kaynak: llm:openai | llm:anthropic | heuristic';
comment on column public.beacon_triage.chain_seq is
    'İlişkili triggered_beacons.chain_seq (kanıt zinciri bağı, varsa)';

-- =============================================================================
-- Append-only bütünlük
-- =============================================================================
create or replace function public.forbid_triage_mutation()
returns trigger
language plpgsql
as $$
begin
    raise exception 'MIRAGE triage is append-only: % on beacon_triage is not permitted', tg_op
        using errcode = 'restrict_violation';
end;
$$;

drop trigger if exists trg_forbid_triage_update on public.beacon_triage;
create trigger trg_forbid_triage_update
    before update on public.beacon_triage
    for each row
    execute function public.forbid_triage_mutation();

drop trigger if exists trg_forbid_triage_delete on public.beacon_triage;
create trigger trg_forbid_triage_delete
    before delete on public.beacon_triage
    for each row
    execute function public.forbid_triage_mutation();

comment on function public.forbid_triage_mutation() is
    'MIRAGE: beacon_triage üzerinde UPDATE/DELETE yasak (append-only)';
