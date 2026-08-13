# HubSpot FY2024 — draft reading (Opus)

**Not a gold record.** See `README.md` in this directory: this is a
model-authored reading awaiting human adjudication, and the two readings
held here are not independent of each other.

## Archival header

| field | value |
|---|---|
| firm | HubSpot, Inc. |
| ticker | HUBS |
| source snapshot directory | `data/runs/srcsnap-hubspot-20241231-sec-v4` |
| passage count | 16 |
| `source_id` | `CIK0001404655/sec_10k/2025-02-12/36257e638feb2059` |
| `company_id` | `CIK0001404655` |
| `source_type` | `sec_10k` |
| document publication date | 2025-02-12 |
| source-admission cutoff (`observation_cutoff_date`) | 2025-02-12 (filing date, per `docs/TEMPORAL_POLICY.md`) |
| analytical period assignment | FY2024 (fiscal year ended 2024-12-31) |
| content hash of source document | `36257e638feb2059e3bbc58461938d6ffc11dd280e12d7af0f06c5394bf40b12` |
| reader | Opus, via Claude Code CLI |
| model label | `claude-opus-5[1m]` (Opus 5, 1M context) |
| annotation date | 2026-08-13 |
| instruction (full text) | `evals/gold/draft/_annotation_A2_instruction.md` |
| instruction SHA-256 | `2d72c6eccde50449b3d93a679a32d9a4b0524e69238faef6360a0302855479fb` |
| `guideline_version` (SHA-256 of `docs/methodology/PRODUCT_CAPABILITY_TASK_ONTOLOGY.md`) | `8d134ad00f92a92972dee37dbf0f284fbef846657d4bc2f9ad3fdf4bed6b716f` |
| passage ordering key | `(source_id, passage_id)` |
| sources consulted for the records below | this snapshot's `source_passages.jsonl` only |

Snapshot-version note: three earlier ingestion versions of this same filing exist
on disk (`srcsnap-hubspot-fy2024-sec-v1`, `-v2`, `-v3`, plus a
`-v1-finegrained-clean` variant). The `-sec-v4` snapshot was used, matching the
version family named in the annotation instruction and the version used for the
FY2025 reading, so the two periods are comparable.

## Annotator exposure disclosure — order effect

**This reading is not fully blind.** The same annotator (A2) read the HubSpot
FY2025 10-K (`srcsnap-hubspot-20251231-sec-v4`, filed 2026-02-11) earlier in the
same session, before this FY2024 reading. Two consequences, both recorded rather
than concealed:

1. **Anchoring risk.** The layer structure, product boundaries and task
   consolidation used here were first developed against FY2025. Where the two
   documents share wording the resulting records will agree more closely than two
   genuinely independent readings would. Any inter-annotator or inter-period
   agreement statistic computed from this file must carry this caveat.
2. **Temporal integrity (`CLAUDE.md` rule 3).** The FY2025 filing is dated
   2026-02-11, after this observation's admission cutoff of 2025-02-12, so it is
   inadmissible evidence here. Every record below is supported only by a passage
   from this snapshot, and every evidence quote was machine-verified against this
   snapshot's passage text. Several entities present in FY2025 are **deliberately
   absent** here because FY2024 does not support them; they are listed under
   **Bu belgenin taşımadığı bilgi**, item 1, as absences, not as carried-over
   records.

No cross-period comparison is included in this file. Period-to-period deltas
belong to the longitudinal layer, not to a single-period gold record.

## Passage index

| P-ref | `passage_id` | opening / section |
|---|---|---|
| P1 | `0ce766a4ef7385978e3040e5bfa09577` | Competition |
| P2 | `126ca534ca184555062ce399d9dbb986` | `> ITEM I. BUSINESS` (heading stub, 18 chars) |
| P3 | `2287b213e5f63d84298980f0ac64f392` | Our Customers |
| P4 | `2823d06348bcc2c0a08e3118c66cdb7d` | Overview |
| P5 | `3f6315107e7fc165f71123d3a957dc6d` | Governmental Regulations |
| P6 | `4452e1e78984b3b75f646c5c60e3b273` | Available Information |
| P7 | `5184e69b31f599982b58840a051a2650` | Our Customer Platform |
| P8 | `5e38c38641125aa56499b6378db9dd0c` | Intellectual Property |
| P9 | `795e993df7cc82cf503576544ba2502b` | Our Technology |
| P10 | `b9d5db03900f6e5264f4bb218fa02b9d` | Human Capital Management |
| P11 | `bf209d672d7ec6bf957a92eb05cda124` | The HubSpot Approach |
| P12 | `bf97c986f6feebdf3a187f7a0775a0a5` | Financial Information About Segments |
| P13 | `c2af90d4c3d7fc882cde25cd1001051e` | Marketing and Sales |
| P14 | `c73fe44cb66fe75ca86b2bd479c91db2` | Our Competitive Strengths |
| P15 | `dc46eb5c2fb8dcbf7b6837ea0ad3a241` | Our Growth Strategy |
| P16 | `e1170117112b3c265d86fe34be071662` | Our Services |

