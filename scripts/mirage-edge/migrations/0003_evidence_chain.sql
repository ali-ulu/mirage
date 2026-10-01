-- MIRAGE — 0003: Kanıt zinciri (evidence chain) şeması
--
-- Her honeytoken beacon olayı, sonradan değiştirilemez bir kanıt kaydına
-- dönüşür. İki katman:
--   1. Hash zinciri: record_hash -> sonraki kaydın prev_hash'i (kopmaz bağ)
--   2. HMAC imzası : record_hash, sunucu sırrıyla imzalanır
--
-- TASARIM KARARI (hibrit):
--   - chain_seq / prev_hash / record_hash / hmac alanlarını EDGE FUNCTION
--     hesaplar ve yazar. Gerekçe:
--       * `opener_app` PostgreSQL'de `generated always as` ile türetilir ve
--         BEFORE INSERT trigger'ında henüz NULL'dur; hash'in DB'de SQL ile
--         hesaplanması kırılgan ve diller-arası kanonikleştirme borcu yaratır.
--       * HMAC sırrı veritabanında tutulmaz (sır hijyeni).
--       * Böylece hash mantığı TEK dilde (TypeScript, Web Crypto) ve tek
--         yerde yaşar; Python kanıt çekirdeği bağımsız referans/doğrulayıcıdır.
--   - Bu migration, zincirin DB tarafındaki sözleşmesini kurar: sıralama
--     (chain_seq), tekillik ve APPEND-ONLY bütünlük (UPDATE/DELETE yasak).
--
-- Idempotent: tekrar çalıştırılabilir.

-- =============================================================================
-- Kanıt kolonları
-- =============================================================================
alter table public.triggered_beacons
    add column if not exists chain_seq   bigint,
    add column if not exists prev_hash   text,
    add column if not exists record_hash text,
    add column if not exists hmac        text;

-- chain_seq zincirin sırasıdır: tekil olmalı (NULL'lar hariç).
create unique index if not exists uq_beacons_chain_seq
    on public.triggered_beacons (chain_seq);

create index if not exists idx_beacons_record_hash
    on public.triggered_beacons (record_hash);

comment on column public.triggered_beacons.chain_seq is
    'MIRAGE kanıt zinciri sıra numarası (tekil, edge function atar)';
comment on column public.triggered_beacons.prev_hash is
    'Bir önceki kaydın record_hash''i (genesis = 64 sıfır)';
comment on column public.triggered_beacons.record_hash is
    'Kanonik alanların SHA-256 özeti';
comment on column public.triggered_beacons.hmac is
    'record_hash üzerinde HMAC-SHA256 imzası (sunucu sırrı ile)';

-- =============================================================================
-- Append-only bütünlük
-- =============================================================================
-- Kanıt kaydı üretildikten sonra DEĞİŞTİRİLEMEZ veya SİLİNEMEZ. Bu, RLS/grants
-- ne olursa olsun DB seviyesinde garantidir (defense in depth). Yeni kanıt
-- yalnızca INSERT ile eklenir.
create or replace function public.forbid_beacon_mutation()
returns trigger
language plpgsql
as $$
begin
    raise exception 'MIRAGE evidence is append-only: % on triggered_beacons is not permitted', tg_op
        using errcode = 'restrict_violation';
end;
$$;

drop trigger if exists trg_forbid_beacon_update on public.triggered_beacons;
create trigger trg_forbid_beacon_update
    before update on public.triggered_beacons
    for each row
    execute function public.forbid_beacon_mutation();

drop trigger if exists trg_forbid_beacon_delete on public.triggered_beacons;
create trigger trg_forbid_beacon_delete
    before delete on public.triggered_beacons
    for each row
    execute function public.forbid_beacon_mutation();

comment on function public.forbid_beacon_mutation() is
    'MIRAGE: triggered_beacons üzerinde UPDATE/DELETE yasak (append-only kanıt)';
