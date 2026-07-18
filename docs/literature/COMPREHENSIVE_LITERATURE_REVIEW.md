# Comprehensive Literature Review

## Dynamic AI Product Evolution: Product–Capability–Task Transformation, Frontier Replicability, Deployment, and Defensibility

**Document status:** Living literature synthesis for the clean-room thesis repository  
**Last bibliographic review:** 2026-07-18  
**Primary observation window of the thesis:** approximately 2022–2026  
**Primary empirical unit:** `firm × observation date × product × capability × customer-facing task`  
**Governing methodology:** `docs/THESIS_METHODOLOGY_AND_DATA.md`  

---

## 0. How to use this document

This review replaces the legacy literature note that framed the project as a static product-task exposure database followed by a predetermined difference-in-differences analysis. The old note remains useful as a list of candidate references, but its project-specific claims, equations, implementation statements, source restrictions, and causal-design commitments are not carried forward.

The current thesis asks a broader and more dynamic question:

> How did software firms redesign customer-facing products and tasks during the frontier-LLM transition, and which combinations of frontier task replicability, AI transformation depth, deployment scale, task-specific defensibility, and task importance were associated with different strategic and economic trajectories?

The literature is therefore organized around six conceptually distinct objects:

1. **The customer-facing task** supplied by the focal product.
2. **The dated frontier alternative** available at the observation cutoff.
3. **The firm's transformation response**, ranging from superficial assistance to workflow execution and orchestration.
4. **Deployment scale**, which separates announcement from actual availability, breadth, usage, and commercialization.
5. **Task-specific defensibility**, including workflow state, permissions, integrations, specialized assets, trust, authority, and switching friction.
6. **Outcomes**, which are empirical consequences rather than components of the exposure or adoption measure.

The central synthesis is:

```text
Exposure is not adoption.
Adoption is not transformation.
Transformation is not deployment.
Deployment is not defensibility.
Defensibility is not realized performance.
```

This distinction is the literature review's organizing principle and should remain visible in every extraction, measurement, and empirical-design decision.

### Publication-status labels

Entries use the following labels:

- **[Peer-reviewed]** — published in an academic journal or refereed proceedings.
- **[Working paper]** — not yet peer-reviewed or final at the review date.
- **[Official research report]** — research released by an institution or firm, not necessarily peer-reviewed.
- **[Benchmark/preprint]** — technical benchmark or preprint whose results may change with later versions.
- **[Book/chapter]** — scholarly book or edited-volume contribution.

Working papers and benchmarks are included because the frontier-LLM literature develops faster than journal publication cycles. They must not be represented as final consensus evidence.

---

# Part I — What changed relative to the legacy review

## 1. Legacy-framework audit

The table below records the main changes. It is intentionally explicit so that prior assumptions do not leak back into the new project.

| Legacy claim or design | Current treatment | Reason for revision |
|---|---|---|
| The project is a **Product-Task LLM Exposure Database** | Replaced by a **dynamic product–capability–task evolution dataset** | A firm is not a fixed task bundle; products, capabilities, tasks, delivery modes, and commercial positioning change after the frontier shock. |
| `10-K Item 1` is the sole or near-sole source | Item 1 remains an anchor, but the corpus includes dated SEC filings/exhibits, official IR materials, product pages, developer documentation, release notes, pricing pages, and archived official pages | Item 1 often identifies products and strategic direction but is frequently insufficient for precise functionality, launch timing, execution depth, deployment breadth, or commercialization. |
| One extraction pass directly produces tasks and scores | Extraction is separated into source discovery, product extraction, capability extraction, task extraction, role classification, longitudinal matching, and measurement | Joint extraction and scoring encourages confirmation bias and allows the target score to distort the task universe. |
| Product tasks are represented only as value propositions or a fixed small number of subtasks | The canonical hierarchy is `company → product family → product → capability → customer-facing task → customer need` | Product names, functions, and economic jobs are different entities and evolve differently over time. |
| The main measure is a categorical `R0/R1/R2` score aggregated into a single `ρ` | Frontier replicability is retained as a construct, but the final scale is not yet frozen and remains separate from transformation, scale, and defensibility | A single technical-replicability score cannot distinguish Chegg-like direct substitution from Adobe- or workflow-platform transformation. |
| A firm-level friction parameter `δ` is combined mechanically with `ρ` | No current commitment to one multiplicative friction formula | Workflow state, permissions, specialized engines, customer data, network effects, legal authority, quality risk, and migration costs may not form one unidimensional construct. |
| `PDS`, `GSS`, `AES`, `DRS`, and `DES` are governing constructs | Removed from the clean-room methodology | They were designed for a different static framework and would pre-structure the new extraction and interpretation. |
| AI adoption is implicitly a protective or beneficial response | Rejected | Deep AI integration can be defensive and commoditized when the frontier directly satisfies the underlying need at low switching cost. |
| AI wording is evidence of adoption | Rejected | “AI-powered,” “copilot,” and “agent” are candidate-discovery terms, not measurement evidence. Concrete actions, state access, tools, availability, and commercialization must be observed. |
| The task list is fixed and only frontier capability changes | Both the task universe and frontier capability are dynamic | Firms add, remove, merge, split, transform, and reposition tasks; the frontier also expands. These channels must be separated. |
| The thesis treatment is fixed to a pre-shock score followed by a predetermined DiD | No causal-design commitment before data validation | The primary contribution is a longitudinal measurement system. Descriptive trajectories, transition analysis, panel associations, event studies, and causal designs are evaluated only after the data-generating process is understood. |
| The launch date or shock date was treated imprecisely | Any event date must be explicitly sourced and design-specific | ChatGPT's public launch was 30 November 2022, but a single launch date may not correspond to product adoption, API access, model capability, or firm response. |
| A specific model/provider is embedded in the project definition | Models are implementation instruments recorded in run manifests, not methodological identities | The extraction and evaluation design must survive model changes and be reproducible across model versions. |

## 2. References removed or corrected from the legacy note

Several legacy entries should not be retained without qualification:

- **Pizzinelli et al. (2023)** must be cited as Carlo Pizzinelli, Augustus J. Panton, Marina Mendes Tavares, Mauro Cazzaniga, and Longji Li. The paper adjusts occupational exposure for potential complementarity; it is not direct precedent for a fixed firm-product `ρ × (1−δ)` equation.
- The prior citation to **Acemoglu, Lelarge, and Restrepo (2022)** conflated distinct robot-adoption papers and is not retained in that form.
- The previous **Doval (2026)** entry was not sufficiently bibliographically verified and is omitted.
- The Microsoft realized-use paper should be cited as **Tomlinson, Jaffe, Wang, Counts, and Suri (2025), “Working with AI: Measuring the Applicability of Generative AI to Occupations.”**
- Statements that an old prompt, Gemini version, score, or implementation was “the project” are removed. The literature review concerns constructs and evidence, not a legacy implementation.
- Correlation targets or benchmark values from unpublished or unverified sources are not used as acceptance thresholds.

---

# Part II — The thesis's conceptual foundation

## 3. Tasks as the unit of technological change

### 3.1 Autor, Levy, and Murnane (2003)

**Status:** [Peer-reviewed]  
**Citation:** Autor, D. H., Levy, F., & Murnane, R. J. (2003). The skill content of recent technological change: An empirical exploration. *Quarterly Journal of Economics, 118*(4), 1279–1333. DOI: 10.1162/003355303322552801.

The task approach's key insight is that technology does not act on occupations or firms as indivisible objects. It substitutes for some activities, complements others, and changes how work is organized. The routine/non-routine framework was created for labor-market analysis, but the deeper lesson generalizes to product markets: a software firm can contain directly replicable informational outputs alongside non-replicable execution, governance, and workflow tasks.

**Implication for the thesis:** Firm-level labels should be aggregated from task-level observations rather than assigned directly. Heterogeneity within a product and within a firm is substantive, not noise.

### 3.2 Acemoglu and Restrepo (2018, 2019, 2022)

**Status:** [Peer-reviewed]

- Acemoglu, D., & Restrepo, P. (2018). The race between man and machine. *American Economic Review, 108*(6), 1488–1542. DOI: 10.1257/aer.20160696.
- Acemoglu, D., & Restrepo, P. (2019). Automation and new tasks. *Journal of Economic Perspectives, 33*(2), 3–30. DOI: 10.1257/jep.33.2.3.
- Acemoglu, D., & Restrepo, P. (2022). Tasks, automation, and the rise in U.S. wage inequality. *Econometrica, 90*(5), 1973–2016. DOI: 10.3982/ECTA19815.

These papers distinguish a displacement effect, in which capital or automation takes over existing tasks, from reinstatement or new-task effects, in which technology creates new activities. This distinction is central to a longitudinal product study. Generative AI may destroy an incumbent product's delivery layer, augment an existing capability, or create new AI-native jobs and workflows.

**Implication:** The transition taxonomy must represent at least continuation, assistance, transformation, entry, replacement, split, merge, and discontinuation. Counting only AI additions would miss product destruction and portfolio reallocation.

### 3.3 Autor (2015) and Polanyi's paradox

**Status:** [Peer-reviewed]  
**Citation:** Autor, D. H. (2015). Why are there still so many jobs? *Journal of Economic Perspectives, 29*(3), 3–30. DOI: 10.1257/jep.29.3.3.

Autor emphasizes that many valuable activities depend on tacit knowledge, context, judgment, and physical interaction that are difficult to fully codify. Foundation models weaken some historical boundaries by learning broad statistical representations, but enterprise execution, reliable tool use, persistent state, authority, and physical action still create capability gaps.

**Implication:** Frontier replicability should not be inferred from linguistic similarity. It must assess the complete customer outcome, including required context and execution, under a dated capability baseline.

### 3.4 Brynjolfsson and Mitchell (2017); Brynjolfsson, Mitchell, and Rock (2018)

**Status:** [Peer-reviewed]

- Brynjolfsson, E., & Mitchell, T. (2017). What can machine learning do? *Science, 358*(6370), 1530–1534. DOI: 10.1126/science.aap8062.
- Brynjolfsson, E., Mitchell, T., & Rock, D. (2018). What can machines learn, and what does it mean for occupations and the economy? *AEA Papers and Proceedings, 108*, 43–47. DOI: 10.1257/pandp.20181019.

These studies argue for mapping technological capabilities to task characteristics rather than making broad occupation-level predictions. Their task-suitability logic supports a structured counterfactual: which elements of the customer task can a dated system complete, under what inputs, and with what residual requirements?

**Implication:** The frontier registry should record capabilities such as modality, context, retrieval, code execution, tool calling, computer use, latency, and reliability—not merely model names.

---

## 4. General-purpose technologies, co-invention, and organizational complements

