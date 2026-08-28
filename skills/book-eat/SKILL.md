---
name: book-eat
description: "Deep-digest a book into a permanent, page-cited knowledge base — text is taken from the source directly whenever present (text layer / structural unpack); vision reading is the fallback for scanned pages; every page is archived (figure/table presence + bbox + full text) (figure/table presence + bbox + full text). Tiered close reading (deep notes + summaries behind an outline confirmation gate), topic archiving, glossary building, spaced-repetition review cards, figure harvesting driven by the archive's bboxes, and a resumable state machine. Use when the user says 'eat this book' / 'process this book', drops a new PDF/EPUB into sources/, asks to resume or check a book's processing status, or wants structured book notes built."
---

# Book Eat v2 · extraction-first pipeline (2026-08-28)

Extraction first: the text comes from the source directly (text layer, structural
unpack) whenever present; vision reading is reserved for scanned pages and for figure/table
judgment. The per-page archive produced by `tools/book_parse.py` (canonical PROMPT embedded —
prompt changes require user sign-off) is the truth for what each page contains. (`tools/book_parse.py`, canonical PROMPT embedded — prompt
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

## ① Parse (full-book archive) — extraction first, vision fallback

| source | text | figure/table |
|---|---|---|
| **Native PDF** (text layer) | extract from the text layer directly | render pages → visual pass judges presence & bboxes |
| **Scanned PDF** (no text layer) | vision transcription IS the text source | same visual pass |
| **EPUB** | structural unpack: spine XHTML → chapter text | embedded media extracted whole to `book-parse/media/` (chapter-anchored, no page semantics) |

- Scanned path: `book_parse render` (serial, dpi100) → `book_parse prompts` prints per-shard
  agent briefs → one Read-only agent per shard (presence + bbox + full text) → `merge`
  (validates continuity/fields).
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

- Extraction first, vision fallback (rule 1). No OCR tools anywhere; OCR history stays deleted.
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
