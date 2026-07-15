# MIRAGE V2 — "Nirvanadan Arşa" Planı + Oturum Raporu

> **Durum:** Mentorluk çıktısı / karar haritası + bu oturumda yapılan denetim ve düzeltmelerin kaydı.
> **Tarih:** Temmuz 2026.
> **Tek cümlelik tez:** MIRAGE'ı "bir honeytoken üreteci" olmaktan çıkarıp, **her sızıntı olayının imzalı, zaman-damgalı, mahkemede delil olabilecek bir kanıta dönüştüğü bir "aldatma-temelli sızıntı kanıtı" katmanına** yükseltmek — AGON ve HUQAN ile aynı "kanıtlanabilirlik" DNA'sını paylaşarak.

---

## 0. Bu oturumda ne yapıldı (kanıt)

MIRAGE deposu satır satır denetlendi, testler bu ortamda bizzat koşturuldu. Sonuçlar:

### Doğrulanan güçlü yanlar
- **Passive-only iddiası bizzat kanıtlandı.** Gerçek bir honeytoken XLSX üretildi ve içi açıldı: external tracking link mevcut (`r:link` ile Excel açılışta HTTP GET atıyor), **sıfır yasaklı pattern, sıfır makro/VBA parçası.** Üretimin son adımındaki yasaklı-pattern taraması (powershell, VBA, DDE, DNS tunneling, smb/ftp/file şemaları) ihlalde üretimi iptal ediyor. Ürünün en kritik güvenlik/yasal tezi sağlam.
- **`r:link` vs `r:embed` tercihi doğru** — external image olarak bağlanınca openpyxl dosyayı yüklemeye çalışmıyor, Excel ise URL'i resolve etmek için otomatik GET atıyor. Bilinçli, doğru mühendislik.
- **Python server fail-closed.** `_require_api_token`, production'da (`MIRAGE_ENV=production`) token yoksa 503 döndürüyor — AGON'da bulunan fail-open bug'ı MIRAGE'da YOK. Aynı hata tekrarlanmamış.

### Test sonuçları (bu ortamda koşturuldu)
- Python: honeytoken 21/21, registry 13/14 (1 skip), integration testleriyle birlikte **34/35 pass**, server-auth 4/4.
- Frontend (vitest): düzeltme öncesi 46/47 (1 fail) → **düzeltme sonrası 47/47.**

### Bu oturumda düzeltilen gerçek bug
**FIX-1 — `src/lib/supabase/env.ts` erken-donma (frozen env) hatası.**
Supabase env değişkenleri modül yüklenirken bir kez okunup `const`'a donduruluyordu. Bu yalnızca testi kırmıyordu; **gerçek üretim sınırıydı** — env değişkenleri process başlangıcında hazır değilse (geç yükleme / edge runtime / runtime injection) Supabase client hiç oluşmuyor, dashboard sessizce polling fallback'e düşüyordu. Değişkenler artık her çağrıda lazy okunuyor. Sebep koda yorum olarak yazıldı. Sonuç: frontend 47/47 yeşil.

### Bu oturumda yapılan temizlik
- **`.env` dosyası arşivden silindi** (aşağıda BULGU-1). `.env.example` şablonu korundu (gerçek sır içermiyor).
- Paketleme dışı bırakılanlar: `node_modules` (1.4G), `.next` (238M), `.venv` (295M, zaten Windows-uyumsuz), `memory.db`, `prisma/dev.db`, `.pytest_cache`, `tsconfig.tsbuildinfo`, `downloads/`. Bunlar ya bağımlılık ya üretilmiş artık — kaynak değil.

---

## 1. Açık bulgular (V2 kapsamına giren)

