# HubSpot FY2024 and ServiceNow FY2025 — draft reading (executor session)

**Not a gold record.** See `README.md` in this directory.

## Partial archival header — added retroactively

This header was **not written at reading time**. It was added on 2026-08-13,
after the reading, from what could be verified afterwards. It is a partial
archive, not an archive.

| field | value | verifiable now? |
|---|---|---|
| reader | executor session (Claude Code) | — |
| model label | **not recorded at reading time** | no |
| reading date | 2026-08-13 17:45 (+02:00), from file mtime | weakly |
| instruction | **not archived**; the request was conversational | no |
| firm 1 | HubSpot, `srcsnap-hubspot-20241231-sec-v4`, 16 passages | yes |
| `source_id` 1 | `CIK0001404655/sec_10k/2025-02-12/36257e638feb2059` | yes |
| firm 2 | ServiceNow, `srcsnap-servicenow-20251231-sec-v4`, 101 passages | yes |
| `source_id` 2 | `CIK0001373715/sec_10k/2026-01-29/9bb399d4bc6ab5ca` | yes |
| `guideline_version` | `8d134ad00f92a92972dee37dbf0f284fbef846657d4bc2f9ad3fdf4bed6b716f` | yes |
| per-row confidence | **not recorded** | no |

**Context contamination.** The reading was made inside the session that had
already produced and inspected eight consolidation prototypes, C4's product
list for both firms, and the pipeline's own capability and task output for
HubSpot. That context cannot be reconstructed and cannot be subtracted. The
reading is therefore a diagnostic, and its agreement or disagreement with the
pipeline carries less weight than an unexposed reading would.

---

# Elle okuma: family · product · capability · task

Kaynak: yalnızca `data/runs/srcsnap-hubspot-20241231-sec-v4` (16 pasaj) ve
`srcsnap-servicenow-20251231-sec-v4` (101 pasaj). Model çağrısı yok. Dış bilgi
yok. Ontoloji: `docs/methodology/PRODUCT_CAPABILITY_TASK_ONTOLOGY.md`.

Kural 2 uygulandı: "AI-powered", "copilot", "agent" tek başına hiçbir şey
kazandırmaz. Kural 7 uygulandı: kanıt yetmiyorsa `unknown`.

---

# A. HUBSPOT INC — cutoff 2025-02-12

## A.1 Product family (2)

| # | family | dayanak |
|---|---|---|
| F1 | **Customer platform** | P4 "We provide a customer platform... a unified platform that includes three layers" |
| F2 | **Breeze** | P7 "Breeze includes Breeze Copilot...; Breeze Agents...; and Breeze Intelligence" |

`Breeze` bir aile, çünkü metin onu **üyeleri olan bir grup** olarak tanımlıyor
("Breeze includes X, Y, Z"). Ontolojinin aile tanımı tam olarak bu:
"a stable commercial grouping used to organize related products."

Üç katman (engagement Hubs / Smart CRM / connected ecosystem) aile DEĞİL —
mimari betimleme. `connected ecosystem` satılan bir şey değil (marketplace,
partner ağı, akademi), ürün de değil.

## A.2 Product (11)

**F1 Customer platform**

| # | ürün | ürün eşiği (ontoloji §Product) |
|---|---|---|
| P01 | Smart CRM | adlı + betimli; ayrı UX ("one login, one user interface") |
| P02 | Marketing Hub | adlı + betimli; ayrı plan ("free and paid tiers") |
| P03 | Sales Hub | aynı |
| P04 | Service Hub | aynı |
| P05 | Content Hub | aynı |
| P06 | Operations Hub | aynı |
| P07 | Commerce Hub | aynı |
| P08 | **Payments** | adlı + betimli; ayrı ticari sınır (işlem bazlı ödeme çözümü) — `ambiguity`: beyanname onu Commerce Hub'ın *içinde* konumluyor |

**F2 Breeze**

| # | ürün | not |
|---|---|---|
| P09 | Breeze Copilot | adlı, ama **hiçbir somut işlev betimlenmemiş** |
| P10 | Breeze Agents | adlı; tek zayıf işlev |
| P11 | Breeze Intelligence | adlı; "data enrichment solution" — somut |

