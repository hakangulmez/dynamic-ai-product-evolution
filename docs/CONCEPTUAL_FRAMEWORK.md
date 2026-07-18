# Conceptual Framework

## Core distinction

The project separates three questions that are often conflated:

1. **Can the frontier model do the customer's job?**
2. **How deeply did the firm transform the product with AI?**
3. **Did that transformation create durable differentiation?**

A firm can score high on transformation while remaining highly vulnerable if the underlying job is directly available from a general-purpose model at low switching cost.

## Dynamic task model

For task `i`, firm `f`, and observation date `t`:

```text
Customer need
  → focal product capability
  → task delivery mode
  → frontier alternative at date t
  → firm response and resulting differentiation
```

## Construct families

### Frontier Task Replicability

The degree to which the dated frontier system can satisfy the underlying customer need without the focal product.

### AI Transformation Depth

The degree to which AI changes the task from assistance to generation, workflow integration, action execution, or orchestration.

### Deployment Scale

The breadth and commercial reality of the transformation across availability, workflows, products, customers, and monetization.

### Task-Specific Defensibility

The degree to which the transformed product retains necessary advantages that the frontier alternative cannot readily replace.

### Task Economic Importance

The importance of the task to the product's customer value proposition. Importance is not assumed from the number of words or named features.

## Why adoption is not advantage by definition

Consider two stylized tasks.

### Direct-answer task

```text
Question → general-purpose model → answer
```

A firm may add conversational AI, domain prompts, and proprietary content. If customers can obtain equal or better answers directly from a frontier model with minimal switching friction, deep adoption may remain commoditized.

### Workflow-execution task

```text
Goal → plan → retrieve enterprise context → call tools → update records → execute → monitor exceptions
```

Here, integration with workflow state, permissions, tools, and execution can create a differentiated product layer even if a frontier model supplies reasoning or language generation.

## Provisional two-dimensional interpretation

| Frontier replicability | AI transformation | Interpretation |
|---|---|---|
| High | Low | Exposed and slow to respond |
| High | High | Adapted, but possibly commoditized |
| Low | High | Deeply transformed and potentially differentiated |
| Low | Low | Protected, stagnant, or not yet affected |

Defensibility and scale are required to refine these categories.

## No single-score commitment

The repository preserves the component observations. Derived indices may be introduced only after pilot validation. Multiple measures may coexist if they represent distinct constructs.