### 4.1 Bresnahan and Trajtenberg (1995)

**Status:** [Peer-reviewed]  
**Citation:** Bresnahan, T. F., & Trajtenberg, M. (1995). General purpose technologies: “Engines of growth”? *Journal of Econometrics, 65*(1), 83–108. DOI: 10.1016/0304-4076(94)01598-T.

A general-purpose technology creates value through broad applicability, improvement over time, and complementary innovation in downstream sectors. Foundation models fit this framework better than a narrow software feature. Their economic impact depends on co-invention: firms redesign workflows, products, data systems, interfaces, and organizations around the new capability.

**Implication:** The study should measure firm response as product and task reconfiguration, not simply the presence of an AI feature.

### 4.2 Brynjolfsson and Hitt (2000); Brynjolfsson, Hitt, and Yang (2002)

**Status:** [Peer-reviewed]

- Brynjolfsson, E., & Hitt, L. M. (2000). Beyond computation: Information technology, organizational transformation and business performance. *Journal of Economic Perspectives, 14*(4), 23–48. DOI: 10.1257/jep.14.4.23.
- Brynjolfsson, E., Hitt, L. M., & Yang, S. (2002). Intangible assets: Computers and organizational capital. *Brookings Papers on Economic Activity, 2002*(1), 137–198.

IT value often requires complementary organizational investment: process redesign, training, data quality, decentralized decision rights, and new business practices. This explains why the same frontier model can produce different outcomes across firms.

**Implication:** AI Transformation Depth should identify whether AI is embedded in the product's operational state and action path. Deployment Scale should remain separate because technically deep integration can still be a narrow pilot.

### 4.3 Brynjolfsson, Rock, and Syverson (2021) — the productivity J-curve

**Status:** [Peer-reviewed]  
**Citation:** Brynjolfsson, E., Rock, D., & Syverson, C. (2021). The productivity J-curve: How intangibles complement general purpose technologies. *American Economic Journal: Macroeconomics, 13*(1), 333–372. DOI: 10.1257/mac.20180386.

Measured productivity can lag technological potential because complementary intangible investments are initially expensed and only later generate output. Early outcome regressions may therefore understate transformation or show non-monotonic dynamics.

**Implication:** The thesis should avoid interpreting a short-run null outcome as evidence that transformation is shallow. Product and task changes are outcomes in their own right, and financial effects may be delayed.

### 4.4 Bresnahan, Greenstein, and Yin (2025)

**Status:** [Working paper]  
**Citation:** Bresnahan, T. F., Greenstein, S., & Yin, P.-L. (2025). New economic forces behind the value distribution of innovation. NBER Working Paper 34090. DOI: 10.3386/w34090.

The paper distinguishes incremental and novel co-invention around a general-purpose technology. Similar firms may undertake low-cost incremental adaptation, while novel complements are expensive and uncertain but can create much larger value.

**Implication:** “AI adoption” should not be a binary variable. The ontology should distinguish incremental feature augmentation from new product families, cross-product workflows, model ecosystems, and orchestration layers.

---

## 5. Dynamic capabilities and product reconfiguration

### 5.1 Teece, Pisano, and Shuen (1997)

**Status:** [Peer-reviewed]  
**Citation:** Teece, D. J., Pisano, G., & Shuen, A. (1997). Dynamic capabilities and strategic management. *Strategic Management Journal, 18*(7), 509–533.

Dynamic capabilities concern the firm's capacity to sense opportunities, seize them, and reconfigure assets under technological change. This is a natural strategy foundation for longitudinal product evolution.

**Implication:** Firm response should be observed through product entry, capability integration, changes in delivery architecture, acquisitions, discontinued tasks, and new commercialization—not inferred from strategic rhetoric.

### 5.2 Henderson and Clark (1990)

**Status:** [Peer-reviewed]  
**Citation:** Henderson, R. M., & Clark, K. B. (1990). Architectural innovation. *Administrative Science Quarterly, 35*(1), 9–30. DOI: 10.2307/2393549.

Architectural innovation changes how product components are linked even when underlying components remain familiar. Generative AI can be a component-level enhancement or an architectural change that reorganizes an end-to-end workflow.

**Implication:** Transformation depth should not be based only on output sophistication. A text generator embedded in a persistent workflow with permissions, tools, review, and activation may represent deeper architectural change than a more impressive standalone generation demo.

### 5.3 Tripsas and Gavetti (2000)

**Status:** [Peer-reviewed]  
**Citation:** Tripsas, M., & Gavetti, G. (2000). Capabilities, cognition, and inertia. *Strategic Management Journal, 21*(10–11), 1147–1161.

Incumbent response can be constrained by managerial beliefs and existing business models even when technical capability exists. This is relevant to firms that successfully add AI features but fail to change pricing, distribution, customer jobs, or portfolio focus.

**Implication:** Technical transformation, commercial deployment, and strategic success must be separate variables.

### 5.4 Argente, Baslandze, Hanley, and Moreira (2025)

**Status:** [Working paper]  
**Citation:** Argente, D., Baslandze, S., Hanley, D., & Moreira, S. (2025). Patents to products: Product innovation and firm dynamics. NBER Working Paper 34592. DOI: 10.3386/w34592.

The paper directly links invention to product introductions and shows why product-level data can reveal innovation dynamics that patents alone miss. It also illustrates that product entry is a distinct empirical object, not a synonym for R&D or patenting.

**Implication:** The thesis's product and capability transition panel is substantively valuable even without an immediate causal outcome design.

### 5.5 Cohen, Higgins, Miles, and Shibuya (2025/2026)

**Status:** [Working paper]  
**Citation:** Cohen, W. M., Higgins, M. J., Miles, W. D., & Shibuya, Y. (2025, revised 2026). Blockbusters, sequels and the nature of innovation. NBER Working Paper 33957. DOI: 10.3386/w33957.

This product-level innovation study highlights demand stickiness and path dependence: successful products shape the direction of subsequent innovation.

**Implication:** Task economic importance and pre-existing product success may predict where firms concentrate AI transformation. The thesis should avoid treating all tasks as equally likely to be transformed.

---

# Part III — Measuring AI capability and exposure

## 6. A priori task-exposure measures

### 6.1 Eloundou, Manning, Mishkin, and Rock (2024)

**Status:** [Peer-reviewed]  
**Citation:** Eloundou, T., Manning, S., Mishkin, P., & Rock, D. (2024). GPTs are GPTs: Labor market impact potential of LLMs. *Science, 384*(6702), 1306–1308. DOI: 10.1126/science.adj0998. Earlier working-paper version: arXiv:2303.10130.

Eloundou et al. created an influential task-level rubric for whether an LLM or LLM-enabled software could reduce worker task completion time while preserving quality. Its contribution is methodological: evaluate specific tasks relative to a dated technology frontier, then aggregate.

**What carries forward:**

- task-level rather than broad occupational judgment;
- explicit technology assumptions;
- separate treatment of direct model capability and model-plus-software capability;
- human and model annotation as measurement instruments;
- evidence that the frontier is heterogeneous across tasks.

**What does not carry forward unchanged:**

- the labor-time-reduction threshold is not the natural primitive for a customer-facing product output;
- worker tasks and product tasks are different constructs;
- a static rubric cannot represent firm adaptation;
- a single weighted average cannot represent transformation, scale, and defensibility.

For this thesis, the analogous question is:

> At the observation cutoff, could the frontier system satisfy the underlying customer need to a practically substitutable degree without the focal product?

The answer must include the complete required outcome, not only whether the model can generate related text.

### 6.2 Felten, Raj, and Seamans (2018, 2021)

**Status:** [Peer-reviewed]

- Felten, E. W., Raj, M., & Seamans, R. (2018). A method to link advances in artificial intelligence to occupational abilities. *AEA Papers and Proceedings, 108*, 54–57. DOI: 10.1257/pandp.20181021.
- Felten, E. W., Raj, M., & Seamans, R. (2021). Occupational, industry, and geographic exposure to artificial intelligence. *Strategic Management Journal, 42*(12), 2195–2217. DOI: 10.1002/smj.3286.

AIOE maps progress in AI applications to occupational abilities. It establishes that exposure is a relational construct between technological capabilities and task or ability requirements.

**Implication:** The frontier registry and task requirement schema are both necessary. Neither a model leaderboard nor a task description alone is sufficient.

### 6.3 Webb (2020)

**Status:** [Working paper]  
**Citation:** Webb, M. (2020). The impact of artificial intelligence on the labor market. Stanford working paper.

Webb measures overlap between task language and patent language. Its strengths are scale and historical coverage; its weakness is that textual overlap can produce false substantive matches.

**Implication:** Semantic retrieval may generate candidates, but classification must be evidence-grounded and counterfactual. Keyword overlap cannot establish product substitutability or transformation depth.

### 6.4 Frey and Osborne (2017)

**Status:** [Peer-reviewed]  
**Citation:** Frey, C. B., & Osborne, M. A. (2017). The future of employment. *Technological Forecasting and Social Change, 114*, 254–280. DOI: 10.1016/j.techfore.2016.08.019.

The study estimates occupation-level computerization probabilities using expert labels and bottleneck variables. It is an important historical reference but not an appropriate direct benchmark for frontier LLMs.

**Implication:** Validation should be construct-specific. Weak correlation with pre-LLM physical automation measures need not imply poor validity.

### 6.5 Pizzinelli, Panton, Tavares, Cazzaniga, and Li (2023)

**Status:** [Working paper]  
**Citation:** Pizzinelli, C., Panton, A. J., Tavares, M. M., Cazzaniga, M., & Li, L. (2023). Labor market exposure to AI: Cross-country differences and distributional implications. IMF Working Paper 2023/216. DOI: 10.5089/9798400254802.001.

The paper distinguishes exposure from potential complementarity using occupational context. Its strongest relevance is conceptual: high technical exposure can coexist with complementarity rather than displacement.

**Implication:** The thesis should maintain separate constructs rather than interpreting frontier replicability as realized destruction. However, occupational complementarity variables should not be mechanically translated into one firm-product friction score.

### 6.6 Eisfeldt, Schubert, Zhang, and Taska

**Status:** [Working paper / forthcoming]  
**Citation:** Eisfeldt, A. L., Schubert, G., Zhang, M. B., & Taska, B. Generative AI and firm values. NBER Working Paper 31222; forthcoming in the *Journal of Finance*; consult the latest version for final title and results.

The paper constructs firm exposure through workforce composition and links exposure to market valuation around generative-AI developments. It is a central firm-level precedent, but its exposure is labor-input-side rather than product-output-side.

**Implication:** The thesis provides a complementary construct: what the firm's products do for customers and how those tasks evolve. Workforce exposure may serve as an external comparison, not a substitute for product-task data.

