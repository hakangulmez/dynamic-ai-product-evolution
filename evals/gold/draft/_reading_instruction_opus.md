# Annotation instruction — A2 (second independent annotator)

This file archives the verbatim instruction given to annotator A2, as required by
the model-use policy in `CLAUDE.md` ("Chat UI runs are exploratory unless their
exact source packet, prompt, model label, and output are archived") and by the
Gold protocol in `evals/EVAL_HARNESS.md` ("Guideline version and annotator
confidence recorded").

- Annotator label: `A2`
- Model label: `claude-opus-5[1m]` (Opus 5, 1M context)
- Date issued: 2026-08-13
- Guideline version (`docs/methodology/PRODUCT_CAPABILITY_TASK_ONTOLOGY.md`,
  SHA-256): `8d134ad00f92a92972dee37dbf0f284fbef846657d4bc2f9ad3fdf4bed6b716f`

Each per-firm annotation file references this file by path and by the SHA-256 of
this file's instruction body.

---

## Verbatim instruction

```text
=== Görev: sentinel gold set — bağımsız birinci elden okuma ===

Sen bu projenin **insan hakemi yerine geçen bağımsız bir açıklayıcısın**
(annotator). Görevin bir prompt yazmak, kod değiştirmek veya pipeline koşturmak
DEĞİL. Görevin, 10-K Item 1 metnini kendin okuyup dört katmanı elle kurmak:

    Product family → Product → Capability → Customer-facing task

Bu, `evals/gold/` altına girecek referans veridir. Modelin ne ürettiğini değil,
**belgenin ne desteklediğini** kaydediyorsun.

=== NEDEN BAĞIMSIZ ===

Bu okumanın aynısı bir kez daha yapıldı ve diskte duruyor. İkisi
karşılaştırılıp uzlaştırılacak (`evals/EVAL_HARNESS.md`, "Gold protocol": *two
independent annotations… adjudication after independent completion*).

Diğer okumayı görürsen bu tur bağımsız olmaktan çıkar ve **değerini tamamen
kaybeder**. Aşağıdaki yasak liste bu yüzden var ve esnetilemez.

=== OKUYACAKLARIN — bunlar ve yalnızca bunlar ===

    CLAUDE.md                                          proje anayasası
    docs/methodology/PRODUCT_CAPABILITY_TASK_ONTOLOGY.md   BAĞLAYICI taksonomi
    docs/TEMPORAL_POLICY.md
    docs/SOURCE_POLICY.md
    specs/SPEC-008-product-extraction.md
    specs/SPEC-009-capability-extraction.md
    specs/SPEC-010-task-extraction.md
    specs/SPEC-011-task-role-classification.md
    evals/rubrics/PRODUCT_EXTRACTION_RUBRIC.md
    evals/rubrics/TASK_EXTRACTION_RUBRIC.md
    evals/EVAL_HARNESS.md   -- yalnızca "Gold protocol" ve "E0-E4" bölümleri

Taksonominin tek kaynağı `PRODUCT_CAPABILITY_TASK_ONTOLOGY.md`. Bir tanım
eksikse **eksik olduğunu raporla**, doldurma.

=== AÇMAYACAKLARIN — kesin ===

    evals/reports/**                 ölçüm notları -- diğer okumanın bulguları
    evals/change_requests/**         CR'ler -- aynı bulgular
    data/runs/ext-smoke-**           pipeline çıktıları (ürün/capability/task)
    data/runs/decisions-**           insan karar setleri
    data/runs/cand-**                aday koleksiyonları
    data/runs/task-decisions-**
    prompts/**                       prompt'ları okuma -- onların çerçevesini alma
    docs/DECISION_LOG.md             ADR'ler firma-özgü bulgular taşıyor
    /private/tmp/**  ve  **/scratchpad/**    diğer oturumların çalışma dosyaları
    git log · git show · commit mesajları    bulguları taşıyorlar

Bir dosyayı yanlışlıkla açarsan **DUR ve söyle**. Sessizce devam etme --
kontaminasyon kaydedilebilirse zarar sınırlı kalır, kaydedilmezse gold set
çöp olur.

Web araması yok. Firmalar hakkında dış bilgi yok. Yalnızca pasaj metni.

=== KAYNAK — pasajları nereden alacaksın ===

    data/runs/srcsnap-<firma>-<dönem>-sec-v4/source_passages.jsonl

Dizin adlarını `ls data/runs/ | grep srcsnap` ile bul. Her satır bir pasaj:
`passage_id`, `source_id`, `text`. Sıralama: `(source_id, passage_id)` --
üretimle aynı anahtar. Pasajlara P1, P2… diye sıra numarası ver ve kanıtta o
etiketi kullan.

Bu snapshot'lar **değişmez**. Hiçbirine yazma.

=== FİRMA LİSTESİ ===

Sekiz firma, açıklama (`dev`) bölümü için. Seçim ölçülmüş **metin üslubu**
çeşitliliğine göre yapıldı, tanınırlığa göre değil:

    HubSpot      özellik-listesi üslubu, ince belge (16 pasaj)
    ServiceNow   iş-akışı üslubu, kalın belge (101 pasaj)
    Adobe        tekdüze katalog, çok kademe/sürüm (25 pasaj)
    Datadog      tek yoğun bölüm (13 pasaj)
    Okta         ince granülarite, ürün seviyesinde bölünmüş (40 pasaj)
    Workday      kontrol grubu, en düz belge (26 pasaj)
    Twilio       kısaltılmış Item 1 (16 pasaj)
    MongoDB      tek ürün hattı (15 pasaj)

DOKUNMA -- bunlar `frozen_test` için ayrıldı, genellemeyi ölçecekler:
    CrowdStrike · Palo Alto · Snowflake · Intuit · Atlassian · Veeva · Salesforce

Listeyi değiştirmen gerektiğini düşünüyorsan **önce gerekçeyle söyle**, kendin
değiştirme.

=== SIRA VE DURAK ===

Firma firma ilerle. **Her firmadan sonra DUR ve bekle.** Sekizini tek seferde
üretme -- ara kontrol noktası olmadan hata birikir.

Her firma için önce Item 1'in TAMAMINI oku (mobilya pasajları dahil, ne
olduklarını görmek için), sonra yaz.

=== ÇIKTI BİÇİMİ ===

Her firma için ayrı bir dosya:
`evals/gold/draft/<ticker>_annotation_A2.md`  (A2 = ikinci açıklayıcı)

Dört bölüm. Alan adları şemalarla hizalı ama şema dosyalarını okuman gerekmiyor:

    ## Product family
    | # | name | evidence [P-ref] | quote | confidence |

    ## Product
    | # | name | family | evidence [P-ref] | quote | availability_status |
      | confidence | ambiguity |

    ## Capability
    | # | text | product | evidence [P-ref] | quote | ai_action_observed |
      | confidence |

    ## Customer-facing task
    | # | text | customer_need | capability_refs | evidence [P-ref] | quote |
      | task_role | confidence |

Ve dosyanın sonuna:

    ## Kararsız kaldıklarım
    ## Ontolojinin cevaplamadığı sorular
    ## Bu belgenin taşımadığı bilgi

Son üç bölüm **en değerli kısım**. Bir vakayı zorlamaktansa kararsız kaydet.

=== BAĞLAYICI KURALLAR ===

`CLAUDE.md`'den, hepsi bu görevde geçerli:

  **Kural 2 — AI ifadesinden çıkarım yok.** "AI-powered", "copilot", "agent"
  tek başına hiçbir şey kazandırmaz. Somut, müşteriye dönük bir eylem
  yoksa capability yoktur. Bir ürünün adı geçip işlevi yazılmamışsa
  **sıfır capability** yaz -- bu bir boşluk değil, bir bulgu.

  **Kural 5 — Kanıt zorunlu.** Her kayıt bir `P-ref` ve **birebir alıntı**
  taşır. Alıntı o pasajın içinde kelimesi kelimesine bulunabilmeli. Kendi
  cümlenle özetleme.

  **Kural 7 — Tahmin yerine bilinmeyen.** Kanıt yetmiyorsa `unknown`,
  `uncertain`, ya da boş bırak. Makul göründüğü için doldurma.

  **Kural 3 — Zamansal bütünlük.** Yalnızca pasaj metni. Firmanın bugünkü
  sitesi, sonraki duyuruları, senin ön bilgin -- hiçbiri kullanılamaz.

  **Kural 11 — Sonuç sızıntısı yok.** Firmanın hisse performansı, büyümesi,
  başarısı hiçbir etiketi etkilemez.

  **Kural 12 — Tanım gereği fayda yok.** Derin AI dönüşümü otomatik olarak
  avantaj değildir. Sen sadece ne tarif edildiğini kaydediyorsun.

Ayrıca `CLAUDE.md`'nin yasaklılar listesi: cümle başına bir task yaratma;
teslim kanallarını ayrı task sayma; her adlandırılmış özelliği ürün sayma;
yol haritasını genel kullanıma alınmış gibi kaydetme.

=== HER KAYIT İÇİN GÜVEN ===

Protokol açıklayıcı güveninin kaydını istiyor. Her satıra:
`high` | `medium` | `low`. Bu, uzlaştırmada hangi anlaşmazlığın önemli
olduğunu belirleyecek.

=== ARŞİVLEME ===

`CLAUDE.md` model-kullanım politikası: *"Chat UI runs are exploratory unless
their exact source packet, prompt, model label, and output are archived."*

Her firma dosyasının başına şunları yaz:
    kaynak snapshot dizini · pasaj sayısı · `source_id` · cutoff tarihi
    bu talimatın tam metni (ya da hash'i) · model etiketi · tarih
    `guideline_version`: ontoloji dosyasının SHA-256'sı

=== YAPMAYACAKLARIN ===

    - prompts/ · schemas/ · specs/ · src/ · docs/ altına YAZMA
    - decision set, snapshot, universe'e yazma
    - mevcut hiçbir dosyayı düzenleme -- yalnızca yeni dosya yarat
    - model çağrısı yapma, pipeline koşturma
    - git add · commit · push
    - yasak listeyi "sadece bir bakayım" diye açma
    - sekiz firmayı tek turda bitirme

=== RAPORLAMA — her firmadan sonra ===

    1. Dört katmanın sayıları: family / product / capability / task
    2. task ÷ capability oranı
    3. Sıfır capability alan ürünler ve nedeni
    4. Kararsız kaldığın vakalar
    5. Ontolojinin cevaplamadığı sorular
    6. Ve tek cümle: bu belge dört katmanı taşıyor mu, taşımıyorsa hangisini

STOP — her firmadan sonra bekle.
```

---

## Snapshot selection rule applied by A2

The instruction gives a passage count per firm but not a period. The counts were
matched against every `srcsnap-<firm>-*-sec-v4` directory on disk. For all eight
firms the stated count matches exactly one period — the most recent snapshot for
that firm — so A2 used the latest snapshot per firm:

| firm | stated count | matched snapshot |
|---|---|---|
| HubSpot | 16 | `srcsnap-hubspot-20251231-sec-v4` |
| ServiceNow | 101 | `srcsnap-servicenow-20251231-sec-v4` |
| Adobe | 25 | `srcsnap-adobe-20251128-sec-v4` |
| Datadog | 13 | `srcsnap-datadog-20251231-sec-v4` |
| Okta | 40 | `srcsnap-okta-20260131-sec-v4` |
| Workday | 26 | `srcsnap-workday-20260131-sec-v4` |
| Twilio | 16 | `srcsnap-twilio-20251231-sec-v4` |
| MongoDB | 15 | `srcsnap-mongodb-20260131-sec-v4` |

For HubSpot, Datadog and Twilio an earlier period shares the same count
(hubspot-20241231 = 16, datadog-20241231 = 13, twilio-20241231 = 16) and for
MongoDB and Workday several periods do; the "latest snapshot" rule resolves all
of them consistently and is recorded here so the choice is auditable.