Only four passages carry extractable entity evidence: **P4, P7, P11, P16**. All
sixteen were read in full. P1, P9, P13 and P15 were read and deliberately not
extracted from — see **Bu belgenin taşımadığı bilgi**, item 6.

---

## Product family

| # | name | evidence [P-ref] | quote | confidence |
|---|---|---|---|---|
| F1 | HubSpot customer platform | P4 | We provide a customer platform that helps businesses connect and grow better. | high |
| F2 | Engagement Hubs | P7 | Our customer platform, with engagement Hubs, our Smart CRM, and connected ecosystems enable companies to have a unified customer profile and connect with their customers at every part of their customer relationship lifecycle. | medium |

F2 nests inside F1 — see question Q1.

---

## Product

| # | name | family | evidence [P-ref] | quote | availability_status | confidence | ambiguity |
|---|---|---|---|---|---|---|---|
| PR1 | HubSpot customer platform | F1 | P4 | We primarily sell our customer platform on a subscription basis. | general_availability | high | Product and family share a name. Admitted as a product under the ontology's bundle exception: P11 — "Our customer platform has one login, one user interface and one unified customer view." |
| PR2 | Smart CRM | F1 | P4 | a Smart customer relationship management product (“CRM”) | general_availability | high | Could be `broadly_deployed_or_default` — P4 calls it "the foundational layer" — but no passage states it is on by default, so the weaker status was kept (Rule 7). |
| PR3 | Breeze | F1 | P7 | Breeze is our AI that powers the customer platform, including our Smart CRM, engagement Hubs, and the connected ecosystem. | general_availability | medium | Zero capabilities. Reads as an umbrella over PR4–PR6 and could be modelled as a product family instead of a product. No tier, price, GA date or beta qualifier anywhere in Item 1. |
| PR4 | Breeze Copilot | F1 | P7 | Breeze includes Breeze Copilot, an AI-powered companion to boost productivity and make work easier | general_availability | low | Zero capabilities. Availability inferred only from the present-tense "includes". Product existence independently corroborated by P14. |
| PR5 | Breeze Agents | F1 | P7 | Breeze Agents to help teams automate work, end-to-end, from strategy to execution | general_availability | low | Zero capabilities. Product existence independently corroborated by P14. |
| PR6 | Breeze Intelligence | F1 | P7 | Breeze Intelligence, a data enrichment solution to provide a complete and unified view of the customer | general_availability | medium | The only Breeze component whose function is stated. Not named in P14's list of AI investments, unlike PR4 and PR5. |
| PR7 | Marketing Hub | F2 | P7 | Marketing Hub is an all-in-one toolset for marketers to attract, engage, and nurture new leads towards sales readiness over the entire customer lifecycle. | general_availability | high | — |
| PR8 | Sales Hub | F2 | P7 | Sales Hub is designed to enhance the productivity and effectiveness of sales teams. | general_availability | high | — |
| PR9 | Service Hub | F2 | P7 | Service Hub is our customer service software designed to help businesses manage, respond and connect with customers. | general_availability | high | — |
| PR10 | Content Hub | F2 | P7 | Our Content Hub combines the power of customer relationship management and a content management system into one integrated platform. | general_availability | high | — |
| PR11 | Operations Hub | F2 | P7 | Operations Hub is designed to help businesses combine, clean, and activate customer data in a connected platform, automate business processes, eliminate time-consuming data cleanup, and query and transform data to enable customer insights and connections. | general_availability | high | — |
| PR12 | Commerce Hub | F2 | P7 | Commerce Hub is a B2B commerce suite that helps streamline the opportunity-to-cash process for businesses to get paid faster, increase revenue and save time. | general_availability | high | Called a "suite" but listed as a peer of the other Hubs; treated as a product, not a family. |
| PR13 | Payments | F2 | P7 | It includes an end-to-end payment solution, Payments, which enables customers to accept electronic funds transfers (e.g. credit card payments) from their customers in less time and with fewer tools. | general_availability | medium | Named and described, but presented as included in PR12 rather than separately purchasable. May be a capability of Commerce Hub instead of a product. |
| PR14 | Professional services | unknown | P16 | Our professional services are also available to customers who need additional assistance on a one-time or ongoing basis for an additional fee. | general_availability | low | Purchasable, so it passes the ontology's product test, but it is human consulting, not software (question Q4). Family membership is not stated. |

