# Software Universe Classifier — Item 1 Product Gate

Using only the firm's baseline Item 1, make two firm-level judgements in this
order.

## 1. Customer-facing digital product

Decide whether Item 1 establishes that the firm currently sells, licenses,
subscribes customers to, or deploys for customers a separately identifiable
digital or software product.

Return `YES` only when an external customer, user, client, consumer, merchant,
developer, or partner can obtain that product from the firm. Return `NO` when
Item 1 establishes a primarily non-digital business and does not establish such
a product. Return `UNKNOWN` when Item 1 does not resolve the question.

A digital sales channel or website, an internal system, third-party
infrastructure, technology used only to deliver a physical product or a
human-delivered service, and embedded software are not themselves a
customer-facing digital product.

## 2. Software centrality

Decide centrality only if `customer_facing_digital_product` is `YES`. If it is
`NO` or `UNKNOWN`, return `UNKNOWN` for `software_centrality`.

- `CORE` — customers principally acquire the digital or software product.
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
