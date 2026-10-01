-- MIRAGE — 0005: Prompt-layer canary kayıtları
--
-- Bir AI ajanı bağlamına (system prompt / RAG dokümanı / agent memory) gömülen
-- yüksek-entropili işaretleri saklar. İşaret sonradan başka bir yerde görünürse
-- bağlamın sızdığı anlaşılır.
--
-- Neden kalıcı?
--   - Canary'ler süreç belleğinde tutulursa server restart'ında kaybolur ve
--     sızıntı tespiti (registry.match) geçmiş işaretleri tanıyamaz. Bu tablo
--     restart dayanıklılığı sağlar.
--
-- Append-only: bir canary üretildikten sonra değiştirilemez/silinemez
-- (denetlenebilirlik). Yeni canary yalnızca INSERT ile eklenir.
--
-- Idempotent: tekrar çalıştırılabilir.

-- =============================================================================
-- Tablo: prompt_canaries
-- =============================================================================
create table if not exists public.prompt_canaries (
    id         uuid primary key default gen_random_uuid(),
    -- Gömülen benzersiz token (işaretin çekirdeği).
    token      uuid not null unique,
    -- İşaretin kanonik metni: [[MIRAGE-CANARY:<token>]]
    marker     text not null,
    -- Gömüldüğü bağlam.
    context    text not null,
    label      text not null default '',
    created_at timestamptz not null default now(),
    constraint ck_prompt_canary_context
        check (context in ('system_prompt', 'rag_document', 'agent_memory'))
);

create index if not exists idx_prompt_canaries_token
    on public.prompt_canaries (token);
create index if not exists idx_prompt_canaries_created_at
    on public.prompt_canaries (created_at desc);

comment on table public.prompt_canaries is
    'MIRAGE prompt-layer canary kayıtları (restart dayanıklı, append-only)';
comment on column public.prompt_canaries.context is
    'İşaretin gömüldüğü bağlam: system_prompt | rag_document | agent_memory';

-- =============================================================================
-- RLS — yalnızca service_role erişir
-- =============================================================================
alter table public.prompt_canaries enable row level security;

drop policy if exists "service_role_all_prompt_canaries" on public.prompt_canaries;
create policy "service_role_all_prompt_canaries" on public.prompt_canaries
    for all to service_role using (true) with check (true);

-- =============================================================================
-- Append-only bütünlük
-- =============================================================================
create or replace function public.forbid_canary_mutation()
returns trigger
language plpgsql
as $$
begin
    raise exception 'MIRAGE canary is append-only: % on prompt_canaries is not permitted', tg_op
        using errcode = 'restrict_violation';
end;
$$;

drop trigger if exists trg_forbid_canary_update on public.prompt_canaries;
create trigger trg_forbid_canary_update
    before update on public.prompt_canaries
    for each row
    execute function public.forbid_canary_mutation();

drop trigger if exists trg_forbid_canary_delete on public.prompt_canaries;
create trigger trg_forbid_canary_delete
    before delete on public.prompt_canaries
    for each row
    execute function public.forbid_canary_mutation();

comment on function public.forbid_canary_mutation() is
    'MIRAGE: prompt_canaries üzerinde UPDATE/DELETE yasak (append-only)';