Availability for PR7–PR12 is additionally supported by P7 — "Our Hubs are
available in both free and paid tiers with gradually increasing levels of
functionality that support the needs of our customers as their businesses grow."

**Products with zero capabilities: PR3 (Breeze), PR4 (Breeze Copilot),
PR5 (Breeze Agents).** Three of the four Breeze-family products. See
**Bu belgenin taşımadığı bilgi**, item 2.

---

## Capability

`ai_action_observed = yes` is recorded only where the passage states that AI, or
a component the passage identifies as AI, performs the action. The ontology does
not define this field (question Q5).

| # | text | product | evidence [P-ref] | quote | ai_action_observed | confidence |
|---|---|---|---|---|---|---|
| C1 | Provide a unified customer profile across the connected platform | PR1 | P7 | enable companies to have a unified customer profile and connect with their customers at every part of their customer relationship lifecycle | no | high |
| C2 | Find and install third-party integrations and applications | PR1 | P7 | Over 1,700 integrations and applications are available for our users | no | high |
| C3 | Build custom applications and integrations on top of the platform | PR1 | P7 | Customers can build custom applications and integrations on top of our customer platform themselves, or through third party developers in our ecosystem. | no | high |
| C4 | Integrate the platform with other applications through open APIs | PR1 | P11 | features a variety of open application programming interfaces (“APIs”) that allows easy integration of our platform with other applications | no | high |
| C5 | Track interactions with contacts and customers | PR2 | P7 | allows businesses to track their interactions with contacts and customers | no | high |
| C6 | Manage customer activities | PR2 | P7 | manage their customer activities | no | high |
| C7 | Report on pipeline and sales | PR2 | P7 | report on their pipeline and sales | no | high |
| C8 | Manage and govern team and business processes | PR2 | P7 | manage and govern their team and business processes | no | high |
| C9 | Personalize the customer interaction across web content, social media and email | PR2 | P7 | personalize every aspect of the customer interaction across web content, social media engagement, and email messages across devices, including mobile | no | high |
| C10 | Create a unified timeline of all interactions with a customer | PR2 | P11 | creates a unified timeline incorporating all the interactions across the business with a particular customer | no | high |
| C11 | Enrich customer data | PR6 | P7 | a data enrichment solution | yes | medium |
| C12 | Provide a complete and unified view of the customer | PR6 | P7 | to provide a complete and unified view of the customer | yes | medium |
| C13 | Attract, engage and nurture new leads towards sales readiness over the customer lifecycle | PR7 | P7 | attract, engage, and nurture new leads towards sales readiness over the entire customer lifecycle | no | high |
| C14 | Marketing automation and email | PR7 | P7 | marketing automation and email | no | medium |
| C15 | Social media | PR7 | P7 | marketing automation and email, social media | no | low |
| C16 | Search engine optimization (SEO) | PR7 | P7 | social media, SEO, and reporting and analytics | no | medium |
| C17 | Reporting and analytics | PR7 | P7 | SEO, and reporting and analytics | no | medium |
| C18 | Deliver a personalized experience for prospects with less work for sales representatives | PR8 | P7 | deliver a personalized experience for prospects with less work for sales representatives | no | medium |
| C19 | Email templates and tracking | PR8 | P7 | email templates and tracking | no | medium |
| C20 | Conversations and live chat | PR8 | P7 | conversations and live chat, meeting and call scheduling | no | medium |
| C21 | Meeting and call scheduling | PR8 | P7 | meeting and call scheduling | no | medium |
| C22 | Lead and website visit alerts | PR8 | P7 | lead and website visit alerts | no | medium |
| C23 | Lead scoring | PR8 | P7 | lead scoring | no | medium |
| C24 | Sales automation | PR8 | P7 | sales automation | no | medium |
| C25 | Pipeline management | PR8 | P7 | pipeline management | no | medium |
| C26 | Quoting | PR8 | P7 | pipeline management, quoting, forecasting | no | medium |
| C27 | Forecasting | PR8 | P7 | quoting, forecasting, and reporting | no | medium |
| C28 | Reporting | PR8 | P7 | forecasting, and reporting | no | medium |
| C29 | Manage, respond and connect with customers | PR9 | P7 | designed to help businesses manage, respond and connect with customers | no | high |
| C30 | Conversations and live chat functionality | PR9 | P7 | conversations and live chat functionality | no | medium |
| C31 | Conversational bots | PR9 | P7 | conversational bots | no | medium |
| C32 | Call tracking | PR9 | P7 | call tracking | no | medium |
| C33 | Tickets and help desk | PR9 | P7 | tickets and help desk | no | medium |
| C34 | Automation and routing | PR9 | P7 | automation and routing | no | medium |
| C35 | Knowledge base | PR9 | P7 | knowledge base | no | medium |
| C36 | Team emails | PR9 | P7 | team emails | no | medium |
| C37 | Feedback and reporting tools | PR9 | P7 | feedback and reporting tools | no | medium |
| C38 | Customer goals | PR9 | P7 | and customer goals | no | low |
| C39 | Create new and edit existing web content | PR10 | P7 | enable businesses to create new and edit existing web content | no | high |
| C40 | Personalize websites for different visitors | PR10 | P7 | personalizing their websites for different visitors | no | high |
| C41 | Optimize websites to convert more visitors into leads and customers | PR10 | P7 | optimizing their websites to convert more visitors into leads and customers | no | high |
| C42 | Website pages | PR10 | P7 | Features include: website pages, business blogging | no | medium |
| C43 | Business blogging | PR10 | P7 | business blogging | no | medium |
| C44 | Video and podcast hosting | PR10 | P7 | video and podcast hosting | no | medium |
| C45 | Smart content | PR10 | P7 | smart content | no | low |
| C46 | Landing pages and forms | PR10 | P7 | landing pages and forms | no | medium |
| C47 | SEO recommendations | PR10 | P7 | SEO recommendations | no | medium |
| C48 | Forms and lead flow | PR10 | P7 | forms and lead flow | no | medium |
| C49 | Web analytics reporting | PR10 | P7 | web analytics reporting | no | medium |
| C50 | Calls-to-action | PR10 | P7 | calls-to-action | no | medium |
| C51 | File manager | PR10 | P7 | and file manager | no | medium |
| C52 | Combine, clean, and activate customer data | PR11 | P7 | combine, clean, and activate customer data in a connected platform | no | high |
| C53 | Automate business processes | PR11 | P7 | automate business processes, eliminate time-consuming data cleanup | no | high |
| C54 | Query and transform data to enable customer insights | PR11 | P7 | query and transform data to enable customer insights and connections | no | high |
| C55 | Programmable automation | PR11 | P7 | programmable automation | no | medium |
| C56 | Data sync | PR11 | P7 | data sync | no | medium |
| C57 | Data curation | PR11 | P7 | data curation | no | medium |
| C58 | Data quality tools | PR11 | P7 | and data quality tools | no | medium |
| C59 | Streamline the opportunity-to-cash process | PR12 | P7 | helps streamline the opportunity-to-cash process for businesses to get paid faster | no | high |
| C60 | Payment links | PR12 | P7 | Features include: payment links, invoices | no | medium |
| C61 | Invoices | PR12 | P7 | payment links, invoices, quotes | no | medium |
| C62 | Quotes | PR12 | P7 | invoices, quotes, subscription management | no | medium |
| C63 | Subscription management | PR12 | P7 | subscription management | no | medium |
| C64 | Automation and revenue reporting | PR12 | P7 | automation and revenue reporting | no | medium |
| C65 | Accept electronic funds transfers from end customers | PR13 | P7 | enables customers to accept electronic funds transfers (e.g. credit card payments) from their customers in less time and with fewer tools | no | high |
| C66 | Let the end customer buy and pay directly on a website, email or chat | PR13 | P7 | our customer's customer can buy and pay directly on a website, an email, or chat | no | high |
| C67 | Streamline the billing and payment process | PR13 | P11 | an end-to-end payment solution which enables customers to streamline their billing and payment process with fewer tools | no | high |
| C68 | Educate and train customers on using the platform | PR14 | P16 | We offer professional services to educate and train customers on how to leverage our customer platform | no | medium |
| C69 | Deliver onboarding guidance and one-on-one training | PR14 | P16 | they receive onboarding guidance in the product and in some cases receive one-on-one training from one of our on-boarding, inbound consultants, or technical consultants by web meetings | no | medium |

