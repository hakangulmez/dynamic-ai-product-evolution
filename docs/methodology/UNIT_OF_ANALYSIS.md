# Unit of Analysis

## Primary unit

```text
firm × observation date × product × capability × customer-facing task
```

## Why not firm-year only?

Firms contain heterogeneous products. A creative engine, document assistant, marketing platform, and infrastructure product may respond differently to frontier models.

## Why capability between product and task?

A capability is the product function; a task is the customer's economic job. One capability may support several tasks, and the same task may be supported by several capabilities.

## Optional lower level

Subtasks are not a mandatory entity. Use `task_components` only when a task contains materially different actions required for later measurement. Avoid domain or format proliferation.

## Longitudinal unit

Task observations are linked through transition records rather than mutating one row over time.
