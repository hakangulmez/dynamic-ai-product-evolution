# HubSpot FY2025 — draft reading (Opus)

**Not a gold record.** See `README.md` in this directory: this is a
model-authored reading awaiting human adjudication, and the two readings
held here are not independent of each other.

## Archival header

| field | value |
|---|---|
| firm | HubSpot, Inc. |
| ticker | HUBS |
| source snapshot directory | `data/runs/srcsnap-hubspot-20251231-sec-v4` |
| passage count | 16 |
| `source_id` | `CIK0001404655/sec_10k/2026-02-11/2535543b3e09730d` |
| `company_id` | `CIK0001404655` |
| `source_type` | `sec_10k` |
| document publication date | 2026-02-11 |
| source-admission cutoff (`observation_cutoff_date`) | 2026-02-11 (filing date, per `docs/TEMPORAL_POLICY.md`) |
| analytical period assignment | FY2025 (fiscal year ended 2025-12-31) |
| content hash of source document | `2535543b3e09730d167e9db7823b86acdc2dfd1ca310c41e1e589936a8c63597` |
| reader | Opus, via Claude Code CLI |
| model label | `claude-opus-5[1m]` (Opus 5, 1M context) |
| annotation date | 2026-08-13 |
| instruction (full text) | `evals/gold/draft/_annotation_A2_instruction.md` |
| instruction SHA-256 | `2d72c6eccde50449b3d93a679a32d9a4b0524e69238faef6360a0302855479fb` |
| `guideline_version` (SHA-256 of `docs/methodology/PRODUCT_CAPABILITY_TASK_ONTOLOGY.md`) | `8d134ad00f92a92972dee37dbf0f284fbef846657d4bc2f9ad3fdf4bed6b716f` |
| passage ordering key | `(source_id, passage_id)` |
| sources consulted | this snapshot's `source_passages.jsonl` only |

## Passage index

P-refs are the ordinal position under the `(source_id, passage_id)` sort key.

| P-ref | `passage_id` | opening / section |
|---|---|---|
| P1 | `11fd6f02db6ff32d4f9f0ec9185811f1` | Available Information |
| P2 | `1baeb043e21f595cea2c5709f7c0bfda` | Human Capital Management |
| P3 | `27e5754b3c9eced795e196f40fba2be0` | Our Customer Platform |
| P4 | `2f4a7746c52b625e02c3e4cc46775894` | `> ITEM 1. BUSINESS` (heading stub, 18 chars) |
| P5 | `44e8083a7283e7657a2589fda4131818` | Competition |
| P6 | `4c3161bee5e0b55431d05b6f43584f43` | Overview |
| P7 | `4e1df938c8d4b6a81153419351933f4b` | Financial Information About Segments |
| P8 | `8698cfe9fee5d32fd5dcb1afabaf7b1c` | The HubSpot Approach |
| P9 | `88747550803154f80d217ecf02dc2e3c` | Our Services |
| P10 | `a9d8936302d9e9ac750366bbdd98b09d` | Marketing and Sales |
| P11 | `ae25c85b23499baff116e9ca1f510fa8` | Our Technology |
| P12 | `c234fc918e2d2f0cd973ae08aebfc31f` | Governmental Regulations |
| P13 | `c509a54b47f7635cc12868a84e0eb937` | Our Growth Strategy |
| P14 | `cd97bcff952481e17a831e4d0e80e362` | Our Customers |
| P15 | `e36093725acd739283cd5f9537224c55` | Intellectual Property |
| P16 | `e76dc2058caaf7bbc9c283d9278a6dc9` | Our Competitive Strengths |

Passages carrying no product/capability/task evidence (read in full, deliberately
not extracted from): P1, P2, P4, P7, P12, P14, P15. P5 (Competition), P10
(Marketing and Sales) and P11 (Our Technology) were read in full and produce no
entities for the reasons recorded under **Bu belgenin taşımadığı bilgi**.

---

## Product family

| # | name | evidence [P-ref] | quote | confidence |
|---|---|---|---|---|
| F1 | HubSpot customer platform | P6 | We provide an agentic customer platform that helps marketing, sales, and customer service teams drive business growth. | high |
| F2 | Engagement Hubs | P3 | Our customer platform, with engagement Hubs, our Smart CRM, and connected ecosystems enable companies to have a unified customer profile and connect with their customers at every part of their customer relationship lifecycle. | medium |

