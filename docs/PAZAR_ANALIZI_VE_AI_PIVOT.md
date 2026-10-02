# MIRAGE — Pazar Analizi ve AI/AI-Agent Pivot Yol Haritası

> Durum: analiz + yol haritası. Bu belge bir iddia listesi değil; her satır ya
> depodaki gerçek yeteneğe ya da kaynağı verilen kamuya açık veriye dayanır.

## 1. Yönetici özeti

MIRAGE, "deception-only" (veri tuzaklama) konumundan **AI/AI-agent güvenliği**
konumuna pivot etmiştir. Pivotun tezi şudur:

> Saldırgan tarafı yapay zekâ ile ölçeklendi (tek bir LLM ajanı neredeyse sıfır
> marjinal maliyetle paralel keşif yapıyor). Savunma tarafında kazanan ürün,
> **ajanın bağlamını ve çıktısını kuşatan**; sızıntıyı oyalamadan **kurcalanamaz
> kanıtla** yakalayan; ve bunu SIEM/SOAR'a düşüren bütünleşik bir katmandır.
> MIRAGE bu katmanı, üç olgun yeteneği (canary/honeytoken, kanıt zinciri,
> triyaj) AI yüzeylerine taşıyarak kuruyor.

Kısaca farklılaşma: rakiplerin çoğu ya **statik tripwire** (Canarytokens) ya
**altyapı deception'ı** (Acalvio/CounterCraft) ya da **prompt-güvenlik
guardrail'ı** (Prompt Security/SentinelOne, Llama Prompt Guard) satar. MIRAGE
ise **veri + prompt + ajan çıktısı** yüzeylerini tek kanıt/triyaj zincirinde
birleştirir ve deception'ı yalnızca "alarm" değil **sızıntı yakalama + dışa
aktarım** olarak konumlar.

## 2. Pazar manzarası