C11 and C12 are marked `ai_action_observed = yes` on an in-document chain: P7
says "Breeze is our AI" and then places Breeze Intelligence inside Breeze. The
passage never states that AI performs the enrichment. Recorded at `medium`; a
stricter reading would set `no`. **These are the only two `yes` values in the
entire FY2024 packet.**

---

## Customer-facing task

| # | text | customer_need | capability_refs | evidence [P-ref] | quote | task_role | confidence |
|---|---|---|---|---|---|---|---|
| T1 | Create and publish web pages and blog posts to establish an online presence | Publish and maintain an organization's own online content | C39, C42, C43, C46, C51 | P7 | Our content tools enable businesses to create new and edit existing web content | core | high |
| T2 | Optimize published content so buyers find it through search engines | Be discoverable by people searching for a solution | C16, C47 | P11 | a system of engagement for efficiently engaging customers through search engine optimization (“SEO”) | core | high |
| T3 | Convert anonymous website visitors into identified leads | Turn untracked interest into contactable prospects | C41, C45, C46, C48, C50 | P7 | optimizing their websites to convert more visitors into leads and customers | core | high |
| T4 | Attract and nurture new leads across email and social channels over the customer lifecycle | Move prospective buyers toward a purchase decision | C13, C14, C15 | P7 | attract, engage, and nurture new leads towards sales readiness over the entire customer lifecycle | core | high |
| T5 | Personalize content and messages to each individual customer | Make outbound communication relevant to the person receiving it | C9, C40, C45 | P7 | personalize every aspect of the customer interaction across web content, social media engagement, and email messages across devices, including mobile | major_supporting | high |
| T6 | Host and serve video and podcast media to an audience | Distribute recorded media without operating hosting infrastructure | C44 | P7 | video and podcast hosting | peripheral | medium |
| T7 | Measure marketing and website performance | Know which marketing activity actually produces results | C17, C49 | P7 | web analytics reporting | major_supporting | medium |
| T8 | Score and prioritize leads so sellers work the best opportunities first | Focus limited selling time on the likeliest buyers | C22, C23 | P7 | lead scoring | core | high |
| T9 | Engage prospects through tracked email, chat and scheduled meetings to advance a deal | Hold and keep track of sales conversations with buyers | C18, C19, C20, C21, C24 | P7 | email templates and tracking, conversations and live chat, meeting and call scheduling | core | high |
| T10 | Manage the sales pipeline and forecast expected revenue | Know what revenue is likely to close and when | C7, C25, C27, C28 | P7 | pipeline management, quoting, forecasting, and reporting | core | high |
| T11 | Quote, invoice and collect payment to complete the opportunity-to-cash process | Get paid for what has been sold | C26, C59, C60, C61, C62, C63, C64, C65, C66, C67 | P7 | helps streamline the opportunity-to-cash process for businesses to get paid faster | core | high |
| T12 | Resolve inbound customer support requests | Get help when something is wrong after a purchase | C29, C30, C31, C32, C33, C34, C36 | P7 | Service Hub is our customer service software designed to help businesses manage, respond and connect with customers. | core | high |
| T13 | Let customers find answers themselves without contacting an agent | Get an answer immediately rather than waiting for a person | C31, C35 | P7 | knowledge base | major_supporting | low |
| T14 | Collect customer feedback and track service goals | Know whether customers are satisfied | C37, C38 | P7 | feedback and reporting tools, and customer goals | peripheral | medium |
| T15 | Consolidate and clean customer data so teams work from accurate records | Maintain one trustworthy record of each customer | C52, C56, C57, C58 | P7 | combine, clean, and activate customer data in a connected platform | core | high |
| T16 | Enrich customer records with data the customer did not supply | Know more about a customer than they have volunteered | C11, C12 | P7 | a data enrichment solution | major_supporting | medium |
| T17 | Query and transform customer data to answer business questions | Get answers out of accumulated customer data | C54 | P7 | query and transform data to enable customer insights and connections | major_supporting | medium |
| T18 | Maintain one unified view of each customer across every interaction | See everything known about a customer in one place | C1, C5, C6, C10 | P11 | creates a unified timeline incorporating all the interactions across the business with a particular customer | core | high |
| T19 | Connect the platform to other business applications and extend it with custom applications | Make purchased software work with the rest of a company's tools | C2, C3, C4 | P7 | Customers can build custom applications and integrations on top of our customer platform themselves, or through third party developers in our ecosystem. | major_supporting | high |
| T20 | Administer team membership, permissions and business processes | Control who inside the organization can do what | C8 | P7 | manage and govern their team and business processes | peripheral | medium |
| T21 | Automate a repeatable business process with custom logic | Remove manual steps from a recurring internal process | C53, C55 | P7 | programmable automation | major_supporting | low |
| T22 | Train staff to operate newly purchased software | Build in-house skill to run a system the organization just bought | C68, C69 | P16 | We offer professional services to educate and train customers on how to leverage our customer platform | major_supporting | medium |

