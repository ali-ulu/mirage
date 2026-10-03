-- MIRAGE — 0009: MCP gateway denetim günlüğü
--
-- Bir MCP tool çağrısı için gateway'in verdiği politika/risk kararını ve
-- denetlenebilirlik kaydını saklar.
--
-- Neden tablo gerekli?
--   - Gateway kararını bellekte (`audit_log` listesi) tutar ve bu liste
--     SÜREÇ ÖMRÜNE bağlıdır: restart'ta sıfırlanır. Ürün "append-only,
--     değiştirilemez kanıt" dediği için bir denetim kaydının kaybolması
--     kabul edilemez.
--   - Dashboard MCP paneli kalıcı kayıttan okur; bellekten okusa her
--     deploy'da boş ekran gösterecek ve "koruma yok" izlenimi üretecekti.
--
-- Append-only: bir karar üretildikten sonra değiştirilemez/silinemez.
-- Idempotent: tekrar çalıştırılabilir.

-- =============================================================================
-- Tablo: mcp_audit
-- =============================================================================
create table if not exists public.mcp_audit (
    id          uuid primary key default gen_random_uuid(),
    occurred_at timestamptz not null default now(),
    -- Çağrıyı yapan aktör etiketi (istemci tarafından verilir).
    actor       text not null default '',
    -- MCP sunucusu tanımı (ör. "filesystem", "github").
    server      text not null,
    -- Çağrılan araç.
    tool        text not null,
    -- Gateway kararı ve gerekçesi.
    allowed     boolean not null,
    reason      text not null default '',
    risk_score  double precision not null default 0,
    risk_level  text not null default 'low',
    constraint ck_mcp_audit_risk_level
        check (risk_level in ('low', 'medium', 'high', 'critical'))
);

create index if not exists idx_mcp_audit_occurred_at
    on public.mcp_audit (occurred_at desc);
create index if not exists idx_mcp_audit_risk_level
    on public.mcp_audit (risk_level);
create index if not exists idx_mcp_audit_server
    on public.mcp_audit (server);

comment on table public.mcp_audit is
    'MIRAGE MCP gateway denetim günlüğü (append-only, kalıcı)';
comment on column public.mcp_audit.allowed is
    'Gateway kararı: true = izin verildi, false = fail-closed ile engellendi';
comment on column public.mcp_audit.risk_level is
    'Sunucu risk seviyesi: low | medium | high | critical';

-- =============================================================================
-- RLS — yalnızca service_role erişir
-- =============================================================================
alter table public.mcp_audit enable row level security;

drop policy if exists "service_role_all_mcp_audit" on public.mcp_audit;
create policy "service_role_all_mcp_audit" on public.mcp_audit
    for all to service_role using (true) with check (true);

-- =============================================================================
-- Append-only bütünlük
-- =============================================================================
create or replace function public.forbid_mcp_audit_mutation()
returns trigger
language plpgsql
as $$
begin
    raise exception 'MIRAGE mcp_audit is append-only: % on mcp_audit is not permitted', tg_op
        using errcode = 'restrict_violation';
end;
$$;

drop trigger if exists trg_forbid_mcp_audit_update on public.mcp_audit;
create trigger trg_forbid_mcp_audit_update
    before update on public.mcp_audit
    for each row
    execute function public.forbid_mcp_audit_mutation();

drop trigger if exists trg_forbid_mcp_audit_delete on public.mcp_audit;
create trigger trg_forbid_mcp_audit_delete
    before delete on public.mcp_audit
    for each row
    execute function public.forbid_mcp_audit_mutation();

comment on function public.forbid_mcp_audit_mutation() is
    'MIRAGE: mcp_audit üzerinde UPDATE/DELETE yasak (append-only)';