**Ürün DEĞİL:** `Breeze` (aile), `connected ecosystem` (satılmıyor),
`Solutions Partner Program` (kanal), `HubSpot Academy` (eğitim), `INBOUND`
(etkinlik), `Clearbit`/`Cacheflow` (satın alınan, ürüne gömülen).

## A.3 Capability (58)

**P01 Smart CRM (7)** — P7, P11
- store a unified record of lead and customer information
- track interactions with contacts and customers
- report on pipeline and sales
- manage and govern team and business processes
- personalize interactions across web content, social media and email
- assemble a unified customer timeline across the business
- provide one login and one interface across the hubs

**P02 Marketing Hub (5)** — P7
- automate marketing workflows · send marketing email · publish to social media
- optimize content for search engines · report on marketing performance

**P03 Sales Hub (11)** — P7
- send templated sales email · track email opens and engagement
- conduct live chat with prospects · schedule meetings and calls
- alert representatives to lead and website-visit activity · score leads
- automate sales sequences · manage a sales pipeline · generate quotes
- forecast revenue · report on sales performance

**P04 Service Hub (10)** — P7
- conduct live chat with customers · deploy conversational bots
- track support calls · manage support tickets · route support requests
- publish a knowledge base · manage shared team email
- collect customer feedback · report on service performance
- set and track customer goals

**P05 Content Hub (10)** — P7
- build and edit web pages · publish blog content
- host video and podcast content · personalize website content per visitor
- build landing pages and forms · recommend SEO improvements
- capture leads through forms · report web analytics
- place calls-to-action · manage content files

**P06 Operations Hub (5)** — P7
- run programmable automation · sync customer data across systems
- curate customer data · clean and de-duplicate customer records
- query and transform customer data

**P07 Commerce Hub (5)** — P7
- issue invoices · generate quotes · manage subscriptions
- automate billing workflows · report on revenue

**P08 Payments (3)** — P7
- accept electronic funds transfers · create payment links
- take payment on a website, an email or a chat

**P09 Breeze Copilot (0)** — `unknown`
> "an AI-powered companion to boost productivity and make work easier"

Kural 2: somut müşteriye dönük eylem yok. Ürün var, işlevi bu belgeden
**bilinmiyor**. Bu bir boşluk değil, bir bulgu.

**P10 Breeze Agents (1)**
- execute multi-step work from strategy to execution — `ambiguity`: hangi iş

**P11 Breeze Intelligence (1)** — P7, P15
- enrich customer records with third-party company data

## A.4 Customer-facing task (32)

Biçim: `fiil + nesne + amaçlanan sonuç`. Birden çok capability tek task'a
katlanır. Teslim kanalı (web/email/chat) task ayırmaz — ontoloji §Task
granularity.

**Marketing Hub (3)**
1. Attract prospects to the business through search-optimized and social content. `[SEO, social]`
2. Nurture new leads toward sales readiness with automated email sequences. `[automation, email]`
3. Measure campaign performance to decide where marketing spend goes. `[reporting]`

**Sales Hub (6)**
4. Decide which lead a representative should work next. `[lead scoring, activity alerts]`
5. Run outbound sales outreach at scale without per-prospect manual work. `[templates, tracking, sequences]`
6. Book a meeting with a prospect without scheduling back-and-forth. `[scheduling]`
7. Move a deal from quote to signature. `[quoting, pipeline]`
8. Forecast revenue and hold the sales team to a number. `[forecasting, reporting]`
9. Answer a prospect's question while they are still on the site. `[live chat]`

**Service Hub (4)**
10. Resolve a customer issue raised on any channel from one queue. `[tickets, chat, team email, call tracking]`
11. Deflect routine support requests without a human agent. `[bots, knowledge base]`
12. Get each request to the right agent without manual triage. `[routing]`
13. Measure service quality and act on customer satisfaction. `[feedback, reporting, goals]`