### 6.7 Hampole, Papanikolaou, Schmidt, and Seegmiller (2025)

**Status:** [Working paper]  
**Citation:** Hampole, M., Papanikolaou, D., Schmidt, L. D. W., & Seegmiller, B. (2025). Artificial intelligence and the labor market. NBER Working Paper 33509. DOI: 10.3386/w33509.

This study constructs exposure measures that vary across firms, occupations, tasks, and time. It also distinguishes mean exposure from concentration across tasks, arguing that concentration can permit reallocation.

**Implication:** Aggregation should preserve the distribution of task properties, not only a mean. A firm with one highly exposed core task differs from a firm with many moderately exposed peripheral tasks even if the average is equal.

---

## 7. Realized AI use versus technical possibility

### 7.1 Tomlinson, Jaffe, Wang, Counts, and Suri (2025)

**Status:** [Official research report / working paper]  
**Citation:** Tomlinson, K., Jaffe, S., Wang, W., Counts, S., & Suri, S. (2025). Working with AI: Measuring the applicability of generative AI to occupations. Microsoft Research.

The study uses a large sample of anonymized Copilot conversations to infer user goals, AI actions, task completion, and applicability. It represents realized use rather than theoretical capability.

**Implication:** Frontier Task Replicability and realized adoption should not be conflated. Realized-use datasets can validate whether task categories appear in practice, but their user population, product interface, and access regime create selection effects.

### 7.2 Anthropic Economic Index (2025–2026)

**Status:** [Official research reports]

The Anthropic Economic Index maps privacy-preserving patterns of Claude use to tasks and distinguishes collaboration, augmentation, and automation modes. Later reports add economic primitives, autonomy, and task success.

**Implication:** The distinction between what users ask for, what the model does, and whether the result succeeds is highly relevant. The thesis should preserve separate fields for customer need, AI action, execution scope, human oversight, and outcome evidence.

**Caution:** Provider-specific usage data are not representative of the entire economy and change as interfaces, models, pricing, and user composition evolve.

### 7.3 Bick, Blandin, and Deming (2024/2025)

**Status:** [Working paper]  
**Citation:** Bick, A., Blandin, A., & Deming, D. J. (2024, revised 2025). The rapid adoption of generative AI. NBER Working Paper 32966. DOI: 10.3386/w32966.

National surveys show rapid generative-AI adoption, but frequency and intensity vary. Adoption at least once is not the same as deep integration into production.

**Implication:** Deployment Scale must distinguish availability, occasional use, repeated use, workflow breadth, user breadth, and economic relevance.

### 7.4 Bonney, Breaux, Dinlersoz, Foster, Haltiwanger, and Pande (2026)

**Status:** [Working paper]  
**Citation:** Bonney, K., Breaux, C. L., Dinlersoz, E., Foster, L. S., Haltiwanger, J. C., & Pande, A. A. (2026). The microstructure of AI diffusion: Evidence from firms, business functions, and worker tasks. NBER Working Paper 35141. DOI: 10.3386/w35141.

This paper is especially important for the thesis because it separates three layers: firm-level adoption, business-function deployment, and worker-task use. It finds that even among adopters, use can remain concentrated in a small number of functions.

**Implication:** A firm-level “AI user” indicator is too coarse. The thesis's product–capability–task hierarchy and deployment-breadth measures directly address this problem on the output side of the firm.

### 7.5 Yotzov et al. (2026); Baslandze et al. (2026); Bick et al. (2026)

**Status:** [Working papers]

- Yotzov, I., et al. (2026). Firm data on AI. NBER Working Paper 34836. DOI: 10.3386/w34836.
- Baslandze, S., et al. (2026). Artificial intelligence, productivity, and the workforce: Evidence from corporate executives. NBER Working Paper 34984. DOI: 10.3386/w34984.
- Bick, A., Blandin, A., Deming, D. J., Fuchs-Schündeln, N., & Jessen, J. (2026). Mind the gap: AI adoption in Europe and the U.S. NBER Working Paper 34995. DOI: 10.3386/w34995.

These surveys provide valuable evidence on adoption, expected productivity, management encouragement, and cross-country differences. They also reveal that adoption definitions and sampling frames produce very different headline rates.

**Implication:** The thesis should not validate Deployment Scale against one generic adoption statistic. It should use task-specific official evidence and document the denominator for every scale claim.

---

# Part IV — Does AI adoption improve firm performance?

## 8. Firm-level AI, growth, and product innovation

### 8.1 Babina, Fedyk, He, and Hodson (2024)

**Status:** [Peer-reviewed]  
**Citation:** Babina, T., Fedyk, A., He, A. X., & Hodson, J. (2024). Artificial intelligence, firm growth, and product innovation. *Journal of Financial Economics, 151*, 103745. DOI: 10.1016/j.jfineco.2023.103745.

Using AI-related human capital and patents, the paper finds that AI investment is associated with firm growth and product innovation, particularly in product-oriented channels. It measures AI input and capability accumulation rather than product-task transformation.

**Implication:** AI investment is a potential antecedent of product transformation and an external validation variable. It should not be treated as equivalent to deep customer-facing adoption.

### 8.2 Babina (2026) — measuring firms' AI efforts

**Status:** [Working paper]  
**Citation:** Babina, T. (2026). Understanding firms' AI efforts and their economic impact. NBER working paper / research chapter; use the latest bibliographic version.

This recent synthesis emphasizes multiple dimensions of firm AI effort: invention versus use, in-house development versus external sourcing, managerial perceptions versus realized deployment, and inputs versus outputs.

**Implication:** The thesis's construct separation is consistent with the broader measurement literature. Source data should record first-party models, frontier-model use, partner models, custom models, and orchestration without ranking one sourcing strategy as inherently superior.

### 8.3 Eisfeldt et al. — market expectations

Market-value studies capture investor expectations about future rents, not realized product performance. Positive valuation for exposed firms can reflect expected productivity gains, ownership of complementary assets, or anticipated demand for AI infrastructure.

**Implication:** Stock returns should be interpreted as one outcome channel and should not validate task-level replicability by themselves.

---

## 9. Field evidence on productivity and task reorganization

### 9.1 Noy and Zhang (2023)

**Status:** [Peer-reviewed]  
**Citation:** Noy, S., & Zhang, W. (2023). Experimental evidence on the productivity effects of generative artificial intelligence. *Science, 381*(6654), 187–192. DOI: 10.1126/science.adh2586.

The experiment finds faster and often higher-quality completion of professional writing tasks. It demonstrates meaningful productivity effects within the frontier while also focusing on a narrow task set.

**Implication:** Content generation can be economically consequential, but task-level productivity does not reveal whether an incumbent product retains differentiated value.

### 9.2 Dell'Acqua et al. (2023/2024) — jagged frontier

**Status:** [Working paper]  
**Citation:** Dell'Acqua, F., McFowland, E., Mollick, E. R., et al. Navigating the jagged technological frontier. Harvard Business School Working Paper 24-013.

The BCG field experiment shows gains on tasks within the model frontier and poorer performance on tasks outside it. The “jagged frontier” is a critical caution against smooth, firm-wide exposure scores.

**Implication:** Frontier scoring requires task-specific evidence, dated assumptions, and uncertainty. A model's excellence in one modality should not spill over automatically to execution-heavy tasks.

### 9.3 Brynjolfsson, Li, and Raymond (2025)

**Status:** [Peer-reviewed]  
**Citation:** Brynjolfsson, E., Li, D., & Raymond, L. R. (2025). Generative AI at work. *Quarterly Journal of Economics*. Earlier version: NBER Working Paper 31161. DOI: 10.1093/qje/qjae044.

The study of customer-support agents documents average productivity gains and larger benefits for less experienced workers, consistent with knowledge diffusion and augmentation.

**Implication:** AI can transform task performance without removing the surrounding product or organization. Human-in-the-loop and knowledge-transfer modes should remain visible in the extraction.

### 9.4 Peng, Kalliamvakou, Cihon, and Demirer (2023); later developer RCTs

**Status:** [Benchmark/preprint / working papers]

- Peng, S., Kalliamvakou, E., Cihon, P., & Demirer, M. (2023). The impact of AI on developer productivity: Evidence from GitHub Copilot. arXiv:2302.06590.
- Cui, K., et al. (2025). The effects of generative AI on high-skilled work: Evidence from three field experiments with software developers. Microsoft Research working paper.

These studies show that AI-assisted coding can improve task throughput, with effects varying by worker and task context.

**Implication:** Code generation is not identical to replacing a developer platform, source-control system, cloud environment, or enterprise software product. The customer need and full production chain must be defined precisely.

### 9.5 Dillon, Jaffe, Immorlica, and Stanton (2025)

**Status:** [Working paper]  
**Citation:** Dillon, E. W., Jaffe, S., Immorlica, N., & Stanton, C. T. (2025). Shifting work patterns with generative AI. NBER Working Paper 33795. DOI: 10.3386/w33795.

Across 66 firms and more than 7,000 workers, integrated generative AI reduced time spent on some activities but did not produce large changes in the quantity or composition of tasks during the observation window.

**Implication:** Individual productivity and organizational task transformation can diverge. Deep product transformation should not be inferred from user access to a copilot.

### 9.6 Dell'Acqua et al. (2025) — cybernetic teammate

**Status:** [Working paper]  
**Citation:** Dell'Acqua, F., Ayoubi, C., Lifshitz, H., et al. (2025). The cybernetic teammate. NBER Working Paper 33641. DOI: 10.3386/w33641.

A field experiment at Procter & Gamble shows that individuals with AI can match some benefits of human teams in product-innovation tasks and that AI changes expertise sharing and collaboration.

**Implication:** AI transformation may create new coordination architectures rather than simply automate a unit task. The ontology should allow tasks involving ideation, comparison, synthesis, and cross-functional coordination.

### 9.7 Humlum and Vestergaard (2025/2026)

**Status:** [Working paper]  
**Citation:** Humlum, A., & Vestergaard, E. (2025, revised 2026). Still waters, rapid currents: Early labor market transformation under generative AI. NBER Working Paper 33777. DOI: 10.3386/w33777.

The study reports widespread initiatives and task reorganization, including new AI-related tasks, while finding small early effects on recorded earnings and hours.

**Implication:** Dynamic task data may reveal economically meaningful adaptation before aggregate financial outcomes respond. This supports the thesis's decision not to make a short-run DiD the sole objective.

---

# Part V — Frontier replicability and the meaning of “deep” AI transformation

## 10. Foundation models as a common capability layer

### 10.1 Bommasani et al. (2021)

**Status:** [Benchmark/preprint / research report]  
**Citation:** Bommasani, R., Hudson, D. A., Adeli, E., et al. (2021). On the opportunities and risks of foundation models. arXiv:2108.07258.

