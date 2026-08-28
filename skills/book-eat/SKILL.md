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
book-content/
  books/<book>/
    book-parse/              TRUTH SOURCE (per-page / per-chapter archive)
      pages.jsonl            PDF: {page, book_page, is_toc, toc, has_figure, has_table, regions[bbox%], text}
      chapters.jsonl         chapter table: {title, print_page, pdf_page, end_pdf_page, verified}
      media/                 EPUB embedded media (extracted, unregistered until harvest)
    img/                     cropped figures actually harvested (+ 图录.json manifest)
    chapter-<slug>-<NN>-<标题>.md   chapter page (publish unit)
    精读-*.md 摘要-*.md README.md 学习进度.md
site/
  build_html.py · publish_web.sh · home/ · theme/ · assets/
  dist/                       generated site (gitignored in the private repo)
tools/                       book_parse etc.
sources/                     book files (PDF/EPUB) — local only, gitignored
```

Publish resolves each `src="img/…"` in a chapter page directly from
`book-content/books/<book>/img/`; a missing file blocks publish (that is a guard, not a bug).

## Tools

`tools/book_parse.py` — render / prompts / merge / chapters / crop (canonical)

Tool status (do NOT resurrect without user sign-off):

| tool | status |
|---|---|
| book_parse.py | **current** — parse + harvest pipeline |
| pages_probe.py | optional pre-filter only; never a completeness witness |
| extract_figures.py | legacy (private library); superseded by `book_parse crop` |
| run_ocr.py · quote_check.py · check_source.py | **retired** with OCR (2026-08-28) |
| fig_coverage_lint.py · audit_library.py | inoperative post-purge (they read books/*/ocr/); kept for history |

Private-library layout note: the host library may nest the pipeline under a content dir
(e.g. `book-content/books/<book>`, generators under `site/`); run book_parse from the
directory that owns `books/` so relative paths resolve.

## Stage × tool map

| stage | tool / command | output |
|---|---|---|
| ① parse · render | `book_parse render <book> [--pdf src]`（EPUB 自动走结构化分支） | page renders / `chapters.jsonl` + `media/` |
| ① parse · vision read | `book_parse prompts <book>` prints shard briefs → spawn one Read-only agent per shard | shard JSONL files (Write to disk, never chat-only) |
| ① parse · merge | `book_parse merge <book> --round A --dir <shards>`（自动附章节解析） | `book-parse/pages.jsonl` + `chapters.jsonl` |
| ② outline | ⛔ human confirmation gate — no tool | confirmed tier plan |
| ③–⑤ write & harvest | write 精读/摘要/章节 md；`book_parse crop <book>`（archive bbox → `img/` + 图录.json） | notes / chapter pages / figures |
| ⑥ build & publish | `site/build_html.py` → `site/publish_web.sh`（missing figure = fail） | live site, then proxy-verify 200 |
| audit (aux) | `pages_probe.py` pre-filter · overlay eyeball | flagged pages only |

## Step 0 · State detection (every invocation)

| book-content/books/<book>/book-parse/ | book-content/books/<book>/chapter-*.md | state |
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

Propose a tiered reading plan (deep-read chapters / summarize / skip) + chapter outline.
STOP. Do not write a single note until the user confirms the tiers.

## ③④⑤ Close reading → archiving → cards

- Write 精读/摘要/chapter notes; every quotation is copied from the book-parse archive text.
  If it is not in the archive, it may not be quoted — mark ⚠未验证 instead.
- Figures: harvest via `book_parse crop` (archive bbox → img/ + 图录.json). A table with
  embedded woodcuts yields ONE table frame — inner tiles are never individually boxed.
  Chapter pages embed `img/<slug>-…`; a missing file blocks publish (strong linkage check).
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