F2 nests inside F1 — see **Ontolojinin cevaplamadığı sorular**, question Q1.

---

## Product

| # | name | family | evidence [P-ref] | quote | availability_status | confidence | ambiguity |
|---|---|---|---|---|---|---|---|
| PR1 | HubSpot customer platform | F1 | P6 | We primarily sell our customer platform on a subscription basis. | general_availability | high | Product and family carry the same name. Admitted as a product under the ontology's bundle exception ("unless the bundle creates a distinct cross-product workflow"): P8 — "Our customer platform has one login, one user interface and one unified customer view." |
| PR2 | Smart CRM | F1 | P6 | a Smart customer relationship management product (“CRM”) | general_availability | high | Status could be `broadly_deployed_or_default` — P6 calls it "the foundational context layer" of the whole platform — but no passage states it is enabled by default, so the weaker status was kept (Rule 7). |
| PR3 | Breeze | F1 | P3 | Breeze is our AI that powers the customer platform, including our Smart CRM, engagement Hubs, and the connected ecosystem. | general_availability | medium | May instead be a product family containing PR4 and PR5, or an internal AI layer rather than an offering. No tier, price, GA date or beta qualifier anywhere in Item 1. |
| PR4 | Breeze Assistant | F1 | P3 | Breeze includes Breeze Assistant, a go-to-market assistant to boost productivity and make work easier | general_availability | low | Zero capabilities (see below). Availability inferred only from the present-tense "includes"; could equally be modelled as a component of PR3. |
| PR5 | Breeze Agents | F1 | P3 | Breeze Agents to help teams automate work, end-to-end, from strategy to execution. | general_availability | low | Same containment question as PR4. Its capabilities come from P8, which says "Our AI agents", not "Breeze Agents" — an in-document link, not a stated one. |
| PR6 | Marketing Hub | F2 | P3 | Marketing Hub is an all-in-one toolset for marketers to create brand awareness, influence deals, and orchestrate marketing campaigns towards sales readiness over the entire customer lifecycle. | general_availability | high | — |
| PR7 | Sales Hub | F2 | P3 | Sales Hub is designed to enhance the productivity and effectiveness of sales teams. | general_availability | high | — |
| PR8 | Service Hub | F2 | P3 | Service Hub is our customer service software designed to help businesses manage, respond and connect with customers. | general_availability | high | — |
| PR9 | Content Hub | F2 | P3 | Our Content Hub combines the power of customer relationship management and a content management system into one integrated platform. | general_availability | high | — |
| PR10 | Operations Hub | F2 | P3 | Operations Hub is designed to help businesses combine, clean, and activate customer data in a connected platform, automate business processes, eliminate time-consuming data cleanup, and query and transform data to enable customer insights and connections. | general_availability | high | — |
| PR11 | Commerce Hub | F2 | P3 | Commerce Hub is a B2B commerce suite that helps streamline the opportunity-to-cash process for businesses to get paid faster, increase revenue and save time. | general_availability | high | Called a "suite" in the text but is listed as a peer of the other Hubs; treated as a product, not a family. |
| PR12 | Payments | F2 | P3 | It includes an end-to-end payment solution (“Payments”) which enables customers to accept electronic funds transfers (e.g. credit card payments) from their customers in less time and with fewer tools. | general_availability | medium | Formally defined term with its own description, but presented as included in PR11 rather than separately purchasable. May be a capability of Commerce Hub instead of a product. |
| PR13 | Professional services | unknown | P9 | Our professional services are also available to customers who need additional assistance on a one-time or ongoing basis for an additional fee. | general_availability | low | A purchasable offering under the ontology's product test, but not software. The ontology does not say whether services are products (question Q4). Family membership is not stated. |

Availability status for PR6–PR11 is additionally supported by P3 — "Our Hubs are
available in both free and paid tiers with gradually increasing levels of
functionality that support the needs of our customers as their businesses grow."

---

## Capability

`ai_action_observed = yes` is recorded only where the passage states that AI, an
AI agent, or an AI-powered function performs the action. The ontology does not
define this field; the reading used here is recorded as question Q5.