Foundation models create a reusable, general capability layer and encourage homogenization: many downstream products inherit common capabilities and common failure modes.

**Implication:** A company incorporating a frontier model does not automatically possess a proprietary capability. The study must identify what is added around the common model layer.

### 10.2 Commoditization and model access

As comparable capabilities become accessible through multiple model providers, pure prompt wrappers may face low switching barriers. However, common model access can also increase the value of complementary assets such as enterprise data, permissions, workflow state, distribution, compliance controls, specialized engines, and user communities.

**Implication:** Frontier Task Replicability assesses the outside option; Task-Specific Defensibility assesses the residual value of the focal product. These measures can move in opposite directions.

---

## 11. A depth ladder grounded in system capability

The thesis provisionally distinguishes the following transformation levels:

```text
0. No concrete AI integration or wording only
1. Peripheral assistance: search, summary, drafting, autocomplete
2. Direct generation, classification, recommendation, or prediction
3. Native integration with product context or persistent workflow state
4. Multi-step action execution through tools, APIs, records, or transactions
5. Goal-directed orchestration with planning, monitoring, and exception handling
```

This is not a claim that every product follows a linear maturity path. It is an operational ordering of increasing system involvement in the customer task.

### 11.1 Why content generation differs from workflow execution

A system that generates text, code, images, or recommendations produces an artifact. A workflow system must additionally:

- access the correct state;
- respect permissions and policies;
- select and call tools;
- update systems of record;
- maintain consistency across steps;
- verify completion;
- handle exceptions;
- recover from errors;
- operate reliably across repeated trials.

These requirements motivate separate evidence fields for output type, state access, tool use, action scope, autonomy, human approval, and reliability.

### 11.2 AgentBench (2023)

**Status:** [Peer-reviewed / benchmark]  
**Citation:** Liu, X., Yu, H., Zhang, H., et al. (2023). AgentBench: Evaluating LLMs as agents. arXiv:2308.03688; ICLR 2024.

AgentBench measures agents across interactive environments. It helped establish that language proficiency does not imply reliable action in dynamic environments.

### 11.3 WorkArena and WorkArena++ (2024)

**Status:** [Benchmark/preprints]

- Drouin, A., Gasse, M., Caccia, M., et al. (2024). WorkArena: How capable are web agents at solving common knowledge work tasks? arXiv:2403.07718.
- Boisvert, L., Thakkar, M., Gasse, M., et al. (2024). WorkArena++: Towards compositional planning and reasoning-based common knowledge work tasks. arXiv:2407.05291; NeurIPS 2024 benchmark track.

WorkArena evaluates enterprise software tasks; WorkArena++ expands to hundreds of compositional workflows requiring retrieval, planning, reasoning, and interaction.

**Implication:** Enterprise workflow execution is empirically harder than producing plausible text. Product descriptions that claim “agentic” capability require evidence of actions and workflow state, not the label alone.

### 11.4 τ-bench (2024)

**Status:** [Benchmark/preprint]  
**Citation:** Yao, S., Shinn, N., Razavi, P., & Narasimhan, K. (2024). τ-bench: A benchmark for tool-agent-user interaction in real-world domains. arXiv:2406.12045.

τ-bench evaluates agents interacting with users, tools, and domain rules. It uses final database state and repeated-trial reliability measures. Frontier function-calling agents at publication remained inconsistent.

**Implication:** Measurement should distinguish a single demonstrated action from reliable operational deployment. Claims about execution depth need concrete evidence; scale and reliability need separate evidence.

### 11.5 OSWorld (2024)

**Status:** [Benchmark/preprint]  
**Citation:** Xie, T., Zhang, D., Chen, J., et al. (2024). OSWorld: Benchmarking multimodal agents for open-ended tasks in real computer environments. arXiv:2404.07972.

OSWorld evaluates computer-use agents in real operating-system environments and demonstrates a substantial gap between human and model performance at publication.

**Implication:** Dated frontier baselines must avoid hindsight. Capabilities available in 2026 cannot be assigned to a 2023 observation.

### 11.6 METR task-completion time horizons (2025–2026)

**Status:** [Official research report / benchmark]  
**Citation:** Kwa, T., West, B., Becker, J., et al. (2025). Measuring AI ability to complete long tasks. METR.

METR proposes a time-horizon measure: the length of human-equivalent tasks that agents can complete with a given success probability. Results suggest rapid progress while emphasizing uncertainty, benchmark composition, and reliability thresholds.

**Implication:** Task duration and sequential dependency are useful task requirements, but they should not become a universal replicability formula. The thesis can record estimated workflow length, number of dependent steps, and required reliability as explanatory features.

---

# Part VI — Deployment Scale: from announcement to economic use

## 12. Why deployment is multidimensional

The diffusion literature shows that “adoption” can mean very different things:

- a firm reports experimenting with AI;
- one employee used a public chatbot;
- a feature is available in beta;
- a paid product is generally available;
- several workflows use the capability;
- the capability is default across a suite;
- users repeatedly use it;
- it affects revenue, retention, or cost.

A single ordinal scale risks conflating these dimensions. The extraction therefore preserves at least:

1. **Availability:** roadmap, announced, private preview, public beta, general availability, default.
2. **Product breadth:** one feature, multiple capabilities in one product, multiple products, platform-wide.
3. **Workflow breadth:** one step versus multiple steps or end-to-end process coverage.
4. **Customer breadth:** named customer, customer count, seat count, percentage of installed base.
5. **Usage intensity:** active users, generations, transactions, agent runs, API calls, repeated use.
6. **Commercialization:** bundled, add-on, credits, consumption, standalone subscription, material revenue evidence.

### 12.1 Rogers (2003)

**Status:** [Book]  
**Citation:** Rogers, E. M. (2003). *Diffusion of Innovations* (5th ed.). Free Press.

Rogers distinguishes adoption stages and diffusion across a social system. Although not AI-specific, the framework cautions against treating awareness, trial, and sustained use as equivalent.

### 12.2 Organizational adoption research

The technology-organization-environment tradition and complementary-assets literature suggest that adoption depends on firm size, skills, systems, management, competitive pressure, and institutional context.

**Implication:** Deployment Scale is an observed property of the task-product-year, not a direct consequence of technical depth.

### 12.3 Strategic interaction in adoption

Recent field and survey evidence shows that firms update adoption intentions based on beliefs about competitors' technology use. This reinforces the possibility of symbolic or defensive adoption.

**Implication:** AI wording may partly reflect signaling and competitive positioning. Concrete evidence rules are therefore essential.

---

# Part VII — Task-Specific Defensibility and competitive advantage

## 13. Complementary assets and appropriability

### 13.1 Teece (1986)

**Status:** [Peer-reviewed]  
**Citation:** Teece, D. J. (1986). Profiting from technological innovation. *Research Policy, 15*(6), 285–305. DOI: 10.1016/0048-7333(86)90027-2.

Teece argues that innovators capture value when they control appropriability and complementary assets such as manufacturing, distribution, service, and specialized capabilities.

**Implication:** A frontier model's ability to produce an output does not determine who captures value. The focal product may retain necessary complements, or the model provider may commoditize the core deliverable.

### 13.2 Azoulay, Krieger, and Nagaraj (2024/2025)

**Status:** [Peer-reviewed chapter]  
**Citation:** Azoulay, P., Krieger, J. L., & Nagaraj, A. (2025). Old moats for new models: Openness, control, and competition in generative artificial intelligence. In *Entrepreneurship and Innovation Policy and the Economy, Volume 4*. DOI: 10.1086/732852. Earlier version: NBER Working Paper 32474.

The authors apply appropriability and complementary-assets reasoning to generative AI. Control of infrastructure, data, distribution, and downstream complements can shape market structure despite common foundation-model capabilities.

**Implication:** Defensibility should identify the exact complementary asset and test whether it is necessary for the customer's outcome. “Proprietary data” is not automatically a moat if the frontier alternative already performs sufficiently without it.

---

## 14. Switching costs, lock-in, and network effects

### 14.1 Klemperer (1987, 1995); Farrell and Klemperer (2007)

**Status:** [Peer-reviewed / book chapter]

- Klemperer, P. (1987). Markets with consumer switching costs. *Quarterly Journal of Economics, 102*(2), 375–394.
- Klemperer, P. (1995). Competition when consumers have switching costs. *Review of Economic Studies, 62*(4), 515–539.
- Farrell, J., & Klemperer, P. (2007). Coordination and lock-in. In *Handbook of Industrial Organization, Volume 3*.

Switching costs can be contractual, technical, informational, procedural, learning-based, relational, or data-related. They can protect incumbents even when alternatives are technically viable.

**Implication:** The thesis should distinguish task defensibility from broad firm lock-in. An enterprise may face high migration cost for one system while a specific informational task remains easy to bypass with a general model.

### 14.2 Katz and Shapiro (1985); Shapiro and Varian (1999)

**Status:** [Peer-reviewed / book]

- Katz, M. L., & Shapiro, C. (1985). Network externalities, competition, and compatibility. *American Economic Review, 75*(3), 424–440.
- Shapiro, C., & Varian, H. R. (1999). *Information Rules*. Harvard Business School Press.

Installed bases, standards, compatibility, and information-good economics explain why software value can persist beyond a standalone feature.

**Implication:** The schema should record ecosystems and interoperability only when they affect the task's delivery or migration—not as generic firm-level praise.

### 14.3 Rochet and Tirole (2003); Parker and Van Alstyne (2005)

**Status:** [Peer-reviewed]

- Rochet, J.-C., & Tirole, J. (2003). Platform competition in two-sided markets. *Journal of the European Economic Association, 1*(4), 990–1029.
- Parker, G. G., & Van Alstyne, M. W. (2005). Two-sided network effects. *Management Science, 51*(10), 1494–1504.

Platform value can depend on interactions across user groups. A frontier model may replicate one surface task without replicating marketplace liquidity, developer ecosystems, or transaction networks.

**Implication:** Product tasks that coordinate multiple sides require explicit representation of the participants and the delivered outcome.

---

## 15. Ecosystems and bottlenecks

### 15.1 Adner and Kapoor (2010, 2016)

**Status:** [Peer-reviewed]

- Adner, R., & Kapoor, R. (2010). Value creation in innovation ecosystems. *Strategic Management Journal, 31*(3), 306–333.
- Adner, R., & Kapoor, R. (2016). Innovation ecosystems and the pace of substitution. *Strategic Management Journal, 37*(4), 625–648.

Technology substitution depends on bottlenecks in the focal product and its ecosystem. A superior component can diffuse slowly when complementary innovations are missing; incumbents can also benefit from existing ecosystems.

**Implication:** Frontier model capability is only one component. The task-level counterfactual must account for required complements, while defensibility tests whether those complements are controlled and economically necessary.

