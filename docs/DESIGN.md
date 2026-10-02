# Myth v0.7 Product Design

## Product identity

Myth is not a knowledge-base SaaS with an AI chat panel. It is an **Agent Workbench** where users can see how intent becomes execution evidence.

The product identity comes from one causal chain:

```text
Intent → Decision → Authority → Result → Completion
```

The primary screen is the work surface, not a marketing hero.

## Visual system

### Color

- Paper `#F6F2EA` — application canvas.
- Surface `#FCFAF6` — composer, panels and controlled elevation.
- Ink `#25231F` — primary structure and high-confidence controls.
- Muted `#7C756A` — secondary information.
- Signal Orange `#C77732` — running state, selected authority and execution cut-points only.
- Success `#5E7A63` — completed / durable positive state.

Orange is not a decorative wash. Runtime state earns the accent.

### Type

- System Sans: navigation, conversation, controls and body copy.
- Georgia / Noto Serif SC fallback: task headline and major page title only.
- Monospace: runtime meters, IDs and machine facts only.

## Information architecture

```text
History / Context | Conversation / Task | Runtime Inspector
```

- Conversation stays central.
- Projects, Knowledge and Session Management are secondary context surfaces.
- Runtime is visible but does not compete with the task.
- Model state remains close to the active conversation.

## Signature move: Execution Spine

The Runtime Inspector is the one memorable visual device. It shows causality instead of presenting a dashboard full of identical cards.

Current projection:

```text
Decision
   │
Authority
   │
Result
   │
Completion
```

v0.7 only renders facts already exposed by the conversation API. It does **not** invent Ticket IDs, Receipts or semantic verification that are not present in the API. As deeper durable facts become available, the same layout can evolve into:

```text
Action → Attempt → Ticket → Receipt → Verification
```

## State design

Distinct states exist for idle, running, waiting for user, completed, failed/cancelled, unknown/recovering and budget exhausted.

UNKNOWN is amber/brown and is not collapsed into failure red.

## CSS rule

v0.7 replaces the visual system at the source. Do not append another “final refinement override” layer. Tokens, layout primitives and component rules must be edited directly.

## Accessibility floor

- visible keyboard focus;
- usable touch targets;
- readable metadata;
- `prefers-reduced-motion` support;
- mobile collapses navigation and hides the inspector instead of squeezing three columns;
- no critical meaning is conveyed by color alone.