| # | text | product | evidence [P-ref] | quote | ai_action_observed | confidence |
|---|---|---|---|---|---|---|
| C1 | Provide a unified customer profile across the connected platform | PR1 | P3 | enable companies to have a unified customer profile and connect with their customers at every part of their customer relationship lifecycle | no | high |
| C2 | Find and install third-party integrations and applications | PR1 | P3 | Over 2,000 integrations and applications are available for our users | no | high |
| C3 | Build custom applications and integrations on top of the platform | PR1 | P3 | Customers can build custom applications and integrations on top of our customer platform themselves, or through third party developers in our ecosystem. | no | high |
| C4 | Integrate the platform with other applications through open APIs | PR1 | P8 | features a variety of open application programming interfaces (“APIs”) that allows easy integration of our platform with other applications | no | high |
| C5 | Track interactions with contacts and customers | PR2 | P3 | allows businesses to track their interactions with contacts and customers | no | high |
| C6 | Manage customer activities | PR2 | P3 | manage their customer activities | no | high |
| C7 | Report on pipeline and sales | PR2 | P3 | report on their pipeline and sales | no | high |
| C8 | Manage and govern team and business processes | PR2 | P3 | manage and govern their team and business processes | no | high |
| C9 | Personalize the customer interaction across web content, social media and email | PR2 | P3 | personalize every aspect of the customer interaction across web content, social media engagement, and email messages across devices, including mobile | no | high |
| C10 | Automatically enrich customer records | PR2 | P8 | uses AI to automatically enrich customer records | yes | high |
| C11 | Maintain data quality | PR2 | P8 | maintain data quality | yes | high |
| C12 | Provide unified customer context that powers personalized experiences across engagement channels | PR2 | P8 | provide unified customer context that powers personalized experiences across all engagement channels | yes | high |
| C13 | Create a unified timeline of all interactions with a customer | PR2 | P8 | creates a unified timeline incorporating all the interactions across the business with a particular customer | no | high |
| C14 | Generate content | PR3 | P3 | content generation | yes | medium |
| C15 | Enrich data | PR3 | P3 | data enrichment | yes | medium |
| C16 | Research accounts | PR5 | P8 | researching accounts | yes | medium |
| C17 | Enrich data | PR5 | P8 | enriching data | yes | medium |
| C18 | Answer support questions | PR5 | P8 | answering support questions | yes | medium |
| C19 | Qualify leads | PR5 | P8 | qualifying leads | yes | medium |
| C20 | Orchestrate marketing campaigns towards sales readiness over the customer lifecycle | PR6 | P3 | orchestrate marketing campaigns towards sales readiness over the entire customer lifecycle | no | high |
| C21 | Marketing automation and email | PR6 | P3 | marketing automation and email | no | medium |
| C22 | Social media | PR6 | P3 | marketing automation and email, social media | no | low |
| C23 | Search engine optimization (SEO) | PR6 | P3 | social media, SEO, AEO | no | medium |
| C24 | Answer engine optimization (AEO) | PR6 | P3 | social media, SEO, AEO | no | medium |
| C25 | Reporting and analytics | PR6 | P3 | SEO, AEO, and reporting and analytics | no | medium |
| C26 | Deliver a personalized experience for prospects with less work for sales representatives | PR7 | P3 | deliver a personalized experience for prospects with less work for sales representatives | no | medium |
| C27 | Email templates and tracking | PR7 | P3 | email templates and tracking | no | medium |
| C28 | Conversations and live chat | PR7 | P3 | conversations and live chat, meeting and call scheduling | no | medium |
| C29 | Meeting and call scheduling | PR7 | P3 | meeting and call scheduling | no | medium |
| C30 | Lead and website visit alerts | PR7 | P3 | lead and website visit alerts | no | medium |
| C31 | Lead scoring | PR7 | P3 | lead scoring | no | medium |
| C32 | Sales automation | PR7 | P3 | sales automation | no | medium |
| C33 | Pipeline management | PR7 | P3 | pipeline management | no | medium |
| C34 | Quoting | PR7 | P3 | pipeline management, quoting, forecasting | no | medium |
| C35 | Forecasting | PR7 | P3 | quoting, forecasting, and reporting | no | medium |
| C36 | Reporting | PR7 | P3 | forecasting, and reporting | no | medium |
| C37 | Manage, respond and connect with customers | PR8 | P3 | designed to help businesses manage, respond and connect with customers | no | high |
| C38 | Conversations and live chat functionality | PR8 | P3 | conversations and live chat functionality | no | medium |
| C39 | Conversational bots | PR8 | P3 | conversational bots | no | medium |
| C40 | Call tracking | PR8 | P3 | call tracking | no | medium |
| C41 | Tickets and help desk | PR8 | P3 | tickets and help desk | no | medium |
| C42 | Automation and routing | PR8 | P3 | automation and routing | no | medium |
| C43 | Knowledge base | PR8 | P3 | knowledge base | no | medium |
| C44 | Team emails | PR8 | P3 | team emails | no | medium |
| C45 | Feedback and reporting tools | PR8 | P3 | feedback and reporting tools | no | medium |
| C46 | Customer goals | PR8 | P3 | and customer goals | no | low |
| C47 | Create new and edit existing web content | PR9 | P3 | enable businesses to create new and edit existing web content | no | high |
| C48 | Personalize websites for different visitors | PR9 | P3 | personalizing their websites for different visitors | no | high |
| C49 | Optimize websites to convert more visitors into leads and customers | PR9 | P3 | optimizing their websites to convert more visitors into leads and customers | no | high |
| C50 | Website pages | PR9 | P3 | Features include: website pages, business blogging | no | medium |
| C51 | Business blogging | PR9 | P3 | business blogging | no | medium |
| C52 | Video and podcast hosting | PR9 | P3 | video and podcast hosting | no | medium |
| C53 | Smart content | PR9 | P3 | smart content | no | low |
| C54 | Landing pages and forms | PR9 | P3 | landing pages and forms | no | medium |
| C55 | SEO recommendations | PR9 | P3 | SEO recommendations | no | medium |
| C56 | Forms and lead flow | PR9 | P3 | forms and lead flow | no | medium |
| C57 | Web analytics reporting | PR9 | P3 | web analytics reporting | no | medium |
| C58 | Calls-to-action | PR9 | P3 | calls-to-action | no | medium |
| C59 | File manager | PR9 | P3 | and file manager | no | medium |
| C60 | Combine, clean, and activate customer data | PR10 | P3 | combine, clean, and activate customer data in a connected platform | no | high |
| C61 | Automate business processes | PR10 | P3 | automate business processes, eliminate time-consuming data cleanup | no | high |
| C62 | Query and transform data to enable customer insights | PR10 | P3 | query and transform data to enable customer insights and connections | no | high |
| C63 | Programmable automation | PR10 | P3 | programmable automation | no | medium |
| C64 | Data sync | PR10 | P3 | data sync | no | medium |
| C65 | Data curation | PR10 | P3 | data curation | no | medium |
| C66 | Data quality tools | PR10 | P3 | and data quality tools | no | medium |
| C67 | Streamline the opportunity-to-cash process | PR11 | P3 | helps streamline the opportunity-to-cash process for businesses to get paid faster | no | high |
| C68 | Payment links | PR11 | P3 | Features include: payment links, invoices | no | medium |
| C69 | Invoices | PR11 | P3 | payment links, invoices, quotes | no | medium |
| C70 | Quotes | PR11 | P3 | invoices, quotes, subscription management | no | medium |
| C71 | Subscription management | PR11 | P3 | subscription management | no | medium |
| C72 | Automation and revenue reporting | PR11 | P3 | automation and revenue reporting | no | medium |
| C73 | AI-powered configure-price-quote (CPQ) | PR11 | P8 | AI-powered configure-price-quote (“CPQ”) capabilities | yes | medium |
| C74 | Automated billing | PR11 | P8 | automated billing | no | medium |
| C75 | Payment processing | PR11 | P8 | and payment processing to streamline the end-to-end quote-to-cash process | no | medium |
| C76 | Accept electronic funds transfers from end customers | PR12 | P3 | enables customers to accept electronic funds transfers (e.g. credit card payments) from their customers in less time and with fewer tools | no | high |
| C77 | Let the end customer buy and pay directly on a website, email or chat | PR12 | P3 | our customer's customer can buy and pay directly on a website, an email, or chat | no | high |
| C78 | Educate and train customers on using the platform | PR13 | P9 | We offer professional services to educate and train customers on how to leverage our customer platform | no | medium |
| C79 | Deliver onboarding guidance and one-on-one training | PR13 | P9 | they receive onboarding guidance in the product and in some cases receive one-on-one training from one of our on-boarding, inbound consultants, or technical consultants by web meetings | no | medium |
| C80 | Help customers adapt processes to be AI native and adopt HubSpot AI | PR13 | P9 | we embed Solution Architects with some customers to help them adapt their processes to be AI native and adopt HubSpot AI to run those processes | no | medium |