**Content Hub (6)**
14. Publish and maintain a company website without a developer. `[pages, blog, files]`
15. Convert an anonymous website visitor into an identified lead. `[landing pages, forms, CTAs]`
16. Show a returning visitor content matched to what is known about them. `[smart content]`
17. Improve organic search ranking of published content. `[SEO recommendations]`
18. Distribute video and audio content to an audience. `[hosting]`
19. Measure site traffic and conversion. `[web analytics]`

**Operations Hub (3)**
20. Keep customer data consistent across the company's other systems. `[sync, curation]`
21. Remove duplicate and low-quality records from the customer database. `[data quality, cleanup]`
22. Automate a business process that spans two systems. `[programmable automation, transform]`

**Commerce Hub (3)**
23. Bill a customer and collect on the invoice. `[invoices, quotes]`
24. Manage recurring subscription revenue. `[subscriptions, billing automation]`
25. Report on revenue and collection. `[revenue reporting]`

**Payments (1)**
26. Accept payment from the customer's customer at the point of purchase. `[EFT, payment links, website/email/chat]`
> Üç kanal tek task. Ontoloji: "not split only by ... delivery channel unless
> the economic job differs." Ekonomik iş aynı.

**Smart CRM (4)**
27. Maintain one record of every interaction a customer has had with the business. `[unified record, tracking, timeline]`
28. Personalize an outbound interaction using that record. `[personalization]`
29. Govern team permissions and business process rules. `[governance]`
30. Report on pipeline and business performance. `[pipeline reporting]`

**Breeze Intelligence (1)**
31. Complete a thin customer record with external firmographic data. `[enrichment]`

**Breeze Agents (1)**
32. Execute a multi-step business workflow without a human running each step. — `ambiguity`

**Breeze Copilot (0)** — kanıt yok.

### HubSpot toplamı
```
2 family · 11 product · 58 capability · 32 task
task/capability = 0.55
AI eylemi tarif eden capability: 2/58 (%3)   [Agents 1, Intelligence 1]
```

---

# B. SERVICENOW, INC. — cutoff 2026-01-29

## B.1 Product family (4 beyan edilmiş + 2 yerleşmemiş)

P77 açık: *"Our products are grouped into four areas: Technology, Customer
Relationship Management ("CRM") and Industry, Core Business, and Creator and
Other."*

| # | family |
|---|---|
| G1 | Technology |
| G2 | CRM and Industry |
| G3 | Core Business |
| G4 | Creator and Other |

**Ontolojinin tek aile katmanı burada yetmiyor.** Belgede *iki* gruplama
seviyesi var: dört alan, ve alanların içinde `Asset Management`, `Telecom`,
`Retail`, `Legal and Contract Operations`, `Industry` gibi alt gruplar. Dördü
seçtim çünkü firma "grouped into four areas" diyerek onları *the* gruplama
olarak ilan ediyor. Alt seviye kaydedilemedi — bu bir **kayıp**, ve raporluyorum.

