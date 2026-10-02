# Myth v0.5 workspace design

The product starts with a conversation. Sessions, projects, knowledge and model settings each have a working page. A user can ask a normal question before associating files.

## Visual system

- Graphite navigation, a cool light canvas, white work surfaces and one muted violet accent.
- Sans typography with a clear heading/body/metadata hierarchy; mono is reserved for code and file evidence.
- An original CSS orbital mark, generous spacing and four practical starters in the welcome view.
- A bounded reading column, floating composer, quiet source links, collapsed tool records and concrete downloads.
- Project cards, file panels, session rows and knowledge statistics share spacing, corner and border rules.
- Mobile navigation drawer and single-column pages; reduced-motion rules disable animations.
- Native HTML/CSS/JS, system fonts and original SVG icons; no remote assets or build dependencies.

## Interaction

The URL hash identifies a page/session. Reload restores viewing without submitting a message. Polling retains an unchanged thread, scroll position and open tool records. Replies from an older chat request cannot replace the current selection. Failed submissions retain identity for an unchanged message.

Dialogs implement project/session editing and knowledge import without browser prompts. Model/file text uses textContent and a limited Markdown renderer. Project roots are user configuration; file results are local copies. Conversation completion, source availability and file generation are distinct UI facts.

Source previews retain archived documents for historical references. Removing a document from the index excludes new retrieval without erasing its old source. Answer Markdown exports and immutable artifacts serve different content and are labeled separately.

## Reference study

The implementation is original code. The supplied [video-shotcraft](https://github.com/Vincentwei1021/video-shotcraft), [gc-minimal-zine-poster](https://github.com/LiamGvchi/gc-minimal-zine-poster), [frontend-slides](https://github.com/zarazhangrui/frontend-slides), [GSAP](https://github.com/greensock/GSAP) and [lieflat-charts](https://github.com/larashero3-dotcom/lieflat-charts) informed restrained contrast, negative space, readable hierarchy and motion. No templates or dependencies were copied.

## Validation boundary

Browser checks cover desktop/mobile navigation, project creation, knowledge import, real model conversation, file download, session search/edit/archive/restore and reload. Complete accessibility and cross-browser audits remain planned; see [validation](VALIDATION.md).