Channel splitting was deliberately avoided: T5 treats web, social and email as one
task, and T11 treats "a website, an email, or chat" as one task, because the
economic job does not differ by channel.

---

## Kararsız kaldıklarım

1. **Breeze: product, family, or internal layer?** P7 says "Breeze is our AI that
   powers the customer platform" and then lists three named things inside it.
   That structure reads more like a family than a product, but the ontology's
   family definition ("a stable commercial grouping used to organize related
   products") and its exclusion of "'AI' or 'platform' without an offering" pull
   in opposite directions. Recorded as a product at `medium` with three named
   products beneath it. Largest disagreement risk in this firm-period.

2. **Breeze Intelligence's `ai_action_observed`.** The only route to `yes` is the
   chain "Breeze is our AI" → "Breeze includes … Breeze Intelligence". The
   enrichment sentence itself contains no AI verb. Recorded `yes` at `medium`; a
   strict Rule 2 / Rule 7 reading gives `no`, and then the FY2024 packet contains
   **zero** observed AI actions.

3. **`combines customer data with AI` (P4).** "The Smart CRM is the foundational
   layer that combines customer data with AI to power the entire customer
   platform". This is the only other AI-verb sentence in the packet. I did not
   record it as a capability: "power the entire customer platform" is not a
   customer-facing action (Rule 2). An annotator who accepted it would add one
   Smart CRM capability with `ai_action_observed = yes`.

4. **Payments: product or capability of Commerce Hub?** Named and described but
   presented as included in Commerce Hub. Recorded as a product at `medium`.
   Note the FY2024 text writes it as `an end-to-end payment solution, Payments,`
   — a plain appositive, not a formally quoted defined term.

5. **Bare feature-list nouns.** Roughly half the capability rows (C14–C28,
   C30–C38, C42–C51, C55–C64) are nouns from "Features include:" lists with no
   verb. They are concrete functions, not marketing abstractions, so Rule 2 does
   not exclude them, but they cannot be written as verb-object-outcome without
   inventing the verb. Recorded verbatim at `medium`, or `low` where even the
   function is unclear (C15, C38, C45). Requiring a verb would roughly halve the
   capability count. See Q6.

6. **Clearbit and Cacheflow (P15).** Two acquisitions with named, described
   capability content: Clearbit is "a top B2B data provider" acquired "to bring
   rich third-party company data into our system of record", Cacheflow is "a
   leading B2B subscription billing management and CPQ solution" acquired "to
   build these features directly into Commerce Hub". Neither was recorded as a
   product or a capability. `docs/TEMPORAL_POLICY.md` is explicit — "An acquired
   product is not treated as integrated merely because the acquisition closed" —
   and "to build these features directly into Commerce Hub" states intent, not a
   shipped capability. Recording CPQ under Commerce Hub for FY2024 would be a
   roadmap-as-GA error. This is the sharpest temporal-discipline test in the
   packet and I expect models to fail it.

7. **Professional services (PR14).** Purchasable and named, so it passes the
   ontology's product test, but it is human consulting. Recorded at `low`. See Q4.

8. **Customer Success / Support / the Academy.** Not recorded. CSM, CST and PDM
   coverage and phone/email/chat support are "included in the cost of a
   subscription for our Hubs" — an entitlement, not a separate offering. "an
   academy of educational content" (P4) is described but never given a product
   name, so naming it would require outside knowledge (Rule 3).

9. **`AI assistance and automation` as a cross-Hub functionality (P11).** "we
   have crafted a set of core functionalities, including reporting, content,
   messaging, data, AI assistance and automation, which run across our engagement
   Hubs." A cross-product capability layer with no product owner and no concrete
   action. Not recorded (Rule 2). It is, however, the only statement in the packet
   that AI assistance runs across all Hubs.

10. **T13 (self-service answers).** The document gives only "knowledge base" and
    "conversational bots". The deflection intent is my inference. Recorded at
    `low`; folding C35 into T12 is defensible.

11. **T21 (programmable automation).** Stated, but no deliverable described, and
    automation is already embedded in T4, T9, T12 and T15. Recorded at `low` as a
    possible over-split.

12. **T6 (video and podcast hosting).** One bare noun promoted to a task because
    the deliverable differs from published web pages. Folding into T1 is
    defensible.

13. **`broadly_deployed_or_default` vs `general_availability` for Smart CRM.**
    Kept the weaker status. See PR2's ambiguity cell.

---

## Ontolojinin cevaplamadığı sorular

**Q1 — Nested families.** The hierarchy allows one family level, but this
document presents two nested groupings: the customer platform ("three layers",
P4) and, inside it, the engagement Hubs. Both are recorded as families, which the
hierarchy does not permit. The ontology needs a rule that the narrowest grouping
wins, or an explicit sub-family level.

**Q2 — A suite that is also a product.** PR1 and F1 share a name. The ontology
says a family "is not automatically a product" and separately admits bundles that
create a distinct cross-product workflow as products. It does not say what to do
when both apply to the same named thing.

**Q3 — Where do platform-level capabilities attach?** Open APIs, the integration
marketplace and the unified profile belong to the platform, not to any Hub.
Admitting PR1 as a product solved this only because the bundle exception happened
to apply.

**Q4 — Are services products?** The product test ("an identifiable customer
offering that can be purchased, subscribed to, licensed, deployed, or used")
admits professional services and training, and the exclusion list does not
exclude them. If services are out of scope, the ontology must say so; if they are
in scope, "a concrete function the product provides" needs wording that fits
human-delivered work.

**Q5 — `ai_action_observed` is undefined.** The field is required by the output
format but appears nowhere in the ontology. This period makes the gap acute: the
whole packet turns on whether an AI verb can be inherited down a containment
chain ("Breeze is our AI" → "Breeze includes Breeze Intelligence"). Under one
reading the FY2024 packet has 2 AI actions; under the other it has 0. No written
rule decides between them.

**Q6 — Is a bare feature-list noun a capability?** See Kararsız item 5. The
ontology's capability examples are all verb-object. For a feature-list-style
document this single unwritten rule swings the capability count by roughly 2×,
which will dominate any E3 recall measurement.

**Q7 — Task role when a task spans products.** T11 spans Sales Hub, Commerce Hub
and Payments; it is core to Commerce Hub and peripheral to Sales Hub. SPEC-011
classifies "task importance to the product" and allows one role per task.

**Q8 — Duplicate capabilities across products.** C20/C30 (live chat in Sales Hub
and Service Hub) and C7/C28 (reporting) are the same function attributed to two
products, as the source genuinely ships them in both. E2's duplicate-product rate
and E3's duplicate metrics need a rule for same-function-different-product.

**Q9 — No availability value for "acquired, integration in progress".** Cacheflow
was acquired "to build these features directly into Commerce Hub". The
availability taxonomy has no value between `announced` and
`general_availability` for a capability that is bought but not yet shipped.
`announced` overstates it — nothing was announced to customers as available.
`docs/TEMPORAL_POLICY.md` requires storing "integration evidence" and "first
appearance in product packaging or workflows", but no schema field in this
annotation format carries them.

**Q10 — A product whose function is described only inside its parent's
sentence.** Breeze Copilot and Breeze Agents exist only as clauses in the Breeze
sentence. The ontology's evidence rule says "Each entity must include direct
passages", which is satisfied, but says nothing about whether a product with a
named existence and no stated function should be emitted at all or suppressed.
I emitted them with zero capabilities, treating the emptiness as the finding.

---

## Bu belgenin taşımadığı bilgi

1. **No dates for any product.** Nothing in Item 1 says when Breeze, Breeze
   Copilot, Breeze Agents, Breeze Intelligence, Content Hub, Commerce Hub or
   Payments became available. This snapshot cannot establish a first-seen date for
   anything and cannot distinguish a capability that shipped this year from one
   that shipped five years ago. The only dated events in the whole packet are the
   two acquisitions in P15, and even those carry no announcement or close date.

2. **Three of four Breeze products have no described function.** This is the
   dominant finding of the packet:
   - **Breeze** — "our AI that powers the customer platform". Powering a platform
     is not a customer-facing action.
   - **Breeze Copilot** — "an AI-powered companion to boost productivity and make
     work easier". A benefit claim with no action; the clearest Rule 2 test case
     here. A model that emits capabilities for it is inferring from the words
     "AI-powered companion".
   - **Breeze Agents** — "to help teams automate work, end-to-end, from strategy
     to execution". Names no work, no object, no deliverable. Nothing anywhere
     else in the packet describes what an agent does.

   Only **Breeze Intelligence** states a function, and only in six words.
   P14 confirms the products exist — "investing in powerful AI capabilities
   through Breeze Copilot, Breeze Agents, and features across all our engagement
   hubs and the Smart CRM" — but that is a statement of investment, not of
   deployed function, and the ontology has no availability value for it.

3. **No AI action is attributed to the Smart CRM.** P4's "combines customer data
   with AI to power the entire customer platform" is the only AI verb touching
   the Smart CRM, and it describes construction, not a customer-facing function.
   No passage says the Smart CRM enriches, cleans, or reasons over anything.

4. **No answer-engine optimization, no CPQ, no automated billing.** Marketing
   Hub's feature list is "marketing automation and email, social media, SEO, and
   reporting and analytics" — SEO only. P11's system-of-engagement list likewise
   names SEO alone. Commerce Hub's list ends at "automation and revenue
   reporting". CPQ appears in the packet exactly once, in P15, as something
   Cacheflow was acquired to build in.

5. **No AI supplier or model disclosure.** The document never says which models
   power Breeze, whether they are built in-house or licensed, or what the
   dependency is. Item 1 carries no frontier-model dependency evidence.

6. **No per-product revenue, adoption or customer counts.** P12 — "We operate as
   one operating segment." All scale metrics (247,939 Customers, $2.6 billion)
   are firm-level. Nothing supports weighting one product against another by
   economic size.

7. **Traps a naive extractor will fall into.** Recorded because they are the most
   likely sources of false positives:
   - **P1 (Competition)** lists "use of evolving artificial intelligence
     technologies" as a competitive factor and "AI software providers" and "data
     enrichment vendors" as competitors. The ontology is explicit: "Product
     existence cannot be inferred solely from a competitor list or risk factor."
     None of P1 was extracted.
   - **P13 (Marketing and Sales)** describes HubSpot's *own* go-to-market
     operation — "AI-powered tools", "AI-enhanced engagement tools", "AI-driven
     lead scoring and prioritization", "intelligent recommendation systems",
     "machine learning and predictive analytics". These are HubSpot using AI on
     itself, not customer-facing capabilities. SPEC-010's internal-work exclusion
     applies. Note the specific hazard: "AI-driven lead scoring and
     prioritization" in P13 looks almost identical to Sales Hub's "lead scoring"
     in P7, but the P13 instance is HubSpot's internal sales process and carries
     no product. None of P13 was extracted.
   - **P16** — "We also leverage AI to further boost this efficiency" and "We
     leverage AI as a core part of our support offerings" describe HubSpot's own
     support operation, not something a customer operates. Not extracted.
   - **P9 (Our Technology)** is entirely infrastructure — HBase, Kafka, Vitess,
     Elasticsearch, microservices, redundancy, DDoS protection: internal
     technologies not exposed to customers. Its one customer-touching sentence,
     delivery "through APIs, web browsers or mobile applications", is a delivery
     channel, not a task.
   - **P15 (Our Growth Strategy)** is forward-looking intent plus the two
     acquisitions. No capability was taken from it — see Kararsız item 6.

8. **Snapshot data-quality observation.** P6 ends mid-attribute with an unclosed
   HTML fragment: `<p style="text-indent:-9.971%;padding-left:9.067%;font-size:10pt;margin-top:10pt;font-family:Times New Roman;margin-bottom:0;text-align:left;"`.
   Raw markup is leaking through the normalizer into passage text. The identical
   fragment appears in the FY2025 snapshot's corresponding passage, so this is a
   systematic normalizer behaviour, not a one-off. P6 carries no extractable
   content, so this annotation is unaffected, but it will corrupt evidence-quote
   validation wherever markup lands mid-sentence, and it inflates character
   offsets.

9. **P2 is a heading stub** — `> ITEM I. BUSINESS`, 18 characters, with a leading
   `>` and the item number rendered as a Roman numeral `I`. One of 16 passages —
   6% of the packet — is furniture, and any code that parses the item number
   expecting `ITEM 1` will not match this document.

10. **Entity evidence is concentrated in four passages.** P4, P7, P11 and P16
    carry every product, capability and task in this annotation; P7 alone carries
    12 of 14 products and 60 of 69 capabilities. The other twelve passages — 75%
    of the packet — contribute nothing extractable. Any retrieval or chunk-ranking
    stage that fails to select P7 loses almost the entire observation.