### BULGU-1 (KRİTİK, aksiyon SENDE) — `.env` gerçek sırlarla arşive girmişti
Arşivdeki `.env` dosyası düz metin olarak şunları içeriyordu: `SUPABASE_SERVICE_ROLE_KEY` (RLS'i tamamen bypass eden "tanrı anahtarı"), `DATABASE_URL`, `MIRAGE_API_TOKEN`. Bu arşiv paylaşıldıysa bu anahtarlar **yanmış kabul edilmeli.**

**Dosya bu paketten silindi**, ama silinmesi anahtarları güvenli yapmaz. Senin bugün yapman gerekenler:
1. Supabase'den `SERVICE_ROLE_KEY`'i **rotate et** (yenile).
2. `DATABASE_URL` parolasını değiştir.
3. `MIRAGE_API_TOKEN`'ı yeni bir değere çevir.
4. `.gitignore` zaten `.env*` içeriyor (kontrol edildi) — bir daha arşive/commit'e girmemesi için `git rm --cached .env` disiplinini koru ve arşiv alırken her zaman `-x ".env"` kullan.

### BULGU-2 (YÜKSEK) — Next.js beacon yolu hâlâ `mockDb` kullanıyor
`src/app/api/track/[token]/route.ts` ve `src/app/api/route.ts` bellek-içi `mockDb`'ye yazıyor. Python edge beacon-receiver gerçek Supabase'e parametrize query ile yazıyor (sağlam), ama Next.js yolu prototip. `supabase-client.ts` başındaki "Zero Mock Policy" ifadesiyle çelişiyor.

**Karar gerektiren netleştirme (ikisinden biri):**
- (a) Next.js track ucu gerçek Supabase'e yazsın (Python edge function ile aynı tabloya), veya
- (b) Dokümana açık sınır yaz: *"Kanonik beacon receiver Python edge function'dır (`scripts/mirage-edge/`). Next.js `/api/track` ucu yalnızca yerel demo/geliştirme içindir, kalıcı kayıt yapmaz."*
Öneri: kısa vadede (b) — dürüst sınır beyanı; orta vadede (a) tek kanonik yola indirgeme.

### BULGU-3 (ORTA) — Boundary metni güncellenmeli
Dokümandaki "beacon receiver + dashboard evidence view" iddiası Python tarafı için gerçek, Next.js tarafı için mock. "Current Boundary" bölümüne şunlar açıkça yazılmalı: kanonik beacon yolu Python'dır; live beacon davranışı görüntüleyiciye bağımlıdır (Excel Protected View / external-content engelleme beacon'ı durdurabilir; LibreOffice demo provası için daha güvenilir); Next.js track ucu demo amaçlıdır.

---

## 2. Usta dokunuşu: üç farklılaştırıcı (nirvanadan arşa)

Hepsi mevcut kodun üstüne oturuyor. AGON ile aynı "kanıtlanabilirlik" ailesine bağlanıyor — böylece dört ürün tek anlatı altında toplanıyor.

### 2.1 Signed Leak Evidence — "imzalı sızıntı delili"
**Fikir:** Bugün bir honeytoken tetiklendiğinde IP + User-Agent + timestamp kaydediliyor. V2'de her beacon olayı, **imzalı ve zaman-damgalı bir kanıt kaydına** dönüşür: `{token, ip, user_agent, received_at, honeytoken_sha256, prev_hash}` alanları üzerinde HMAC/SHA-256 imza. Böylece bir sızıntı olayı "bir log satırı" değil, **sonradan değiştirilemez bir delil** olur.
**Neden benzersiz:** Sızıntı tespit araçları "birisi dosyayı açtı" der; hiçbiri bu tespiti kurcalanamaz delile çevirmez. MIRAGE, AGON'un audit-chain mantığını sızıntı olaylarına taşıyan ilk deception aracı olur.
**Kod karşılığı:** Beacon-receiver'da (hem Python edge hem Next.js yolu birleştirildikten sonra) kayıt anında imza üret; `honeytoken.py`'deki `file_sha256` alanı zaten var — onu delile bağla.

### 2.2 Evidence Chain Verify — "delil zincirini ispatla"
**Fikir:** AGON'daki `/api/audit-verify`'ın MIRAGE karşılığı: tüm beacon delil zincirini yürüyüp `prev_hash` bağlarını ve imzaları doğrulayan bir uç. "Bu sızıntı kayıtları üretildiğinden beri değiştirilmedi ✓" raporu.
**Neden benzersiz:** Sızıntı olayını mahkemede/denetimde savunulabilir kılar. Demo: bir delil kaydını elle değiştir, doğrulayıcı anında yakalar.
**Kod karşılığı:** AGON'da yazılan `verifyAuditChain()` deseninin birebir uyarlaması.