---

## 16. Trust, error costs, authority, and regulated execution

### 16.1 Agrawal, Gans, and Goldfarb (2018)

**Status:** [Book]  
**Citation:** Agrawal, A., Gans, J., & Goldfarb, A. (2018). *Prediction Machines*. Harvard Business Review Press.

Lower prediction costs change the value of complements such as judgment, action, data, and error management. A technically accurate output may not substitute when liability, auditability, or authority are central.

**Implication:** Defensibility should separate model quality from institutional authority, approval rights, audit trails, and error costs.

### 16.2 Reliability is task-specific

For low-stakes content tasks, occasional errors may be tolerable. For payments, access provisioning, medical decisions, compliance filings, or infrastructure changes, repeated reliability and authorization may be essential.

**Implication:** “Same quality” cannot be one universal threshold. The measurement rubric must interpret practical substitutability relative to task-specific stakes and required success probability, while avoiding speculative legal judgments unsupported by evidence.

---

# Part VIII — Product and task data from corporate text

## 17. 10-K product descriptions as structured economic text

### 17.1 Hoberg and Phillips (2016)

**Status:** [Peer-reviewed]  
**Citation:** Hoberg, G., & Phillips, G. (2016). Text-based network industries and endogenous product differentiation. *Journal of Political Economy, 124*(5), 1423–1465. DOI: 10.1086/688176.

Hoberg and Phillips use 10-K product descriptions to construct time-varying product-market similarity and competition measures. This is the closest foundational precedent for treating Item 1 product language as longitudinal economic data.

**Implication:** Annual product descriptions can support a dynamic product universe. However, similarity metrics and task extraction are different: the thesis needs entity resolution, evidence passages, and capability/task boundaries.

### 17.2 Loughran and McDonald (2011)

**Status:** [Peer-reviewed]  
**Citation:** Loughran, T., & McDonald, B. (2011). When is a liability not a liability? *Journal of Finance, 66*(1), 35–65. DOI: 10.1111/j.1540-6261.2010.01625.x.

The paper demonstrates that financial text requires domain-specific interpretation and that generic dictionaries can misread disclosure language.

**Implication:** Generic keyword counts of “AI,” “agent,” or “platform” are poor proxies for adoption depth. Evidence-grounded semantic extraction is more appropriate.

### 17.3 Li (2010)

**Status:** [Peer-reviewed]  
**Citation:** Li, F. (2010). The information content of forward-looking statements in corporate filings. *Journal of Accounting Research, 48*(5), 1049–1102. DOI: 10.1111/j.1475-679X.2010.00382.x.

Li shows that forward-looking language can be systematically identified and contains information distinct from other filing sections.

**Implication:** Availability status must be extracted. Roadmap claims, announced features, beta products, and generally available capabilities cannot be treated as equivalent active tasks.

### 17.4 Bellstam, Bhagat, and Cookson (2021)

**Status:** [Peer-reviewed]  
**Citation:** Bellstam, G., Bhagat, S., & Cookson, J. A. (2021). A text-based analysis of corporate innovation. *Management Science, 67*(7), 4004–4031. DOI: 10.1287/mnsc.2020.3682.

Text can reveal innovation by firms that do not patent and can predict later outcomes. The paper also shows that source choice matters: analyst reports capture dimensions not represented in patents or R&D.

**Implication:** Product and documentation text can complement traditional innovation measures. The thesis should validate source contribution through ablations rather than assume one source is complete.

---

## 18. Why Item 1 alone is not sufficient

Item 1 is comparatively standardized and useful for identifying business lines, named products, major capabilities, and strategic repositioning. It is often weaker for:

- exact feature behavior;
- developer-facing capabilities;
- tool and API actions;
- launch and deprecation dates;
- historical availability;
- pricing and packaging;
- usage intensity;
- reliability or customer deployment;
- granular product transitions within the year.

The current source hierarchy therefore includes:

```text
SEC filings and exhibits
→ official investor-relations materials
→ official product and solution pages
→ official developer/API documentation
→ official release notes and newsroom
→ archived official pages
```

No source is assumed unbiased. SEC text is investor-oriented; product pages are marketing-oriented; developer docs may omit commercial context; release notes may overrepresent incremental changes; archived pages may be incomplete.

### 18.1 Website-mining evidence

**Status:** [Peer-reviewed]  
**Citation:** *Signals of innovation online: Identifying innovative firms by combining website mining and evidence-producing LLMs.* (2026). *Technological Forecasting and Social Change, 228*, 124695. DOI: 10.1016/j.techfore.2026.124695.

The study finds that website text can be an imperfect innovation signal, that firms may underreport relevant activities, and that evidence-producing LLM classifications improve interpretability relative to opaque keyword-based approaches.

**Implication:** Official web pages are valuable but should be combined with other official sources, date-bounded through snapshots, and linked to evidence passages. The thesis's evidence-producing extraction and source-ablation design directly address these concerns.

---

## 19. Source triangulation and provenance

The literature supports a source-design principle:

> No single document should be asked to establish product identity, technical action, deployment breadth, commercialization, and realized outcome simultaneously.

A defensible record may use:

- Item 1 for product identity and core commercial role;
- release notes for first availability;
- product documentation for concrete customer actions;
- developer docs for tools, APIs, permissions, and execution;
- earnings exhibits for customer or usage scale;
- MD&A and segment notes for financial association.

Every extracted observation should preserve:

- source URL or SEC accession;
- document type;
- publication date;
- retrieval time;
- snapshot hash;
- passage identifier;
- exact supporting excerpt;
- observation cutoff;
- claim type;
- confidence and ambiguity.

This provenance is part of construct validity, not merely engineering metadata.

---

# Part IX — Longitudinal product and task measurement

## 20. The problem of entity resolution over time

A firm can rename a product without changing the customer task, add AI to an existing task, merge products, separate a feature into a standalone product, acquire a product, or discontinue a legacy offering. Naively comparing annual lists creates false entry and exit.

The thesis therefore separates:

1. **Dated observations:** what is stated at each cutoff.
2. **Stable entities:** product, capability, task, and customer-need identifiers.
3. **Transitions:** the relationship between predecessor and successor observations.

### 20.1 Transition vocabulary

The provisional transition types are:

- `same_task`
- `renamed`
- `expanded`
- `contracted`
- `ai_assisted`
- `generative_transformation`
- `workflow_integrated`
- `agentified`
- `split`
- `merged`
- `replaced`
- `discontinued`
- `new_task`
- `uncertain`

These labels are not presumed mutually exclusive at every analytical level. A task may be renamed and expanded; a product may be acquired and later integrated. The released schema should preserve primary and secondary transition evidence where needed.

### 20.2 Product entry versus transformed delivery

A new named AI product does not necessarily create a new customer task. For example, an AI assistant may replace the interface through which an existing explanation task is delivered. Conversely, an existing suite may gain a genuinely new task such as autonomous cross-system remediation.

**Implication:** Matching should prioritize underlying customer need and outcome, then examine capability and delivery changes. Name similarity is only candidate-generation evidence.

### 20.3 Task granularity

Too-broad tasks obscure heterogeneity; too-narrow tasks inflate counts and create unstable matching. The ontology should define tasks as economically meaningful customer outcomes, not UI clicks, marketing categories, or every possible content variant.

**Implication:** Granularity agreement is a primary eval metric. Subtasks should be used only when necessary for a distinct requirement or measurement profile.

---

# Part X — LLMs as extraction and measurement instruments

## 21. Why LLM-based extraction is attractive

LLMs can interpret context, normalize varied product language, map feature descriptions to customer outcomes, and produce structured evidence. This is valuable when firms use heterogeneous terminology and when exact keyword dictionaries are brittle.

However, LLM outputs are measurements generated by an instrument. They are not ground truth. The instrument can be sensitive to:

- prompt wording;
- model version;
- document ordering;
- verbosity and marketing language;
- prior examples;
- schema constraints;
- position bias;
- confirmation bias from desired outcomes;
- temporal leakage from model knowledge;
- inconsistent granularity.

The methodology therefore treats prompt design as an evaluated research instrument.

---

## 22. LLM-as-judge and evaluator bias

### 22.1 G-Eval (2023)

**Status:** [Peer-reviewed / preprint]  
**Citation:** Liu, Y., Iter, D., Xu, Y., Wang, S., Xu, R., & Zhu, C. (2023). G-Eval: NLG evaluation using GPT-4 with better human alignment. EMNLP 2023.

G-Eval shows that structured evaluation prompts and reasoning can improve alignment with human ratings. It motivates rubric-based judges but does not eliminate bias.

### 22.2 Wang et al. (2024)

**Status:** [Peer-reviewed]  
**Citation:** Wang, P., Li, L., Chen, L., et al. (2024). Large language models are not fair evaluators. *ACL 2024*, 9440–9450. DOI: 10.18653/v1/2024.acl-long.511.

The paper demonstrates position bias in LLM pairwise evaluation.

**Implication:** Prompt-version comparisons should randomize or reverse output order where an LLM judge is used. Deterministic metrics and human adjudication remain necessary.

### 22.3 Chen et al. (2024)

**Status:** [Peer-reviewed]  
**Citation:** Chen, G. H., Chen, S., Liu, Z., Jiang, F., & Wang, B. (2024). Humans or LLMs as the judge? A study on judgement bias. *EMNLP 2024*, 8301–8327. DOI: 10.18653/v1/2024.emnlp-main.474.

The study documents multiple biases affecting both human and LLM judges.

**Implication:** Human review is not an infallible gold standard. Gold-set creation should use definitions, reason codes, disagreement resolution, and versioned ontology decisions.

### 22.4 Koo et al. (2024); Zhou et al. (2024); Pan et al. (2024)

**Status:** [Peer-reviewed]

- Koo, R., Lee, M., Raheja, V., Park, J. I., Kim, Z. M., & Kang, D. (2024). Benchmarking cognitive biases in large language models as evaluators. *Findings of ACL 2024*.
- Zhou, H., Huang, H., Long, Y., et al. (2024). Mitigating the bias of large language model evaluation. *CCL 2024*.
- Pan, Q., Ashktorab, Z., Desmond, M., et al. (2024). Human-centered design recommendations for LLM-as-a-judge. *HCI+NLP 2024*.

Together, these papers support calibration, adversarial cases, human involvement, and transparent criteria.

**Implication:** The eval harness should include dev, frozen-test, adversarial, and regression sets; deterministic validators; append-only adjudication; model and prompt versioning; and explicit release gates.

---

## 23. Evaluation design for this thesis

The literature implies a layered evaluation architecture.

### Layer 1 — Deterministic validity

Hard checks include:

