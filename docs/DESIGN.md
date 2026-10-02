# Myth v0.4 workspace design

The workspace leads with a task and its completion criteria. Runtime details are available in an execution record panel. The user can try a complete local task before configuring a model.

## Visual system

- Warm paper, near-black ink, one muted terracotta accent; green denotes verified delivery.
- Serif intent/outcome headings, sans controls, mono file identities and accounting.
- Desktop: history / task / execution record. Tablet: optional record drawer. Mobile: compact navigation, expandable history, full-width task and record drawer.
- Short transform/opacity reveals; reduced-motion preference disables motion.
- System fonts, native CSS/JS, no build step or remote dependencies.

## Interaction rules

Submission fixes files and exact rules; model settings are folded into a secondary disclosure. The running view exposes status, progress, a question form when clarification is needed, stop/continue controls and verified downloads. Event details stay optional.

Refresh restores the selected run from the URL without resubmitting. Unchanged timelines are not rebuilt on each poll, so scrolling and expanded evidence stay stable. Failed submission retries reuse an entry identity until payload changes. Async responses cannot replace a newer selected run. File/model text uses DOM `textContent`, never generated HTML.

## Reference study

The code is original Myth UI; no source/templates were copied. References informed these design choices:

| Reference | Applied principle |
| --- | --- |
| [video-shotcraft](https://github.com/Vincentwei1021/video-shotcraft) | ink/paper contrast, one accent and restrained timing |
| [gc-minimal-zine-poster](https://github.com/LiamGvchi/gc-minimal-zine-poster) | negative space, editorial annotations and focal hierarchy |
| [frontend-slides](https://github.com/zarazhangrui/frontend-slides) | serif/sans/mono separation and transform/opacity reveals |
| [GSAP](https://github.com/greensock/GSAP) | easing and semantic sequencing; no GSAP dependency introduced |
| [lieflat-charts](https://github.com/larashero3-dotcom/lieflat-charts) | compact monochrome metrics with honest reserved/unknown usage |

## Validation boundary

Desktop and mobile browser checks cover the local demo, delivery display, run selection across refresh and drawers. Keyboard focus styling and reduced-motion rules are implemented; a complete assistive-technology audit and browser matrix remain future work. See [validation](VALIDATION.md).
