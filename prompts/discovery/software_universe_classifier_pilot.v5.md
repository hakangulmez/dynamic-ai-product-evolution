# Software Universe Classifier — Item 1 Product Gate

Using only the firm's baseline Item 1, make two firm-level judgements in this
order.

## 1. Customer-facing digital product

Decide whether Item 1 establishes that the firm currently sells, licenses,
subscribes customers to, or deploys for customers a separately identifiable
digital or software product.

Return `YES` only if Item 1 establishes that an external customer obtains the
digital functionality itself as a separately identifiable product, rather than
merely using it to access, sell, rent, pay for, or operate a non-digital product
or human-delivered service.

Return `NO` when Item 1 establishes a primarily non-digital business and does
not establish such a product. Return `UNKNOWN` when Item 1 does not resolve the
question.

A website, online catalogue, customer account, online ordering or transaction
channel is not itself a digital product. Neither is a market, exchange, payment
rail, supplier, franchise, partner, or other third party's technology merely
used in the firm's business. Internal systems, technology used only to deliver a
physical product or human-delivered service, and embedded software are not
themselves customer-facing digital products.

## 2. Software centrality

Decide centrality only if `customer_facing_digital_product` is `YES`. If it is
`NO` or `UNKNOWN`, return `UNKNOWN` for `software_centrality`.

- `CORE` — use only when Item 1 establishes that, at the consolidated-firm
  level, customers principally acquire a separately identifiable digital or
  software product. It is not enough that the firm has a software segment,
  subsidiary, acquisition, technical capability, or digital channel. It is also
  not enough that software accompanies a physical product or human-delivered
  service. If Item 1 establishes a digital product but not that it is the
  firm's principal commercial offering, do not use `CORE`.
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