- schema validity;
- source and passage existence;
- quote-substring validity;
- date cutoff compliance;
- hierarchy validity;
- duplicate IDs;
- prohibited legacy fields;
- unsupported active-task claims;
- roadmap-only evidence incorrectly treated as deployment.

These are not matters for an LLM judge.

### Layer 2 — Gold-set entity comparison

Products, capabilities, and tasks should be compared using stable IDs and accepted aliases rather than exact wording. Precision, recall, duplicate rate, unsupported-claim rate, and granularity errors should be reported separately.

### Layer 3 — Rubric evaluation

Ambiguous constructs—task role, transition type, transformation depth, and defensibility—require explicit rubric dimensions, evidence, and confidence.

### Layer 4 — Human adjudication

Reviewers decide whether the prediction, gold record, both, or neither is acceptable; unclear cases can trigger an ontology decision rather than a forced label.

### Layer 5 — Regression control

Every discovered failure becomes a permanent case. Prompt changes are accepted only when they fix the targeted class without unacceptable regressions on frozen cases.

This process is a methodological requirement, not an optional software-quality feature.

---

# Part XI — Mapping the literature to the thesis constructs

## 24. Frontier Task Replicability (FTR)

### Definition

The degree to which the dated frontier system can satisfy the underlying customer need without the focal firm's product.

### Literature foundations

- task-based technology mapping: Autor et al.; Brynjolfsson and Mitchell;
- LLM task exposure: Eloundou et al.; Felten et al.; Pizzinelli et al.;
- jagged frontier and task heterogeneity: Dell'Acqua et al.;
- realized use as validation, not definition: Tomlinson et al.; Anthropic Economic Index;
- agent/tool limits: WorkArena, τ-bench, OSWorld, METR.

### Required extraction inputs

- customer need;
- core deliverable;
- required input modalities;
- private or live data needs;
- output and action requirements;
- sequential steps;
- tool/API requirements;
- latency and recency needs;
- required reliability;
- human, legal, or physical action requirements.

### Key counterfactual

> Could a customer plausibly obtain the required outcome from the frontier alternative available by the cutoff, without adopting the focal product?

### Non-rules

- High language similarity does not imply replicability.
- An API-accessible frontier model does not automatically include enterprise permissions or systems of record.
- Proprietary data does not automatically block replication.
- A benchmark success does not automatically establish production-quality substitution.

---

## 25. AI Transformation Depth (AITD)

### Definition

The degree to which AI changes how the focal product performs the customer task, from peripheral assistance to generation, stateful workflow integration, multi-step execution, and orchestration.

### Literature foundations

- general-purpose technology and co-invention: Bresnahan and Trajtenberg;
- organizational complements: Brynjolfsson and Hitt; Brynjolfsson et al.;
- architectural innovation: Henderson and Clark;
- dynamic capabilities: Teece et al.;
- task reorganization: Humlum and Vestergaard; Dillon et al.;
- agent benchmarks: AgentBench, WorkArena, τ-bench, OSWorld, METR.

### Evidence dimensions

- concrete AI action;
- generated output or decision;
- use of product/customer context;
- persistent workflow state;
- tool/API invocation;
- record or transaction update;
- action scope;
- planning and sequencing;
- monitoring and exception handling;
- human approval and fallback.

### Interpretation

Depth is descriptive. It is not a benefit score. A direct-answer product can integrate AI deeply yet remain vulnerable if the frontier supplies the same need directly.

---

## 26. Deployment Scale (DS)

### Definition

The breadth and commercial reality of the transformed capability.

### Literature foundations

- diffusion of innovations: Rogers;
- firm and worker adoption: Bick et al.; Yotzov et al.; Bonney et al.;
- organizational deployment and task scope: Dillon et al.; Humlum and Vestergaard;
- AI inputs and firm effort: Babina et al.; Babina's measurement synthesis.

### Evidence dimensions

- availability stage;
- feature, workflow, product, and platform breadth;
- customer reach;
- active usage intensity;
- paid packaging and monetization;
- material revenue or retention evidence.

### Interpretation

A launch announcement is not broad deployment. Cross-product availability is not necessarily high user adoption. High user adoption is not necessarily material revenue.

---

## 27. Task-Specific Defensibility (TSD)

### Definition

The degree to which the focal product retains economically necessary advantages that the frontier alternative cannot readily replace for the specific customer task.

### Literature foundations

- complementary assets and appropriability: Teece; Azoulay et al.;
- switching costs and lock-in: Klemperer; Farrell and Klemperer; Shapiro and Varian;
- network and platform effects: Katz and Shapiro; Rochet and Tirole;
- ecosystems and bottlenecks: Adner and Kapoor;
- judgment and error costs: Agrawal et al.;
- technical reliability and execution: agent benchmarks.

### Candidate mechanisms

- necessary proprietary or licensed data;
- persistent customer/workflow state;
- permissions and authority;
- transaction execution;
- deep integrations;
- regulated status;
- specialized production engine;
- physical delivery;
- live expert or community participation;
- auditability, governance, and safety controls;
- installed-base, learning, migration, or network switching costs.

### Counterfactual discipline

Every claimed mechanism must answer:

> Does this asset materially improve or enable the required customer outcome, or is it merely an asset the firm possesses?

The presence of “100 million content items,” “proprietary AI,” or “enterprise-grade security” is not sufficient without task-level necessity.

---

## 28. Task Economic Importance (TEI)

### Definition

The importance of the task to the product's customer value proposition and, where observable, to the firm's commercial economics.

### Literature foundations

- core versus peripheral tasks in task-economy models;
- product-level innovation and demand stickiness: Argente et al.; Cohen et al.;
- product-market text: Hoberg and Phillips;
- innovation value: Bellstam et al.

### Evidence hierarchy

Potential evidence, from strongest to weaker:

1. directly disclosed product or segment revenue;
2. product-specific subscription/customer metrics;
3. explicit identification as the primary use case or core offering;
4. stable centrality across multiple official source types and years;
5. reviewer-coded core/major-supporting/peripheral role with evidence.

Word count, feature count, and marketing prominence should not be used mechanically as economic weights.

---

## 29. Task Transitions

### Definition

The longitudinal relation between a predecessor and successor task observation.

### Literature foundations

- automation and new tasks: Acemoglu and Restrepo;
- dynamic capabilities and architectural innovation;
- product entry and innovation: Argente et al.;
- task reorganization in early generative-AI adoption: Humlum and Vestergaard;
- longitudinal product-market text: Hoberg and Phillips.

### Analytical value

Transitions permit decomposition of firm change into:

- within-task delivery transformation;
- task entry;
- task exit;
- product reorganization;
- portfolio pivot;
- acquisition integration;
- change caused by frontier expansion versus change caused by firm response.

---

# Part XII — Proposed empirical propositions

## 30. Propositions, not frozen hypotheses

The following propositions organize descriptive analysis. They are not yet registered causal hypotheses.

### P1 — Direct-replicability pressure

Tasks whose underlying customer need can be satisfied directly by the dated frontier, without necessary product-specific systems or assets, face greater substitution pressure.

### P2 — Transformation is conditionally valuable

AI Transformation Depth is more likely to be associated with favorable outcomes when it is accompanied by task-specific defensibility and meaningful deployment scale.

### P3 — Deep but commoditized adaptation

When Frontier Task Replicability is high and Task-Specific Defensibility is low, deeper AI integration may represent defensive parity rather than durable advantage.

### P4 — Execution and orchestration can preserve a product layer

Products that connect frontier reasoning to persistent state, permissions, tools, transactions, governance, and exception handling may retain differentiation even when individual language or generation steps are highly replicable.

### P5 — Product-entry and task-entry effects matter

Firm adaptation occurs not only through modifying incumbent tasks but also through new products, new customer jobs, discontinued offerings, acquisitions, and portfolio pivots.

### P6 — Deployment mediates observed outcomes

A technically deep capability should have limited near-term economic association when it remains announced, beta, narrowly available, or weakly used.

### P7 — Economic effects may lag observable transformation

Product and task reconfiguration can precede financial effects because complementary investments and customer adoption take time.

### P8 — Source enrichment changes measurement

Item 1-only extraction is expected to recover major product families and tasks but under-detect exact actions, launch timing, agentic execution, commercialization, and within-year transitions relative to an enriched official corpus.

---

# Part XIII — Empirical design implications

## 31. Descriptive analysis is a primary contribution

Before causal analysis, the thesis can establish:

- annual product, capability, and task entry/exit rates;
- prevalence of assistance, generation, workflow integration, and orchestration;
- movement of tasks across dated frontier-replicability categories;
- distribution of deployment evidence;
- product and firm archetypes;
- transition matrices;
- task-level examples with evidence packets;
- source-coverage and source-ablation results;
- model and human agreement in extraction and measurement.

These outputs directly fill a gap between occupation-level exposure studies and firm-level adoption indicators.

## 32. Panel associations

Possible panel analyses include:

- product- or firm-fixed-effects models linking lagged transformation and scale to operational outcomes;
- interactions between FTR, AITD, DS, and TSD;
- decompositions separating within-task transformation from task entry and exit;
- heterogeneity by consumer versus enterprise product, workflow state, regulated execution, and task importance;
- lag structures consistent with the productivity J-curve.

These are associational unless a defensible identification strategy is established.

## 33. Event studies

Potential events include:

- first general availability of a major AI product;
- launch of a model platform or agent system;
- acquisition of a material AI capability;
- discontinuation or strategic pivot of an exposed product;
- frontier releases that sharply expand a specific task capability.

Event definition must be independent of the outcome and based on dated official evidence. Staggered-event estimators may be appropriate, but event timing and anticipation must be examined.

## 34. Difference-in-differences

Modern DiD literature remains relevant if a binary or staggered event is later defined:

- Callaway, B., & Sant'Anna, P. H. C. (2021). Difference-in-differences with multiple time periods. *Journal of Econometrics, 225*(2), 200–230.
- Sun, L., & Abraham, S. (2021). Estimating dynamic treatment effects in event studies with heterogeneous treatment effects. *Journal of Econometrics, 225*(2), 175–199.
- Roth, J., Sant'Anna, P. H. C., Bilinski, A., & Poe, J. (2023). What's trending in difference-in-differences? *Journal of Econometrics, 235*(2), 2218–2244.

However, the new thesis does not define all firms as treated on one date. Frontier capability, firm response, and deployment evolve at different times. A single ChatGPT launch dummy is unlikely to represent the full treatment process.

## 35. Post-treatment variables and causal interpretation

AI transformation and deployment after the frontier shock are endogenous firm responses. Conditioning on them can introduce post-treatment bias in a design seeking the total effect of initial exposure.

The thesis should therefore distinguish research questions:

1. **Descriptive response:** How did firms transform?
2. **Predictive association:** Which response profiles are associated with outcomes?
3. **Causal effect of initial exposure:** Requires pre-determined measures and separate design.
4. **Causal effect of adoption or launch:** Requires an exogenous source of timing or variation.

One dataset can support several questions, but the estimands must not be conflated.

---

# Part XIV — Validity threats and mitigation

## 36. Construct validity

### Threats

- product versus capability versus task confusion;
- task granularity instability;
- marketing language mistaken for functionality;
- “agent” labels without action evidence;
- generic assets mistaken for task-specific defensibility;
- activity counts mistaken for economic importance.

### Mitigation

- explicit ontology;
- separate extraction passes;
- inclusion/exclusion rules;
- evidence passages;
- gold and adversarial cases;
- reason-coded human adjudication;
- source triangulation;
- task-level counterfactual questions.

## 37. Temporal validity

### Threats

- using today's product page to describe 2023;
- assigning a later frontier capability to an earlier filing;
- retrospective management descriptions;
- unclear launch versus announcement date;
- model knowledge leaking future facts into classification.

### Mitigation

- immutable dated snapshots;
- publication-date and cutoff fields;
- dated frontier registry;
- source eligibility validator;
- prompts that prohibit external model knowledge;
- explicit availability status.

## 38. Source-selection bias

### Threats

- richer disclosure by large firms;
- incomplete web archives;
- marketing overstatement;
- underreporting of unsuccessful initiatives;
- investor-oriented emphasis in filings;
- documentation intensity correlated with firm quality.

### Mitigation

- source-coverage metrics;
- standardized discovery protocol;
- source-type indicators;
- Item 1-only versus enriched-corpus ablation;
- missingness categories;
- sensitivity analyses by source coverage;
- no silent imputation of missing deployment evidence.

## 39. Measurement-instrument drift

### Threats

- model upgrades;
- prompt edits;
- provider fallback;
- nondeterminism;
- schema changes;
- hidden context contamination.

### Mitigation

- immutable run manifests;
- prompt, model, schema, source, and code hashes;
- frozen eval suites;
- regression reports;
- versioned release decisions;
- no overwrite of old outputs;
- periodic dual-model or repeated-run reliability tests.

## 40. Outcome endogeneity

Successful firms may have more resources to adopt AI, better disclosure, and stronger complementary assets. Outcomes may drive product changes, not only result from them.

**Mitigation:** Careful temporal ordering, lag structures, pre-trend diagnostics, explicit causal limitations, and where feasible external variation or event-specific designs.

## 41. Survivor and selection bias

A 2022–2026 balanced panel may exclude bankruptcies, delistings, mergers, and firms with failed products—the very outcomes of interest.

**Mitigation:** Preserve entry/exit events, unbalanced panels, acquisition and delisting statuses, and reasons for missing observation years.

---

# Part XV — Research gap and intended contribution

## 42. What existing literature measures well

The literature provides strong measures of:

- occupational and worker-task exposure;
- realized user interaction with AI systems;
- firm AI inputs such as patents, talent, and investments;
- broad firm or worker adoption;
- productivity effects in selected tasks and settings;
- product-market similarity from annual filings;
- organizational complements and competitive moats.

## 43. What remains missing

There is limited large-sample evidence connecting, over time:

```text
firm products
→ concrete capabilities
→ customer-facing tasks
→ dated frontier alternatives
→ observed product transformation
→ deployment breadth
→ task-specific defensibility
→ product and firm outcomes
```

Occupation-based measures cannot distinguish firms with similar workers but very different customer outputs. Firm-level AI-adoption indicators cannot distinguish generic copilots from stateful execution platforms. Product pages alone cannot reliably establish scale or economic importance. Static exposure cannot observe endogenous redesign.

## 44. Intended contribution

The project aims to contribute:

1. **A new unit of analysis:** the dated firm-product-capability-task observation.
2. **A dynamic ontology:** explicit product, capability, task, customer need, and transition links.
3. **A multi-source official corpus:** SEC plus dated official product and technical evidence.
4. **A construct separation:** replicability, transformation depth, deployment scale, defensibility, and importance.
5. **A dated frontier design:** no future-capability leakage.
6. **An evidence-producing LLM measurement system:** every claim linked to source passages.
7. **A rigorous eval harness:** deterministic checks, gold sets, adversarial tests, regression control, and append-only adjudication.
8. **A longitudinal empirical map:** firm responses that include adaptation, commoditization, orchestration, task creation, discontinuation, and pivot.

The strongest contribution is not necessarily a single index. It may be the validated representation that makes several theoretically distinct measurements possible.

---

# Part XVI — Reading priorities

## 45. Essential core: read first

1. Autor, Levy, and Murnane (2003) — task framework.
2. Acemoglu and Restrepo (2018; 2019) — displacement and new tasks.
3. Bresnahan and Trajtenberg (1995) — general-purpose technology and co-invention.
4. Brynjolfsson and Hitt (2000) — organizational complements.
5. Brynjolfsson, Rock, and Syverson (2021) — productivity J-curve.
6. Teece (1986) — complementary assets and value capture.
7. Teece, Pisano, and Shuen (1997) — dynamic capabilities.
8. Eloundou et al. (2024) — LLM task exposure.
9. Hoberg and Phillips (2016) — dynamic product text from 10-Ks.
10. Azoulay, Krieger, and Nagaraj (2025) — generative AI and old moats.
11. Bonney et al. (2026) — adoption versus function versus task scope.
12. τ-bench / WorkArena / METR — operational limits of agentic execution.
13. Wang et al. (2024) and Chen et al. (2024) — LLM-evaluator bias.

## 46. Essential empirical interpretation

1. Babina et al. (2024) — firm AI and product innovation.
2. Brynjolfsson, Li, and Raymond (2025) — realized productivity.
3. Dell'Acqua et al. — jagged frontier.
4. Dillon et al. (2025) — productivity without major task-composition shift.
5. Humlum and Vestergaard (2026 revision) — task reorganization before aggregate outcomes.
6. Bick et al. (2024/2025) and Bonney et al. (2026) — diffusion and intensity.
7. Argente et al. (2025) — product innovation and firm dynamics.

## 47. Source and measurement design

1. Loughran and McDonald (2011).
2. Li (2010).
3. Bellstam et al. (2021).
4. *Signals of innovation online* (2026).
5. G-Eval and LLM-judge bias papers.

---

# Part XVII — Literature-to-repository crosswalk

## 48. Governing files by literature domain

| Literature domain | Repository file(s) informed |
|---|---|
| Task-based technological change | `docs/CONCEPTUAL_FRAMEWORK.md`; `docs/methodology/PRODUCT_CAPABILITY_TASK_ONTOLOGY.md` |
| Product and innovation dynamics | `specs/SPEC-008` through `SPEC-013`; longitudinal matching docs |
| Frontier task exposure | `specs/SPEC-014`; `SPEC-015`; frontier measurement prompt |
| AI transformation and agents | `SPEC-016`; AI transformation prompt; capability/task extraction fields |
| Diffusion and deployment | `SPEC-017`; source playbooks; scale evidence fields |
| Complementary assets and switching | `SPEC-018`; task-defensibility prompt |
| Corporate text and websites | `SOURCE_POLICY.md`; `TEMPORAL_POLICY.md`; `SPEC-002` through `SPEC-007` |
| LLM measurement validity | `evals/EVAL_HARNESS.md`; `SPEC-020` through `SPEC-025`; prompt change protocol |
| Outcomes and causal inference | `SPEC-019`; `SPEC-021`; analysis phase of the master notebook |

## 49. Decisions that literature does not settle

The following must be resolved empirically in the pilot rather than by citation alone:

- exact task-granularity rules;
- whether FTR should be categorical, continuous, or multi-dimensional;
- whether transformation depth is strictly ordinal;
- whether deployment dimensions should be combined;
- whether defensibility is one latent construct or a vector;
- how task economic importance should be weighted when revenue is unavailable;
- optimal source packet by firm-year;
- acceptable inter-reviewer and inter-model reliability thresholds;
- final firm universe and observation convention;
- whether a composite firm-level score adds information beyond the component profile;
- the appropriate downstream econometric design.

These decisions should be frozen only after sentinel cases and eval evidence.

---

# Part XVIII — Selected bibliography

The bibliography below prioritizes works directly relevant to the current thesis. Publication details should be checked against the final published version when the thesis is submitted.

## A. Tasks, automation, and technological change

- Acemoglu, D., & Restrepo, P. (2018). The race between man and machine. *American Economic Review, 108*(6), 1488–1542. DOI: 10.1257/aer.20160696.
- Acemoglu, D., & Restrepo, P. (2019). Automation and new tasks. *Journal of Economic Perspectives, 33*(2), 3–30. DOI: 10.1257/jep.33.2.3.
- Acemoglu, D., & Restrepo, P. (2022). Tasks, automation, and the rise in U.S. wage inequality. *Econometrica, 90*(5), 1973–2016.
- Autor, D. H. (2015). Why are there still so many jobs? *Journal of Economic Perspectives, 29*(3), 3–30.
- Autor, D. H., Levy, F., & Murnane, R. J. (2003). The skill content of recent technological change. *Quarterly Journal of Economics, 118*(4), 1279–1333.
- Brynjolfsson, E., & Mitchell, T. (2017). What can machine learning do? *Science, 358*(6370), 1530–1534.
- Brynjolfsson, E., Mitchell, T., & Rock, D. (2018). What can machines learn? *AEA Papers and Proceedings, 108*, 43–47.

## B. General-purpose technology, organization, and innovation

- Bresnahan, T. F., & Trajtenberg, M. (1995). General purpose technologies. *Journal of Econometrics, 65*(1), 83–108.
- Bresnahan, T. F., Greenstein, S., & Yin, P.-L. (2025). New economic forces behind the value distribution of innovation. NBER Working Paper 34090.
- Brynjolfsson, E., & Hitt, L. M. (2000). Beyond computation. *Journal of Economic Perspectives, 14*(4), 23–48.
- Brynjolfsson, E., Hitt, L. M., & Yang, S. (2002). Intangible assets: Computers and organizational capital. *Brookings Papers on Economic Activity*.
- Brynjolfsson, E., Rock, D., & Syverson, C. (2021). The productivity J-curve. *American Economic Journal: Macroeconomics, 13*(1), 333–372.
- Henderson, R. M., & Clark, K. B. (1990). Architectural innovation. *Administrative Science Quarterly, 35*(1), 9–30.
- Teece, D. J. (1986). Profiting from technological innovation. *Research Policy, 15*(6), 285–305.
- Teece, D. J., Pisano, G., & Shuen, A. (1997). Dynamic capabilities and strategic management. *Strategic Management Journal, 18*(7), 509–533.
- Tripsas, M., & Gavetti, G. (2000). Capabilities, cognition, and inertia. *Strategic Management Journal, 21*(10–11), 1147–1161.