C73–C75 are attributed to PR11 because P8 places them in "an end-to-end commerce
solution" and P3 gives Commerce Hub as the only end-to-end commerce offering.
The link is an in-document inference, hence `medium`.

**Products with zero capabilities:** PR4 (Breeze Assistant).

---

## Customer-facing task

| # | text | customer_need | capability_refs | evidence [P-ref] | quote | task_role | confidence |
|---|---|---|---|---|---|---|---|
| T1 | Create and publish web pages and blog posts to establish an online presence | Publish and maintain an organization's own online content | C14, C47, C50, C51, C54, C59 | P3 | Our content tools enable businesses to create new and edit existing web content | core | high |
| T2 | Optimize published content so buyers find it through search and answer engines | Be discoverable by people searching for a solution | C23, C24, C55 | P8 | a system of engagement for efficiently engaging customers through search engine optimization (“SEO”), and answer engine optimization (“AEO”) | core | high |
| T3 | Convert anonymous website visitors into identified leads | Turn untracked interest into contactable prospects | C49, C53, C54, C56, C58 | P3 | optimizing their websites to convert more visitors into leads and customers | core | high |
| T4 | Run marketing campaigns across email and social channels over the customer lifecycle | Nurture prospective buyers toward a purchase decision | C20, C21, C22 | P3 | orchestrate marketing campaigns towards sales readiness over the entire customer lifecycle | core | high |
| T5 | Personalize content and messages to each individual customer | Make outbound communication relevant to the person receiving it | C9, C12, C48, C53 | P3 | personalize every aspect of the customer interaction across web content, social media engagement, and email messages across devices, including mobile | major_supporting | high |
| T6 | Host and serve video and podcast media to an audience | Distribute recorded media without operating hosting infrastructure | C52 | P3 | video and podcast hosting | peripheral | medium |
| T7 | Measure marketing and website performance | Know which marketing activity actually produces results | C25, C57 | P3 | web analytics reporting | major_supporting | medium |
| T8 | Score and prioritize leads so sellers work the best opportunities first | Focus limited selling time on the likeliest buyers | C19, C30, C31 | P3 | lead scoring | core | high |
| T9 | Research a target account before contacting it | Understand a prospective buyer before making contact | C16 | P8 | researching accounts | major_supporting | medium |
| T10 | Engage prospects through tracked email, chat and scheduled meetings to advance a deal | Hold and keep track of sales conversations with buyers | C26, C27, C28, C29, C32 | P3 | email templates and tracking, conversations and live chat, meeting and call scheduling | core | high |
| T11 | Manage the sales pipeline and forecast expected revenue | Know what revenue is likely to close and when | C7, C33, C35, C36 | P3 | pipeline management, quoting, forecasting, and reporting | core | high |
| T12 | Quote, bill and collect payment to complete the quote-to-cash process | Get paid for what has been sold | C34, C67, C68, C69, C70, C71, C72, C73, C74, C75, C76, C77 | P8 | AI-powered configure-price-quote (“CPQ”) capabilities, automated billing, and payment processing to streamline the end-to-end quote-to-cash process with fewer tools | core | medium |
| T13 | Resolve inbound customer support requests | Get help when something is wrong after a purchase | C18, C37, C38, C39, C40, C41, C42, C44 | P3 | Service Hub is our customer service software designed to help businesses manage, respond and connect with customers. | core | high |
| T14 | Let customers find answers themselves without contacting an agent | Get an answer immediately rather than waiting for a person | C39, C43 | P3 | knowledge base | major_supporting | low |
| T15 | Collect customer feedback and track service goals | Know whether customers are satisfied | C45, C46 | P3 | feedback and reporting tools, and customer goals | peripheral | medium |
| T16 | Consolidate and clean customer data so teams work from accurate records | Maintain one trustworthy record of each customer | C11, C60, C64, C65, C66 | P3 | combine, clean, and activate customer data in a connected platform | core | high |
| T17 | Enrich customer records with data the customer did not supply | Know more about a customer than they have volunteered | C10, C15, C17 | P8 | automatically enrich customer records | major_supporting | high |
| T18 | Query and transform customer data to answer business questions | Get answers out of accumulated customer data | C62 | P3 | query and transform data to enable customer insights and connections | major_supporting | medium |
| T19 | Maintain one unified view of each customer across every interaction | See everything known about a customer in one place | C1, C5, C6, C13 | P8 | creates a unified timeline incorporating all the interactions across the business with a particular customer | core | high |
| T20 | Connect the platform to other business applications and extend it with custom applications | Make purchased software work with the rest of a company's tools | C2, C3, C4 | P3 | Customers can build custom applications and integrations on top of our customer platform themselves, or through third party developers in our ecosystem. | major_supporting | high |
| T21 | Administer team membership, permissions and business processes | Control who inside the organization can do what | C8 | P3 | manage and govern their team and business processes | peripheral | medium |
| T22 | Automate a repeatable business process with custom logic | Remove manual steps from a recurring internal process | C61, C63 | P3 | programmable automation | major_supporting | low |
| T23 | Train staff to operate newly purchased software | Build in-house skill to run a system the organization just bought | C78, C79, C80 | P9 | We offer professional services to educate and train customers on how to leverage our customer platform | major_supporting | medium |