### 2.3 HUQAN köprüsü — "üst yargıya devret"
**Fikir:** Bir honeytoken tetiklendiğinde MIRAGE yapılandırılmış bir güvenlik olayı üretir → AGON'a event handoff → AGON policy verdict verir → HUQAN nihai güven kararını makbuzlar. Senin kendi MIRAGE→AGON→HUQAN zincir modelinin somutlaşması.
**Neden benzersiz:** Dört ürünü tek katmanlı güven mimarisine bağlayan yapıştırıcı: *"MIRAGE sızıntıyı kanıtlar, AGON olayı yönetir, HUQAN güven kararını verir ve makbuzlar."*
**Kod karşılığı:** Beacon tetiklendiğinde AGON'un `/api/ingest` ucuna yapılandırılmış event POST'u. Merge yok, sadece event handoff. **V2'de iskele/opsiyonel kalabilir** — gerçek AGON ucu hazır olunca tamamlanır (hayali API yasağı).

> **Disiplin:** Bu üç dokunuş dışında V2'ye özellik EKLENMEZ. DOCX honeytoken, prompt-layer canary, multi-tenant, geo-IP zenginleştirme, PDF desteği — hepsi Sprint 3+ backlog.

---

## 3. V2 sürüm tanımı ve non-claim

**MIRAGE v0.2.0 tanımı (hedef):**
> Pasif XLSX honeytoken üretimi + imzalı/zaman-damgalı sızıntı delili + uçtan uca doğrulanabilir delil zinciri + sentetik hassas veri seti üretimi + beacon telemetri. Kanonik beacon yolu Python edge function; fail-closed API yetkilendirme.

**v0.2.0'ın HÂLÂ demeyeceği (non-claim):**
- Tam DLP / EDR / XDR platformu — YOK
- Malware tespit ürünü — YOK
- Her görüntüleyicide garantili beacon — YOK (Excel Protected View engelleyebilir)
- Multi-tenant SaaS — YOK
- Sertifikasyonsuz uyumluluk iddiası — YOK; doğru dil: *"denetim/adli kanıt üretmeyi kolaylaştırır."*

---

## 4. Sıra ve efor

| Adım | İş | Efor | Öncelik |
|---|---|---|---|
| 0 | **Sırları rotate et** (BULGU-1) | ~yarım gün | ACİL — bugün |
| 1 | Next.js beacon yolu netleştir (BULGU-2/3) | ~1 gün | Yüksek |
| 2 | 2.1 Signed Leak Evidence | ~2 gün | Farklılaştırıcı |
| 3 | 2.2 Evidence Chain Verify | ~1 gün | Farklılaştırıcı (AGON deseni hazır) |
| 4 | 2.3 HUQAN köprüsü (iskele) | ~1 gün | Anlatısal |
| 5 | Boundary/doküman dürüstlük düzeltmeleri | ~yarım gün | İtibar |

Bug/temizlik paketi (adım 0-1) farklılaştırıcılardan önce. Her PR ajan protokolüne tabi: tam test gate sayılarıyla, non-claim bloğu, Yazar/Denetçi ayrımı.

---

## 5. Demo anlatısı (V2 bittiğinde)

Üç perde, AGON demosuyla simetrik:
1. **Tuzak:** Sentetik "Q4-finans-export.xlsx" üret, içine passive honeytoken göm. "Bu dosyada tek satır kod yok — kanıtlayalım" (passive-only doğrulama çıktısı).
2. **Yakalama:** Dosyayı LibreOffice'te aç → beacon düşer → dashboard'da IP/UA/timestamp + imzalı delil kaydı belirir.
3. **İspat:** Evidence chain verify → "delil zinciri N kayıtta bütün ✓". Bir kaydı elle değiştir → "kayıt X'te kırıldı ✗". *Sızıntı tespiti artık savunulabilir delil.*

---

## 6. Kapanış hükmü

MIRAGE'ın cevheri "dosya açıldı mı" tespiti değil — **o tespitin kurcalanamaz, imzalı, HUQAN ailesine bağlanan bir delile dönüşmesi.** Passive-only tezi zaten sağlam ve kanıtlandı; V2 bunun üstüne "kanıtlanabilirlik" katmanını ekliyor ve AGON/HUQAN ile aynı DNA'ya bağlıyor. Tek şart: önce sırlar rotate edilsin, Next.js mock yolu netleşsin — çünkü delil üreten ürünün kendi sırları açıkta olamaz, kendi kayıt yolu mock kalamaz.
