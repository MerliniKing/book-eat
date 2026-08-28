---
name: book-eat
description: "Deep-digest a book into a permanent, page-cited knowledge base — the AI reads the whole book by direct vision (no OCR anywhere) and archives a per-page parse (figure/table presence + bbox + full text). Tiered close reading (deep notes + summaries behind an outline confirmation gate), topic archiving, glossary building, spaced-repetition review cards, figure harvesting driven by the archive's bboxes, and a resumable state machine. Use when the user says 'eat this book' / 'process this book', drops a new PDF/EPUB into sources/, asks to resume or check a book's processing status, or wants structured book notes built."
---

# Book Eat v2 · vision-first pipeline (2026-08-28)

OCR is retired. The book's text AND page-layout truth is a per-page archive produced by
direct multimodal reading (`tools/book_parse.py`, canonical PROMPT embedded — prompt
changes require user sign-off). Nothing else is a completeness witness.

## Library layout

```
sources/                     book files (PDF/EPUB) — local only, gitignored
books/<book>/
  book-parse/                TRUTH SOURCE (per-page or per-chapter archive)
    pages.jsonl              PDF: {page, has_figure, has_table, regions[bbox%], text}
    chapters.jsonl           EPUB: {chapter, href, title, text, media[]}
    media/                   EPUB embedded media (extracted, unregistered until harvest)
  img/                       cropped figures actually harvested (+ 图录.json manifest)
  精读-*.md 摘要-*.md lesson-*.md README.md 学习进度.md
html/                        generated site (build_html.py) — html/img staging is ABOLISHED;
                             publish resolves each src="img/…" directly from books/<book>/img/
```

## Tools

`tools/book_parse.py` — render / prompts / merge / crop
`tools/build_html.py`, `tools/publish_web.sh` — site build & publish (missing figure = publish fails; that is a guard, not a bug)

## Step 0 · State detection (every invocation)

| books/<book>/book-parse/ | books/<book>/lesson-*.md | state |
|---|---|---|
| absent | absent | fresh → ① |
| present | absent | parsed → ② outline gate |
| present | present | reading/publishing → ③–⑥ |
| partially filled | any | interrupted merge → `book_parse merge` to resume |

## ① Parse (full-book archive)

- **Scanned PDF**: `book_parse render` (serial, dpi100) → `book_parse prompts` prints per-shard
  agent briefs → spawn one Read-only agent per shard (each page: presence + bbox + full text
  transcription) → `book_parse merge` (validates continuity/fields, auto-fixes quoting).
- **Native PDF**: same, but body text comes from the text layer; the visual pass judges
  figure/table presence & bboxes only.
- **EPUB**: `book_parse render` unpacks structurally — chapter text from spine XHTML,
  embedded media extracted whole to `book-parse/media/` (no page semantics; media anchor to
  chapters). No visual transcription needed; optional visual pass on media on demand.
- Acceptance: merge reports continuity; eyeball the bbox overlay of a few pages before
  calling the archive done.

## ② Outline → ⛔ confirmation gate

Propose a tiered reading plan (deep-read chapters / summarize / skip) + lesson outline.
STOP. Do not write a single note until the user confirms the tiers.

## ③④⑤ Close reading → archiving → cards

- Write 精读/摘要/lesson notes; every quotation is copied from the book-parse archive text.
  If it is not in the archive, it may not be quoted — mark ⚠未验证 instead.
- Figures: harvest via `book_parse crop` (archive bbox → img/ + 图录.json). A table with
  embedded woodcuts yields ONE table frame — inner tiles are never individually boxed.
  Lesson embeds `img/<slug>-…`; a missing file blocks publish (strong linkage check).
- Cards to cards/*.md with source + difficulty + review ladder.

## ⑥ Kanban & publish

学习进度.md is the progress ledger (read-marker harvest from CF KV via mihomo proxy
127.0.0.1:7890). Publish via publish_web.sh; verify through the proxy afterwards
(mandatory global rule): expect HTTP 200 on changed URLs after the Workers build window.

## Hard rules

- No OCR anywhere. No text-vs-OCR similarity metrics. OCR history stays deleted.
- One canonical PROMPT (inside book_parse.py). No A/B/C prompt rounds; no pixel-probe
  completeness claims. The archive is the only presence witness.
- Absence claims ("no figures", "fully covered") are forbidden in notes — state what was
  parsed and where, and let the archive speak.
- Decorative ornaments (page-tail flourishes, seals) are not figures.

## Red Flags (stop and self-check)

- "I remember this passage" — quoting from memory instead of the archive (P0 class).
- Announcing harvest completeness without the archive diff.
- Third-party vision tools as final acceptors (they misjudge; direct Read is the acceptor).
- Sharded agents delivering to chat only (must Write the shard file; merge validates).
- EPUB media treated as page-anchored (it has no page semantics).

## Maintenance

PROMPT / pipeline changes require user confirmation, then commit in the open repo
(github.com/MerliniKing/book-eat); private libraries symlink to it. Legacy OCR-era
artifacts were purged 2026-08-28 (recoverable at git 34e6842^ if ever needed).