Dörde girmeyen ikisi: `ServiceNow AI Platform` ve `Now Assist` — bunlar dört
alanın *üstünde* duruyor (P86: "At the core of these solutions is the
ServiceNow AI Platform"). `product_family: unknown`. Firma beyan etmediği bir
aile uydurmuyorum.

## B.2 Product (34)

**G1 Technology (8)**
IT Service Management · IT Operations Management · Risk Management ·
**AI Control Tower** · **Security Operations** · **Operational Technology
Management** · IT Asset Management · Enterprise Asset Management

**G2 CRM and Industry (13)**
Customer Service Management · Sales and Order Management · Field Service
Management · Telecom Service Management · Network Inventory Management ·
Telecom Service Operations Management · Financial Services Operations ·
Healthcare and Life Sciences Service Management · Retail Service Management ·
Retail Operations · Public Sector Digital Services · Technology Provider
Service Management · Manufacturing Commercial Operations

**G3 Core Business (5 + 1 yerleşmemiş)**
HR Service Delivery · Workplace Service Delivery · Contract Management Pro ·
Legal Service Delivery · Source-to-Pay Operations ·
*Strategic Portfolio Management* (`family: unknown` — P18'in saydığı HR/legal/
finance/facilities listesine girmiyor, firma da yerleştirmiyor)

**G4 Creator and Other (4)**
App Engine · Workflow Data Fabric · RaptorDB · **Platform Privacy and Security**

**Aile üstü (3)**
ServiceNow AI Platform · Now Assist · ServiceNow Impact

### Üç zor karar

**(a) "X products" — üyesi adlandırılmamış gruplar → ÜRÜN, aile değil.**

`Security Operations products`, `Platform Privacy and Security products`,
`Operational Technology Management products` çoğul yazılmış ama beyanname
**tek bir üye adı vermiyor**. Bunları aile sayarsan altında ürün kalmaz ve
tarif edilen bütün işlevler düşer. Ontolojinin ürün eşiği zaten karşılanıyor:
adlı + betimli. → **ürün**, `ambiguity: filing writes "products" but names no
member`.

Karşı örnek: `Asset Management products include IT Asset Management and
Enterprise Asset Management` — burada üyeler **adlandırılmış**, o yüzden Asset
Management bir gruplama, ürünler ikisi.

Ayırt edici test: **grup adlandırılmış bir üyeye çözülüyor mu?**

**(b) 31 "Now Assist for X" / "AI agents for X" → ürün DEĞİL, capability.**

P78: *"Our Platform's integrated AI offering, **Now Assist**"* — tekil, bir
offering. "Now Assist for ITSM" onun ITSM'e uygulanmış hali. Beyanname bunlara
ayrı plan, ayrı UX, ayrı ticari sınır atfetmiyor. Betimlenen işlevler
**X ürününün capability'leri** olur, AI ile sağlandığı işaretlenerek.

**(c) `Automation Engine` → `not_offered` değil, ardıl ilişkisi.**

P28: *"Built on the foundation laid by our **legacy Automation Engine**
product"*. Ürün var**dı**, yerini Workflow Data Fabric aldı. Doğru kayıt:
`availability_status: discontinued` + `Automation Engine → Workflow Data
Fabric` ardıl bağı. Bu, projenin boylamsal katmanının aradığı şeyin ta kendisi.

**Ürün DEĞİL:** `Customer Support` (P101, destek hizmeti) · `Professional
Services` (P52, hizmet) · `ServiceNow University` (P76, eğitim — sınırda,
`ambiguity`) · `Moveworks` (satın alınan, Platform'a gömülmüş) · `RiseUp with
ServiceNow` (program).

`ServiceNow Impact` **ürün**: P100 "offered on a **subscription basis** and
provides customers with **software tools**" — ayrı ticari sınır + yazılım.

## B.3 Capability (185) — özet, AI işaretli

| ürün | cap | AI | ürün | cap | AI |
|---|---|---|---|---|---|
| IT Service Management | 11 | 3 | Customer Service Management | 11 | 5 |
| IT Operations Management | 7 | 2 | Sales and Order Management | 10 | 3 |
| Risk Management | 12 | 6 | Field Service Management | 8 | 4 |
| AI Control Tower | 3 | 3 | Telecom Service Management | 1 | 0 |
| **Security Operations** | **8** | **4** | Network Inventory Mgmt | 0 | 0 |
| **OT Management** | **7** | **2** | Telecom Service Ops Mgmt | 0 | 0 |
| IT Asset Management | 7 | 2 | Financial Services Operations | 3 | 0 |
| Enterprise Asset Mgmt | 6 | 3 | Healthcare & Life Sciences | 2 | 0 |
| HR Service Delivery | 9 | 4 | Retail Service Management | 1 | 0 |
| Workplace Service Delivery | 7 | 3 | Retail Operations | 2 | 0 |
| Contract Management Pro | 5 | 3 | Public Sector Digital Svcs | 2 | 0 |
| Legal Service Delivery | 5 | 1 | Technology Provider Svc Mgmt | 1 | 0 |
| Source-to-Pay Operations | 8 | 3 | Manufacturing Comm. Ops | 3 | 0 |
| Strategic Portfolio Mgmt | 5 | 2 | App Engine | 8 | 4 |
| **Platform Privacy & Sec.** | **7** | **3** | Workflow Data Fabric | 5 | 0 |
| ServiceNow AI Platform | 3 | 0 | RaptorDB | 2 | 0 |
| **Now Assist** | **13** | **13** | ServiceNow Impact | 3 | 1 |

**Toplam 185 capability, 74'ü AI eylemi (%40).**

İki ürün **sıfır** capability alıyor — `Network Inventory Management` ve
`Telecom Service Operations Management`. P9 üçünü tek cümlede geçiyor:
> "Telecom Service Management, Network Inventory Management and Telecom Service
> Operations Management, combined with Sales and Order Management, enables
> telecom service providers to manage customer service and infrastructure
> operations across front, middle and back-office functions."

Bir cümle, üç ürün, hiçbirine özgü işlev yok. Kural 7: adından işlev
türetmiyorum. Ürün var, capability **`unknown`**. Cümlenin tarif ettiği tek
işlevi `Telecom Service Management`'a veriyorum, `ambiguity` ile.

### Örnek: tam capability listesi, IT Service Management (P67)
```
provide predictive intelligence on IT incidents
manage and respond to IT incidents
automate routine IT tasks and requests
report performance analytics on IT service
track and validate IT changes in real time
manage IT change deployment
manage IT knowledge articles
collaborate on issue resolution
[AI] automate incident triage
[AI] generate incident summaries
[AI] recommend intelligent incident resolutions
```

### Örnek: Security Operations (P23) — pipeline'ın SIFIR ürettiği yer
```
identify security incidents and vulnerabilities
prioritize threats by potential impact
integrate internal and third-party vulnerability data
automate threat and vulnerability response
provide security leaders visibility into security posture
[AI] interact with security data through natural language
[AI] provide context-aware insights for incident resolution
[AI] recommend actions for vulnerability assessment
```

### Örnek: Now Assist (P78)
```
[AI] select among ServiceNow, third-party or proprietary language models
[AI] process text, image, audio and video data
[AI] deploy out-of-the-box AI agents
[AI] integrate AI agents built into third-party applications
[AI] create custom AI agents using natural language
[AI] govern AI agents with monitoring and guardrails
[AI] manage dataset creation for AI
[AI] benchmark AI model performance
[AI] report AI adoption, usage and performance analytics
[AI] retain human-in-the-loop control over AI-generated changes
[AI] search across the enterprise
[AI] handle service requests automatically through a virtual agent
[AI] complete tasks across diverse business applications
```

## B.4 Customer-facing task (98)

| ürün | task | ürün | task |
|---|---|---|---|
| IT Service Management | 5 | Customer Service Management | 5 |
| IT Operations Management | 4 | Sales and Order Management | 5 |
| Risk Management | 6 | Field Service Management | 4 |
| AI Control Tower | 2 | Telecom Service Management | 1 |
| Security Operations | 4 | Network Inventory Mgmt | 0 |
| OT Management | 4 | Telecom Service Ops Mgmt | 0 |
| IT Asset Management | 4 | Financial Services Operations | 2 |
| Enterprise Asset Mgmt | 3 | Healthcare & Life Sciences | 2 |
| HR Service Delivery | 5 | Retail Service Management | 1 |
| Workplace Service Delivery | 4 | Retail Operations | 2 |
| Contract Management Pro | 3 | Public Sector Digital Svcs | 2 |
| Legal Service Delivery | 3 | Technology Provider Svc Mgmt | 1 |
| Source-to-Pay Operations | 4 | Manufacturing Comm. Ops | 3 |
| Strategic Portfolio Mgmt | 3 | App Engine | 4 |
| Platform Privacy & Security | 4 | Workflow Data Fabric | 3 |
| ServiceNow AI Platform | 2 | RaptorDB | 2 |
| Now Assist | 5 | ServiceNow Impact | 2 |

### Örnek: IT Service Management (11 capability → 5 task)
1. Resolve an IT incident from report to closure. `[incident mgmt, triage, summaries, recommendations, knowledge]`
2. Deploy an IT change without breaking a running service. `[change tracking, validation, deployment]`
3. Fulfil a routine IT service request without an engineer touching it. `[request automation]`
4. Anticipate IT service degradation before users report it. `[predictive intelligence]`
5. Report IT service performance against regulatory and risk requirements. `[analytics, process optimization]`

### Örnek: Security Operations (8 capability → 4 task)
1. Triage a security incident to the analyst who should own it. `[identify, prioritize by impact]`
2. Decide which vulnerability to remediate first. `[prioritize, third-party data, AI recommendations]`
3. Investigate a threat by asking questions in plain language. `[natural-language interaction, context-aware insight]`
4. Report the organization's security posture to leadership. `[metric analysis, visibility]`

### Örnek: Payments karşılığı — Source-to-Pay Operations (8 → 4)
1. Raise and approve a purchase request within spending policy. `[initiate conversationally, pre-fill, policy check]`
2. Onboard a new supplier and negotiate terms. `[supplier mgmt, onboarding]`
3. Pay a supplier invoice. `[accounts payable]`
4. Monitor supplier performance against contract. `[performance monitoring]`

### ServiceNow toplamı
```
4 family (+2 yerlesmemis) · 34 product · 185 capability · 98 task
task/capability = 0.53
AI eylemi tarif eden capability: 74/185 (%40)
```

---

# C. Ölçülen farklar — elle okuma vs. pipeline

| | HubSpot elle | HubSpot C4 | ServiceNow elle | ServiceNow C4 |
|---|---|---|---|---|
| family (kullanılan) | 2 | 0 | 4 | 0 |
| product | 11 | 7 | 34 | 28 |
| capability | 58 | 66 | 185 | 150 |
| task | 32 | 64 | 98 | *(koşulmadı)* |
| **task/capability** | **0.55** | **0.97** | **0.53** | — |
| AI capability | 2 (%3) | 5 (%8) | 74 (%40) | 63 (%42) |

## Üç yapısal ayrım

**1. Task katmanı pipeline'da özdeşlik işlevi.** 66 capability → 64 task.
Elle okumada 58 → 32. Ontoloji task'ı "the economically meaningful job"
diye tanımlıyor ve "not merely a UI click" diyor — yani task capability'den
**az** olmalı. Pipeline'ın task aşaması capability'leri yeniden yazıyor.

**2. Aile katmanı hiç kullanılmıyor, ama boşluk bırakıyor.** C4'te `family`
seviyeli 4 aday VALIDATED PRODUCTS'a girmiyor; altlarındaki 5 AI varlığının
işlevleri düşüyor. Elle okumada `Security Operations`, `Platform Privacy and
Security`, `OT Management` **ürün** — çünkü adlandırılmış üyeleri yok. 22
capability, 9'u AI, 12 task kurtarılıyor.

**3. `unknown` üretilmiyor.** 150 capability'nin 150'si `confidence: high`,
150'si `S5`, `ambiguity` 0. Elle okumada 2 ürün sıfır capability
(`Network Inventory Management`, `Telecom Service Operations Management`),
1 ürün sıfır capability (`Breeze Copilot`), ve 9 kayıt `ambiguity` taşıyor.

## İki ingestion bulgusu

**P35 ve P21 birleşik pasajlar.** P35'in başlığı "Core Business" ama ilk
cümlesi *"Our **Technology** products help companies unite technology..."*.
P21'in başlığı "Creator and Other" ama ilk cümlesi *"Our **CRM and Industry**
products help organizations..."*. Bölüm geçiş paragrafları; başlık bir
bölümden, gövde diğerinden. ServiceNow'da pasaj başlığı ürün atfı için
güvenilmez.

**Mobilya pasajları.** 101 pasajın **44'ü** ≤60 karakter. Bunun **36'sı** saf
mobilya (`Part I`, `N Table of Contents`, `2025 Annual Report N Table of
Contents`, `>Item 1. Business`), **8'i** başlık/tablo artığı (`People Led`,
`Data Driven`, `Technology`, `CRM and Industry`, `Human Capital Management`,
`29,187 EMPLOYEES on a full-time basis`, `14,601 of whom are in the United
States`, `Workforce Metrics As of December 31, 2025, we employed:`).

**Gerçek metin 57 pasajda.** Yani ServiceNow'un "101 pasaj" sayısı ürün
çıkarımı için 57 pasaj demek — ve capability koşusunun kanıt verdiği 24 pasaj,
101'in değil **57'nin** %42'si. Oran sanıldığından iyi.
