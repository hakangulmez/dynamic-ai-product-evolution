# Software Universe Classifier — Item 1 Product Gate

Using only the firm's baseline Item 1, make two firm-level judgements in this
order.

## 1. Customer-facing software product

Decide whether Item 1 establishes that the firm currently sells, licenses,
subscribes customers to, or deploys for customers a separately identifiable
software product or software platform.

Before returning `YES`, apply both required tests silently:

1. **Purchase-object test.** Identify the object an external customer contracts
   to obtain. It must be the software product or platform itself, rather than a
   good, financial product, content, transaction, rental, or human service.
2. **Explicit-commercialization test.** Item 1 must directly establish that
   this software itself is sold, licensed, subscribed to, or deployed for the
   external customer as the identified commercial product.

Return `YES` only when both tests pass. If either test does not pass, return
`NO` when Item 1 resolves a non-software business, otherwise `UNKNOWN`.
Words such as digital, platform, cloud, technology, online, or solution do not
by themselves pass either test.

A website, online catalogue, customer account, online ordering or transaction
channel is not itself a software product. Neither are internal systems, embedded
software, third-party technology, or software merely used to deliver a physical
product or human-delivered service. A managed service, consulting engagement,
implementation, integration, outsourcing, or staff-led operation is not a
software product merely because it uses software, cloud infrastructure, data,
or AI.

## 2. Software centrality

Decide centrality only if `customer_facing_digital_product` is `YES`. If it is
`NO` or `UNKNOWN`, return `UNKNOWN` for `software_centrality`.

- `CORE` — customers principally acquire the software product or platform
  itself at the consolidated-firm level.
- `CO_ESSENTIAL` — the customer's outcome requires the digital product and a
  distinct non-software component together.
- `ENABLING` — the distinct digital product supports or extends a principally
  physical or human-delivered customer outcome.
- `PERIPHERAL` — the distinct digital product is ancillary to the customer's
  principal product experience.
- `UNKNOWN` — Item 1 does not resolve centrality.

## Confidence and evidence addresses

Return `high` only where Item 1 directly resolves the judgement; return
`medium` for a meaningful boundary judgement; otherwise return `low`.

The displayed Item 1 blocks have references such as `P001`. Return zero to
three shared `passage_refs` supporting the two judgements. If either conclusion
is not `UNKNOWN`, return at least one reference. Return an empty array only
when both conclusions are `UNKNOWN`.

Select addresses only. Do not write quotes, evidence text, explanations,
product lists, capabilities, tasks, a Tier, offsets, hashes, or fields not shown
below.

## Output

Return valid JSON only:

```json
{
  "customer_facing_digital_product": "YES | NO | UNKNOWN",
  "software_centrality": "CORE | CO_ESSENTIAL | ENABLING | PERIPHERAL | UNKNOWN",
  "confidence": "high | medium | low",
  "passage_refs": ["P001", "P002"]
}
```
