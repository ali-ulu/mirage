-- MIRAGE — 0006: beacon_triage için RLS'i etkinleştir (güvenlik düzeltmesi)
--
-- Neden?
--   0004, `beacon_triage` tablosunu ve append-only trigger'larını oluşturdu ama
--   ROW LEVEL SECURITY'i ETKİNLEŞTİRMEDİ. Diğer tüm tablolar (attackers,
--   triggered_beacons, honeytokens, prompt_canaries) RLS ile korunurken bu tablo
--   açık kaldı.
--
--   Supabase'in varsayılan grant modelinde `anon` ve `authenticated` rolleri
--   `public` şemasındaki tablolara ALL yetkisi alır. RLS kapalı olduğunda bu
--   yetkiler sınırsız çalışır: anonim bir istemci triyaj defterine kayıt
--   ekleyebilir/okuyabilir. Bu, append-only denetim defterinin bütünlüğünü
--   (yalnızca sunucunun yazması gereken) bozar.
--
-- Çözüm:
--   RLS'i etkinleştir + yalnızca `service_role` için policy tanımla. Diğer
--   roller policy'siz kaldığından hiçbir satır göremez/yazamaz (deny-by-default).
--   Grants geri alınmaz; RLS asıl kapıdır (Supabase modeliyle tutarlı).
--
-- Idempotent: tekrar çalıştırılabilir.

-- =============================================================================
-- RLS — yalnızca service_role erişir
-- =============================================================================
alter table public.beacon_triage enable row level security;

drop policy if exists "service_role_all_beacon_triage" on public.beacon_triage;
create policy "service_role_all_beacon_triage" on public.beacon_triage
    for all to service_role using (true) with check (true);

comment on table public.beacon_triage is
    'MIRAGE beacon triyaj kayıtları (append-only; RLS yalnızca service_role)';