Channel splitting was deliberately avoided: T5 covers web, social and email as
one task, and T12 covers "a website, an email, or chat" as one task, because the
economic job does not differ by channel.

---

## Kararsız kaldıklarım

1. **Breeze: product, family, or internal layer?** P3 says "Breeze is our AI that
   powers the customer platform". That sentence reads as an internal technology
   layer, which the ontology excludes ("internal technologies not exposed to
   customers"), yet the same passage names two customer-facing sub-offerings
   inside it. I recorded Breeze as a product with `medium` confidence and both
   sub-offerings as products with `low`. An adjudicator could equally justify
   Breeze-as-family with two products, or Breeze-as-product with two
   capabilities. This is the single largest disagreement risk in this firm.

2. **Breeze Agents ↔ "Our AI agents".** All four agent capabilities (C16–C19)
   come from P8, which never says "Breeze". Breeze Agents is the only named agent
   offering in Item 1, so I attached them, but a strict Rule 7 reading would leave
   PR5 at zero capabilities and record C16–C19 against PR1 or as unattributed.

3. **Payments: product or capability of Commerce Hub?** It carries a formally
   defined term and its own description, but P3 frames it as included in Commerce
   Hub, not separately sold. Recorded as a product at `medium`.

4. **Bare feature-list nouns.** Roughly half the capability rows (C21–C36,
   C38–C46, C50–C59, C63–C72) are nouns from "Features include:" lists with no
   verb — "smart content", "customer goals", "file manager". They are concrete
   functions, not marketing abstractions, so Rule 2 does not exclude them, but
   they cannot be written as verb-object-outcome without me inventing the verb.
   I recorded them verbatim at `medium` (`low` where even the function is unclear:
   C22, C46, C53). An annotator who required a verb would produce roughly half the
   capability count I did.

5. **Professional services (PR13).** Purchasable and named, so it passes the
   ontology's product test, but it is human consulting, not software. Recorded at
   `low`. See Q4.

6. **Customer Success and Support (P9), and the Academy.** Not recorded. CSM
   coverage and phone/email/chat support are "included in the cost of a
   subscription for our Hubs" — an entitlement rather than a separate offering.
   "our academy of educational content" (P6, P9) is described but never given a
   proper product name, so recording "HubSpot Academy" would require outside
   knowledge (Rule 3). Both are live candidates for the adjudicator.

7. **T14 (self-service answers).** The document says only "knowledge base" and
   "conversational bots". The *deflection* intent — customers answering their own
   questions — is my inference, not stated. Recorded at `low`; folding C43 into
   T13 is defensible.

8. **T22 (programmable automation).** "automate business processes" and
   "programmable automation" are stated, but no deliverable is described, and
   automation is already embedded in T4, T10, T13 and T16. Recorded at `low` as a
   possible over-split.

9. **T6 (video and podcast hosting).** One bare noun promoted to its own task
   because the deliverable (hosted media) differs from published web pages.
   Folding it into T1 is defensible.

10. **App marketplace / ecosystem as a product.** P6 describes "a connected
    ecosystem supporting the customer platform with a marketplace of integrations,
    templates, expert partners, a community network, and an academy of educational
    content" — one of the three named platform layers — but gives it no product
    name. Recorded only as capabilities C2–C4 of PR1, not as a product.

11. **`broadly_deployed_or_default` vs `general_availability` for Smart CRM.**
    See PR2's ambiguity cell. Kept the weaker status.

12. **Free tier as a product.** P16 — "Our freemium model attracts customers who
    begin using our customer platform through our free products". "Our free
    products" is packaging of PR6–PR11, not a distinct offering. Not recorded.

---

## Ontolojinin cevaplamadığı sorular

**Q1 — Nested families.** The hierarchy is `Company → Product family → Product`,
one family level. HubSpot presents two nested groupings: the customer platform
(P6: "three layers") and, inside it, the engagement Hubs. I recorded both as
families, which the hierarchy does not permit. The ontology needs either a rule
that the *narrowest* grouping is the family, or an explicit sub-family level.

**Q2 — A suite that is also a product.** PR1 and F1 carry the same name. The
ontology says a family "may correspond to a segment, cloud, suite, or solution
family, but it is not automatically a product", and separately admits bundles
that "create a distinct cross-product workflow" as products. It does not say what
to do when both apply to the same named thing, nor whether the family and product
records may share a name.

**Q3 — Where do platform-level capabilities attach?** Open APIs, the integration
marketplace and the unified profile belong to the platform, not to any Hub.
Admitting PR1 as a product solved this, but only because the bundle exception
happened to apply. If a firm's cross-product capabilities sit under a grouping
that is *not* admissible as a product, the ontology leaves those capabilities
with no valid parent.

**Q4 — Are services products?** "An identifiable customer offering that can be
purchased, subscribed to, licensed, deployed, or used" admits professional
services, training, and consulting. The exclusion list does not exclude them. If
services should be out of scope for a product–capability–task dataset about
software capability, the ontology must say so; if they are in scope, the
capability and task definitions ("a concrete function the product provides")
need wording that fits human-delivered work.

**Q5 — `ai_action_observed` is undefined.** The field is in the required output
format but appears nowhere in the ontology. Unresolved boundaries: does
"AI-powered configure-price-quote" count (a product adjective, not a stated
action)? Does C12 count, where AI provides context that *powers* something a
human then does? Does C80 count, where the subject is a human consultant helping
a customer "adopt HubSpot AI"? I answered yes / yes / no, but the field needs a
written rule or it will not survive inter-annotator agreement.

**Q6 — Is a bare feature-list noun a capability?** See Kararsız item 4. The
ontology's capability examples are all verb-object ("generate images from text").
It says capabilities must be "specific enough to distinguish different functions"
but never says whether a noun that names a function qualifies. For a
feature-list-style document this single rule swings the capability count by
roughly 2×, which will dominate any E3 recall measurement.

**Q7 — Task role when a task spans products.** SPEC-011 classifies "task
importance to the product", but T12 spans Sales Hub, Commerce Hub and Payments;
it is core to Commerce Hub and peripheral to Sales Hub. The ontology gives one
role per task. I labelled by the product where the task is most central and
recorded `medium`.

**Q8 — Duplicate capabilities across products.** C15 (Breeze) and C17 (Breeze
Agents) are the same function attributed to two products, as are C28/C38
(live chat in Sales Hub and Service Hub) and C7/C36 (reporting). The source
genuinely ships them in both places. E3's "duplicate" and E2's "duplicate product
rate" metrics need a rule for whether same-function-different-product counts as a
duplicate.

**Q9 — No rule for statements of investment or intent.** P16 says "We are also
investing in powerful AI capabilities and agents across all our engagement hubs
and the Smart CRM". This is neither a roadmap item with a date nor a deployed
capability. The availability taxonomy has no value for "under active development,
no stated availability". I excluded it; `announced` would overstate it.

---

## Bu belgenin taşımadığı bilgi

1. **No dates for any product.** Nothing in Item 1 says when Breeze, Breeze
   Agents, Content Hub, Commerce Hub or Payments first became available. This
   snapshot cannot establish a first-seen date for anything, and it cannot
   distinguish a capability that shipped in 2025 from one that shipped in 2019.

2. **No availability qualifiers.** No beta, limited-release, preview, deprecated
   or discontinued language anywhere. Every `availability_status` in this file is
   either supported by the single free/paid-tier sentence for the Hubs or is an
   inference from present-tense description. `private_beta`, `public_beta`,
   `announced`, `deprecated` and `discontinued` are unobservable in this source
   type.

3. **Breeze Assistant has no described function.** "a go-to-market assistant to
   boost productivity and make work easier" states a benefit, not an action. Under
   Rule 2 this yields zero capabilities. This is the clearest Rule-2 test case in
   the document, and a model that emits capabilities for PR4 is inferring from the
   word "assistant".

4. **No AI supplier or model disclosure.** The document never says which models
   power Breeze, whether they are built in-house or licensed, or what the
   dependency is. Item 1 carries no frontier-model dependency evidence at all.

5. **Which Hub owns which AI agent is never stated.** P8's four agent actions
   (research accounts, enrich data, answer support questions, qualify leads) map
   naturally onto Sales, Operations, Service and Sales respectively, but the
   document does not make that assignment.

6. **No per-product revenue, adoption or customer counts.** P7 — "We operate as
   one operating segment." All scale metrics (288,706 Customers, $3.1 billion) are
   firm-level. Nothing supports weighting one product over another by economic
   size, which limits what any measurement layer can do with `task_role`.

7. **Traps a naive extractor will fall into.** Recorded here because they are the
   most likely source of false positives:
   - **P5 (Competition)** lists "AI agents and automation capabilities that handle
     end-to-end workflows", "unified data platform with AI-powered data quality
     and enrichment" and "AEO and AI-native marketing capabilities" as
     *competitive factors in the market*, and lists "AI agent and providers" and
     "AI-native CRM and workflow automation startups" as *competitors*. The
     ontology is explicit: "Product existence cannot be inferred solely from a
     competitor list or risk factor." None of P5 was extracted.
   - **P10 (Marketing and Sales)** describes HubSpot's *own* go-to-market
     operation — "Loop Marketing", "AI-driven lead scoring and prioritization",
     "AI-enhanced engagement tools", "intelligent recommendation systems". These
     are HubSpot's internal use of AI on itself, not customer-facing capabilities.
     SPEC-010's internal-work exclusion applies. None of P10 was extracted, and
     "Loop Marketing" is a marketing playbook, not a product.
   - **P9** — "We also leverage AI to further boost this efficiency" and "We
     leverage AI as a core part of our support offerings" describe HubSpot's own
     support operation, not something a customer operates. Not extracted.
   - **P11 (Our Technology)** is entirely infrastructure — HBase, Kafka, Vitess,
     Elasticsearch, microservices, redundancy, DDoS protection. These are internal
     technologies not exposed to customers. Only one sentence in the whole
     passage, about delivery through "APIs, web browsers or mobile applications",
     touches the customer, and that is a delivery channel, not a task.
   - **P13 (Our Growth Strategy)** is forward-looking intent — "We will continue
     to selectively pursue acquisitions", "there is a need to move quickly on data
     enrichment". No capability was taken from it.

8. **Snapshot data-quality observation.** P1 ends mid-attribute with an unclosed
   HTML fragment: `<p style="text-indent:-9.971%;padding-left:9.067%;font-size:10pt;margin-top:10pt;font-family:Times New Roman;margin-bottom:0;text-align:left;"`.
   Raw markup is leaking through the normalizer into passage text. P1 carries no
   extractable content so it does not affect this annotation, but it will affect
   evidence-quote validation on any passage where markup lands mid-sentence, and
   it inflates character offsets. Recorded as an observation about the snapshot,
   not a change request.

9. **P4 is a heading stub.** `> ITEM 1. BUSINESS`, 18 characters, carrying a
   leading `>`. One of 16 passages — 6% of this firm's packet — is furniture.