Deception teknolojisi pazarı büyüyor: 2026'da ~**3,36 milyar USD**, 2033'te
~**8,30 milyar USD** ve **%13,8 CAGR** öngörülüyor
([Coherent Market Insights](https://www.coherentmarketinsights.com/industry-reports/deception-technology-market)).

Paralel olarak AI saldırı yüzeyi hızla büyüyor:

- **GitHub Copilot CVE-2025-53773** — prompt injection ile uzaktan kod
  yürütme (CVSS 9,6) ([MDPI derlemesi](https://www.mdpi.com/2078-2489/17/1/54)).
- **RAG zehirlenmesi** — 5 özenle hazırlanmış doküman AI yanıtını %90
  oranında manipüle edebiliyor (aynı derleme).
- **Vahşi doğada IDPI** — Google, Kasım 2025–Şubat 2026 arasında web
  içeriğine gömülü kötü niyetli prompt-injection yükünde **%32 artış** tespit
  etti ([Palo Alto Unit 42](https://unit42.paloaltonetworks.com/ai-agent-prompt-injection)).
- **M&A doğrulaması** — Prompt Security, SentinelOne tarafından ~**159 milyon
  USD** bedelle satın alındı (Ağu/Eyl 2025)
  ([Nightfall derlemesi](https://www.nightfall.ai/blog/prompt-security-reviews)).

### 2.1. Kategoriler

| Kategori | Ne satar | Temsilci oyuncular |
|---|---|---|
| Statik tripwire / canary token | Dokunulunca alarm veren sahte dosya/anahtar | Thinkst Canary & Canarytokens, Tracebit, OpenCanary |
| Altyapı deception'ı | Ağ/endpoint/OT ölçeğinde otonom decoy | Acalvio ShadowPlex, CounterCraft, Illusive, Fidelis |
| AI honeypot (araştırma) | LLM ile "konuşan" servis taklidi | VelLMes, shelLM/AdvancedShelLM, LLMPot, HoneyGPT |
| Prompt/agent güvenliği | Runtime guardrail, injection savunması, MCP gateway | Prompt Security (SentinelOne), Llama Prompt Guard 2, Azure Prompt Shields |
| Sentetik veri deception'ı | Gerçekçi ama sahte kayıt üretimi | Resecurity, SDV/MOSTLY AI tabanlı çözümler |

### 2.2. Araştırma cephesi (AI honeypot)

- **VelLMes** (IEEE EuroS&PW 2025): SSH/MySQL/POP3/HTTP servislerini taklit
  eder; 89 insan saldırganla değerlendirildi, ~**%30'u gerçek sistemle
  konuştuğunu sandı**; 10 internet örneğinde gerçek saldırılar yakalandı
  ([HF paper](https://huggingface.co/papers/2510.06975)).
- **AdvancedShelLM / shelLM**: durum tutan, çok-ajanlı SSH deception'ı.
- **Honeyval**: LLM HTTP honeypot'ları için 16 arka uç uygulamaya dayalı
  değerlendirme çerçevesi.
- **SANDMAN**: Big Five kişilik modeliyle persona çeşitlendirme (parmak izini
  zorlaştırma).
- **Honeyquest** (arXiv 2606.21037): AI saldırganlara karşı deception'ın
  "çekicilik" ölçümü.
- Küratörlü kaynak: [Awesome AI Deception](https://github.com/0xNslabs/Awesome-AI-Deception).

## 3. Rakip haritası (özet)

| Oyuncu | Güçlü | Zayıf / boşluk |
|---|---|---|
| **Thinkst Canary** | "Her alarm gerçektir" — neredeyse sıfır yanlış-pozitif; fiziksel/sanal/bulut form faktörleri; Canarytokens ücretsiz | Statik; AI ajanı bağlamı/çıktısı yok; kanıt zinciri yok |
| **Acalvio ShadowPlex** | Kurumsal ölçek, otonom decoy, davranış analitiği | AI-agent yüzeyi (prompt/çıktı) dışında; ağır platform |
| **CounterCraft** | Hedefli deception + tehdit istihbaratı toplama | AI yüzeyi yok; kurumsal fiyat |
| **Tracebit** | IaC ile ölçekli token, SIEM'e hazır yönlendirme | Ağırlıklı tripwire; prompt/ajan katmanı yok |
| **Prompt Security (SentinelOne)** | Runtime guardrail, inline injection savunması, MCP gateway, red teaming | Kanıt zinciri/honeytoken deception'ı yok; genel SaaS/CRM kapsamı dışı |
| **Llama Prompt Guard 2 / Azure Prompt Shields** | Model-seviyesi injection sınıflandırma | Bağlam-özel deception + yakalama + triyaj yok |

**Boşluk:** kimse "deception yakalama + kurcalanamaz kanıt + triyaj + SIEM
dışa aktarımı" zincirini AI ajanı yüzeyine uçtan uca bağlamıyor. MIRAGE'ın
pivotu tam bu boşluğa oturuyor.

## 4. MIRAGE'ın konumu ve farklılaşması

Depodaki gerçek yetenekler (pivotun taşıyıcıları):

- **Honeytoken / XLSX takip** — dosya açılışını yakalayan pasif token
  (`honeytoken.py`).
- **Prompt canary** — ajan bağlamına (system prompt / RAG / agent memory)
  işlenen işaret; çıktıda görünürse sızıntı (`agent/prompt_canary.py`).
- **Kanıt zinciri** — HMAC ile kurcalanamaz kayıt (`evidence_store.py`).
- **Triyaj defteri** — append-only, kanıt zincirine bağlı (`triage_store.py`).
- **SIEM/SOAR dışa aktarımı** — Splunk HEC / webhook (`siem.py`).
- **Ajan guard** — satır-içi API/MCP koruması; ihlalde blok (`agent/guard.py`).
- **Dinamik LLM honeypot** — konuşan deception + canary yakalama
  (`honeypot.py`).
- **Red-team tarayıcı + CI kapısı** — prompt artefaktlarında
  injection/jailbreak/gizli-Unicode taraması (`redteam.py`).

Farklılaşma üç eksende:

1. **Tek zincir:** veri (XLSX) + prompt (canary) + ajan çıktısı (scan/guard) →
   aynı kanıt/triyaj/SIEM hattı.
2. **Yakalama > oyalama:** deception yalnızca oyalamaz; sızıntıyı kanıtla
   yakalar.
3. **Deterministik çekirdek + opsiyonel LLM:** LLM yoksa da savunma çalışır
   (heuristic fallback). Bu, "LLM'e bağımlı" rakiplere karşı bir
   dayanıklılık farkıdır.

## 5. AI/AI-agent pivot yol haritası

Durum: **yol haritasındaki tüm iş kalemleri tamamlandı.** Her dilim tek amaçlı
ayrı bir PR olarak açıldı, CI yeşil geçti ve birleştirildi.

Tamamlanan dilimler (her biri ayrı PR, CI yeşil):

| # | Dilim | PR | Modül |
|---|---|---|---|
| 1 | Ajan guard (satır-içi API/MCP koruması) | #26 | `agent/guard.py` |
| 2 | SIEM/SOAR dışa aktarımı (Splunk HEC / webhook) | #27 | `siem.py` |
| 3 | Dinamik LLM honeypot (deception + canary yakalama) | #28 | `honeypot.py` |
| 4 | Prompt red-team tarayıcı + CI injection kapısı | #29 | `redteam.py` |
| 5 | MCP gateway (politika + sunucu riski + denetim) | #31 | `mcp_gateway.py` |
| 6 | Zehirli RAG / veri kaynağı guard'ı | #32 | `rag_guard.py` |
| 7 | Ajan davranış analitiği (niyet skoru) | #33 | `behavior.py` |
| 8 | Otonom deception orkestrasyonu | #34 | `deception.py` |
| 9 | Merkle + harici zaman damgası çapası | #35 | `merkle_anchor.py` |
| 10 | Regex ötesi DLP (checksum + entropi + bağlam) | #36 | `dlp.py` |

Parite kontrolü (rakip yetenekleri → MIRAGE karşılığı):

| Rakip yeteneği | MIRAGE karşılığı | Durum |
|---|---|---|
| Ajan SDK/MCP hook otomatik enjeksiyon | `agent/guard.py`, `agent/middleware.py`, `mcp_gateway.py` | ✅ |
| SIEM/SOAR export | `siem.py` (Splunk HEC / webhook) | ✅ |
| Dinamik LLM honeypot (VelLMes/DECEIVE) | `honeypot.py` + `deception.py` | ✅ |
| Merkle / harici timestamp anchor | `merkle_anchor.py` | ✅ |
| Red-team / CI prompt taraması | `redteam.py` + CI kapısı | ✅ |
| ML tabanlı DLP (regex ötesi) | `dlp.py` | ✅ |

Kalan iş kalemleri: **yok.** Bundan sonrası dilim değil, ürünleştirme
yönüdür (aşağıdaki "Sonraki yön" başlığı).

### Sonraki yön (dilim değil, ürünleştirme)

- **HTTP yüzeyi:** `mcp_gateway` / `rag_guard` / `deception` / `merkle_anchor` /
  `dlp` modüllerini FastAPI uçlarına bağlamak (şu an kütüphane + CLI).
- **Çok-kiracılı kanıt/triyaj:** `team_id` zaten var; politika/limit katmanı.
- **Canlı entegrasyon:** gerçek Supabase migration uygulaması, gerçek LLM
  anahtarlarıyla yeşil koşu, gerçek RFC 3161/OTS çapası (bu ortamda
  kimlik bilgisi yok → non-claim).

## 6. Riskler ve non-claims

- **Honeypot inandırıcılığı LLM'e bağlı.** LLM yoksa deterministik fallback
  daha sınırlı inandırıcılık verir (çekirdek savunma yine çalışır).
- **Red-team kural seti muhafazakâr.** Yanlış-pozitifi önlemek için dar
  tutuldu; sofistike/çok dilli injection için özel kural gerekir.
- **Pazar sayıları üçüncü taraf tahminleridir**; kaynaklandırıldı ama bağımsız
  doğrulanmadı.
- **"Tam kapsama" iddiası yok.** MIRAGE deterministik bir taban + kapı sunar;
  rakiplerin geniş ürün yüzeyiyle bire bir eşleşme iddiası taşımaz.

## 7. Kaynaklar

- Coherent Market Insights — Deception Technology Market 2026–2033:
  https://www.coherentmarketinsights.com/industry-reports/deception-technology-market
- VelLMes (IEEE EuroS&PW 2025): https://huggingface.co/papers/2510.06975
- LLM Honeypot derlemesi (Emergent Mind): https://www.emergentmind.com/topics/llm-honeypot
- Honeyquest for LLMs (arXiv): https://arxiv.org/html/2606.21037v1
- Awesome AI Deception: https://github.com/0xNslabs/Awesome-AI-Deception
- MDPI — Prompt Injection in LLMs & AI Agent Systems: https://www.mdpi.com/2078-2489/17/1/54
- Palo Alto Unit 42 — Web-based IDPI in the wild: https://unit42.paloaltonetworks.com/ai-agent-prompt-injection
- Nightfall — Prompt Security (SentinelOne) incelemesi: https://www.nightfall.ai/blog/prompt-security-reviews
- Tracebit — deception vendor manzarası: https://ai.tracebit.com
- Acalvio — deception evrimi: https://www.acalvio.com/blog/active-defense/from-honeypots-to-ai-driven-defense-the-evolution-of-cyber-deception
- Resecurity — Sentetik veri ile deception: https://www.resecurity.com/blog/article/synthetic-data-a-new-frontier-for-cyber-deception-and-honeypots
- CounterCraft — canary token & honeytoken: https://www.countercraftsec.com/blog/canary-tokens-honeytokens-explained

_Bu belge bir AI ajanı (OpenHands) tarafından ali-ulu adına hazırlanmıştır._