## C. AI exposure and realized use

- Eloundou, T., Manning, S., Mishkin, P., & Rock, D. (2024). GPTs are GPTs. *Science, 384*(6702), 1306–1308.
- Felten, E. W., Raj, M., & Seamans, R. (2018). A method to link advances in AI to occupational abilities. *AEA Papers and Proceedings, 108*, 54–57.
- Felten, E. W., Raj, M., & Seamans, R. (2021). Occupational, industry, and geographic exposure to AI. *Strategic Management Journal, 42*(12), 2195–2217.
- Frey, C. B., & Osborne, M. A. (2017). The future of employment. *Technological Forecasting and Social Change, 114*, 254–280.
- Hampole, M., Papanikolaou, D., Schmidt, L. D. W., & Seegmiller, B. (2025). Artificial intelligence and the labor market. NBER Working Paper 33509.
- Pizzinelli, C., Panton, A. J., Tavares, M. M., Cazzaniga, M., & Li, L. (2023). Labor market exposure to AI. IMF Working Paper 2023/216.
- Tomlinson, K., Jaffe, S., Wang, W., Counts, S., & Suri, S. (2025). Working with AI: Measuring the applicability of generative AI to occupations. Microsoft Research.
- Webb, M. (2020). The impact of artificial intelligence on the labor market. Stanford working paper.
- Anthropic. (2025–2026). *Anthropic Economic Index* reports and public datasets.

## D. Firm adoption, productivity, and product innovation

- Babina, T., Fedyk, A., He, A. X., & Hodson, J. (2024). Artificial intelligence, firm growth, and product innovation. *Journal of Financial Economics, 151*, 103745.
- Bick, A., Blandin, A., & Deming, D. J. (2024/2025). The rapid adoption of generative AI. NBER Working Paper 32966.
- Bonney, K., Breaux, C. L., Dinlersoz, E., Foster, L. S., Haltiwanger, J. C., & Pande, A. A. (2026). The microstructure of AI diffusion. NBER Working Paper 35141.
- Brynjolfsson, E., Li, D., & Raymond, L. R. (2025). Generative AI at work. *Quarterly Journal of Economics*.
- Dell'Acqua, F., McFowland, E., Mollick, E. R., et al. Navigating the jagged technological frontier. HBS Working Paper 24-013.
- Dell'Acqua, F., Ayoubi, C., Lifshitz, H., et al. (2025). The cybernetic teammate. NBER Working Paper 33641.
- Dillon, E. W., Jaffe, S., Immorlica, N., & Stanton, C. T. (2025). Shifting work patterns with generative AI. NBER Working Paper 33795.
- Humlum, A., & Vestergaard, E. (2025/2026). Still waters, rapid currents. NBER Working Paper 33777.
- Noy, S., & Zhang, W. (2023). Experimental evidence on generative AI productivity. *Science, 381*(6654), 187–192.
- Peng, S., Kalliamvakou, E., Cihon, P., & Demirer, M. (2023). The impact of AI on developer productivity. arXiv:2302.06590.
- Yotzov, I., et al. (2026). Firm data on AI. NBER Working Paper 34836.
- Baslandze, S., et al. (2026). Artificial intelligence, productivity, and the workforce. NBER Working Paper 34984.
- Bick, A., Blandin, A., Deming, D. J., Fuchs-Schündeln, N., & Jessen, J. (2026). Mind the gap. NBER Working Paper 34995.

## E. Product innovation, corporate text, and source measurement

- Argente, D., Baslandze, S., Hanley, D., & Moreira, S. (2025). Patents to products. NBER Working Paper 34592.
- Bellstam, G., Bhagat, S., & Cookson, J. A. (2021). A text-based analysis of corporate innovation. *Management Science, 67*(7), 4004–4031.
- Cohen, W. M., Higgins, M. J., Miles, W. D., & Shibuya, Y. (2025/2026). Blockbusters, sequels and the nature of innovation. NBER Working Paper 33957.
- Hoberg, G., & Phillips, G. (2016). Text-based network industries and endogenous product differentiation. *Journal of Political Economy, 124*(5), 1423–1465.
- Li, F. (2010). The information content of forward-looking statements. *Journal of Accounting Research, 48*(5), 1049–1102.
- Loughran, T., & McDonald, B. (2011). When is a liability not a liability? *Journal of Finance, 66*(1), 35–65.
- *Signals of innovation online: Identifying innovative firms by combining website mining and evidence-producing LLMs.* (2026). *Technological Forecasting and Social Change, 228*, 124695.

## F. Competitive advantage, platforms, and ecosystems

- Adner, R., & Kapoor, R. (2010). Value creation in innovation ecosystems. *Strategic Management Journal, 31*(3), 306–333.
- Adner, R., & Kapoor, R. (2016). Innovation ecosystems and the pace of substitution. *Strategic Management Journal, 37*(4), 625–648.
- Agrawal, A., Gans, J., & Goldfarb, A. (2018). *Prediction Machines*. Harvard Business Review Press.
- Azoulay, P., Krieger, J. L., & Nagaraj, A. (2025). Old moats for new models. *Entrepreneurship and Innovation Policy and the Economy, 4*.
- Farrell, J., & Klemperer, P. (2007). Coordination and lock-in. *Handbook of Industrial Organization, Volume 3*.
- Katz, M. L., & Shapiro, C. (1985). Network externalities, competition, and compatibility. *American Economic Review, 75*(3), 424–440.
- Klemperer, P. (1987). Markets with consumer switching costs. *Quarterly Journal of Economics, 102*(2), 375–394.
- Klemperer, P. (1995). Competition when consumers have switching costs. *Review of Economic Studies, 62*(4), 515–539.
- Parker, G. G., & Van Alstyne, M. W. (2005). Two-sided network effects. *Management Science, 51*(10), 1494–1504.
- Rochet, J.-C., & Tirole, J. (2003). Platform competition in two-sided markets. *Journal of the European Economic Association, 1*(4), 990–1029.
- Shapiro, C., & Varian, H. R. (1999). *Information Rules*. Harvard Business School Press.

## G. Agents, execution, and frontier benchmarks

- Boisvert, L., Thakkar, M., Gasse, M., et al. (2024). WorkArena++. arXiv:2407.05291.
- Drouin, A., Gasse, M., Caccia, M., et al. (2024). WorkArena. arXiv:2403.07718.
- Kwa, T., West, B., Becker, J., et al. (2025). Measuring AI ability to complete long tasks. METR.
- Liu, X., Yu, H., Zhang, H., et al. (2023). AgentBench. arXiv:2308.03688.
- Xie, T., Zhang, D., Chen, J., et al. (2024). OSWorld. arXiv:2404.07972.
- Yao, S., Shinn, N., Razavi, P., & Narasimhan, K. (2024). τ-bench. arXiv:2406.12045.

## H. LLM-based evaluation and annotation

- Chen, G. H., Chen, S., Liu, Z., Jiang, F., & Wang, B. (2024). Humans or LLMs as the judge? *EMNLP 2024*.
- Koo, R., Lee, M., Raheja, V., et al. (2024). Benchmarking cognitive biases in LLMs as evaluators. *Findings of ACL 2024*.
- Liu, Y., Iter, D., Xu, Y., Wang, S., Xu, R., & Zhu, C. (2023). G-Eval. *EMNLP 2023*.
- Pan, Q., Ashktorab, Z., Desmond, M., et al. (2024). Human-centered design recommendations for LLM-as-a-judge. *HCI+NLP 2024*.
- Wang, P., Li, L., Chen, L., et al. (2024). Large language models are not fair evaluators. *ACL 2024*.
- Zhou, H., Huang, H., Long, Y., et al. (2024). Mitigating the bias of large language model evaluation. *CCL 2024*.

## I. Causal inference, if later required

- Callaway, B., & Sant'Anna, P. H. C. (2021). Difference-in-differences with multiple time periods. *Journal of Econometrics, 225*(2), 200–230.
- Roth, J., Sant'Anna, P. H. C., Bilinski, A., & Poe, J. (2023). What's trending in difference-in-differences? *Journal of Econometrics, 235*(2), 2218–2244.
- Sun, L., & Abraham, S. (2021). Estimating dynamic treatment effects in event studies. *Journal of Econometrics, 225*(2), 175–199.

---

# Part XIX — Maintenance protocol

## 50. Adding literature

A paper should be added only when it contributes to at least one of:

- construct definition;
- extraction or source design;
- dated frontier measurement;
- longitudinal matching;
- deployment or defensibility measurement;
- evaluation methodology;
- empirical interpretation;
- identification strategy.

Each new entry should record:

- publication status;
- stable bibliographic citation;
- main result;
- exact relevance to this thesis;
- limitations or tension with other evidence;
- repository decision, if any.

## 51. Avoiding citation overreach

The review must not state that a paper “validates” the thesis merely because it uses tasks, AI, firms, or text. Stronger language is appropriate only when the construct and empirical object match.

Examples:

- Worker-task productivity evidence supports the plausibility of frontier capability but does not validate product substitution.
- Firm-level AI hiring supports adoption measurement but does not validate customer-facing transformation.
- Product-page text supports capability discovery but does not establish deployment scale.
- Agent benchmark performance informs the frontier boundary but does not establish a specific commercial product's performance.
- A positive association between AI investment and growth does not imply every deep AI adoption is advantageous.

## 52. Review cadence

Because frontier benchmarks and firm-adoption evidence change rapidly:

- review dated frontier and agent literature before every measurement release;
- review firm-adoption evidence at least quarterly during active thesis development;
- freeze a bibliographic snapshot for each thesis draft;
- distinguish publication date from the version date actually used;
- never update a historical frontier score silently when a benchmark is revised.

---

## Closing synthesis

The literature does not support a simple theory in which firms with more AI wording or more AI features are winners. It supports a layered model.

Foundation models expand a common capability frontier. That expansion directly threatens some customer-facing information tasks, complements others, and creates new downstream opportunities. Firms respond through product redesign, organizational co-invention, workflow integration, commercialization, and portfolio change. Their ability to capture value depends on deployment and on task-specific complementary assets, authority, integration, reliability, and switching friction. These responses and effects unfold over time and are imperfectly reported across different official sources.

Accordingly, the thesis should not ask only:

> How exposed was the firm?

It should ask:

> Which customer tasks did the firm supply, what could the dated frontier do directly, how did the firm change the product-task architecture, how broadly was the change deployed, what necessary differentiation remained, and what happened next?

That sequence is the conceptual foundation of the repository's data model, extraction pipeline, measurement framework, eval harness, and later empirical analysis.
