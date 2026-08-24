---
name: book-eat
description: "Deep-digest a book into a permanent, page-cited knowledge base — the AI reads the whole book so you learn from distilled notes instead of raw text. Full-text caching (text-layer extraction or OCR for scanned PDFs), tiered close reading (deep notes + summaries behind an outline confirmation gate), topic archiving, glossary building, spaced-repetition review cards, and a resumable six-step state machine. Use when the user says 'eat this book' / 'process this book', drops a new PDF/EPUB into sources/, asks to resume or check a book's processing status, or wants structured book notes built. Triggers: book digest, ingest book, deep reading, book summary, knowledge base, book notes."
---

# book-eat · Digest a Book

Six-step pipeline orchestrator: ① full-text cache → ② outline → ③ close reading → ④ archiving → ⑤ cards → ⑥ kanban & publish.
**Reentrant state machine**: any later invocation on the same book resumes from the breakpoint — never redoes finished work.
Working directory: always the **library root** (the repository that owns `sources/`).

## Library layout & bootstrap

Expected layout (created automatically in Step 0 if missing):

```
sources/            drop new books here (.pdf / .epub)
books/<book>/ocr/   pages/  full.txt  toc.txt  quality_report.txt   ← raw machine layer, never rewritten
books/<book>/       README.md (outline & tiering), deep notes, summaries
topics/<area>/      topic notes — area dirs are created on demand, never pre-set
cards/              review cards (Q/A)
INDEX.md            progress kanban
```

Bootstrap rules (Step 0, before anything else):
- `tools/run_ocr.py` missing at library root → copy it from this skill's `tools/` directory
- `sources/ books/ cards/ topics/` or `INDEX.md` missing → create them; seed `INDEX.md` from `scaffold/INDEX-template.md`
- library `CLAUDE.md` missing the knowledge spec → append `scaffold/CLAUDE-snippet.md`

## Step 0 · State detection (every invocation)

| Current state | Next |
|---|---|
| `sources/` has a new book (.pdf/.epub) and `books/` has no directory for it | Phase ① |
| `books/<book>/ocr/full.txt` missing or incomplete | resume ① |
| no `books/<book>/README.md` (outline) | Phase ② |
| outline exists but the tiering table was never confirmed by the user | **⛔ confirmation gate** |
| deep/summary notes incomplete (vs tiering table) | Phases ③④⑤ |
| pipeline all green but `html/` not republished | Phase ⑥ |

Multiple books present or title ambiguous → list `sources/` and the INDEX kanban, let the user choose.

## ① Full-text cache

```bash
timeout 480 python3 tools/run_ocr.py <book-name> sources/<pdf-or-epub>   # rerun until it prints DONE
```

- Supports **.pdf / .epub** only; other formats (mobi/azw3/djvu…) are rejected with a clear error → convert to epub/pdf first
- Auto-detection: text layer present → direct extraction (seconds); otherwise RapidOCR (~8 s/page; EPUB synthetic pages follow the same path)
- **Long background tasks get killed (~10 min on some hosts): always run in `timeout` chunks** — resumable, finished pages are skipped automatically
- Artifacts: `pages/` per-page text, `full.txt` with page markers, `toc.txt` (TOC → start page; junk bookmarks auto-discarded), `quality_report.txt` (OCR path only)
- Page markers: `===== PDF page N =====` / `===== EPUB page N · <chapter> =====` (EPUB synthetic page numbers are deterministic per book)
- When done, read `quality_report.txt` → flag low-confidence pages as visual-verification candidates

## ② Outline → ⛔ confirmation gate

1. Skim `full.txt` in chunks (with `toc.txt`); classify the book: modern → tiered processing / classic (ancient text) → four-layer annotation
2. Write `books/<book>/README.md`: metadata, whole-book outline, **chapter tiering table** (deep-read core / summary / skip), relation to the library's roadmap if one exists
3. Update the INDEX kanban for ①② → commit + push
4. **⛔ REQUIRED STOP: present the tiering table to the user and explicitly wait for confirmation or adjustment. Without it, phases ③④⑤⑥ are forbidden.**

> Why stop: tiering is an editorial judgment that determines all downstream work; getting it wrong means redoing everything.
>
> | Routine excuse | Reality |
>---|---|
> | "the convention implies it, no need to ask" | how many deep notes and which chapters to skip cannot be derived from convention — it is an editorial call |
> | "interrupting once isn't worth it" | one interruption buys direction approval for the whole book — cheapest insurance there is |
> | "finish first, review together" | finishing means the entire token budget and commit history are already spent; rework is the most expensive outcome |

## ③④⑤ Close reading → archiving → cards

- Produce `deep-NN` / `summary-NN` notes **strictly per the confirmed tiering table**; for large books across sessions, commit+push and update INDEX after every 1–2 notes
- **Quality gate**: quotations, factual data (dates/names/editions), tables, and plates → verify against the original page image
  - an image-capable tool available (vision MCP etc.) → AI checks the page images directly
  - none available → still emit the quotation/low-confidence page list marked **⚠ needs human review**; never silently skip verification
- Archive into the matching `topics/<area>/`, backfill book evidence (upgrade `⚠unverified` → verified), extend the glossary, create cards in `cards/` (with difficulty 1–5)

## ⑥ Kanban & optional publish

- INDEX all green → commit + push
- Publishing (optional, **library-defined**): if the library root provides `tools/publish.sh`, run it here — that script is yours to write (HTML build, deploy, whatever your setup needs); document its actual behavior in the library's own CLAUDE.md. No such script → Step ⑥ ends at the INDEX commit

## Knowledge spec (binding for all writing)

- **Sourcing**: every claim carries its origin (book + page, or book + chapter). Synthetic EPUB page numbers are reproducible per book, so page citations stay stable
- Claude's general knowledge not yet backed by the book → mark **⚠unverified**; backfill when the evidence is read
- Topic-note four-piece: plain-language definition → source → `[[related terms]]` → confusion discrimination (易混辨析)
- Classics (ancient texts with commentary): four-layer annotation per chapter — ① original passage ② modern translation ③ textual criticism (editions/readings/facts; doubts marked ⚠) ④ interpretation (intellectual lineage and influence). Modern books → tiered (deep / summary / skip)
- Review cards: Q/A + source + difficulty 1–5 + status
- Blind spots that recur across Q&A sessions → capture them in `faq/`
- `ocr/full.txt` is the raw machine-output layer — **never rewrite it**; corrections live only in note layers, keeping the audit trail intact

## Hard rules

- Never rewrite the OCR cache; revisions land in note layers only
- Commit + push at the end of every phase
- Book source files and OCR caches may be copyrighted — keep them out of any public remote (scrub history with `git filter-repo` before ever making a library public)
- Missing Python deps auto-install: `pip3 install --user --break-system-packages pymupdf rapidocr-onnxruntime` (drop `--break-system-packages` on hosts where you have sudo or a venv)

## Red Flags (stop and self-check)

- "skip the tiering confirmation, we'll review at the end" → violates the confirmation gate; return to ②
- OCR long task run bare without `timeout` → killed at ~10 min, wasted run
- quotations trusted straight from OCR without re-checking → violates the quality gate
- skipping Step 0 state detection and running from scratch → may redo finished work
- a .mobi/.azw3 dropped into `sources/` awaiting the pipeline → ① only accepts pdf/epub; convert first

## Maintenance

This English `SKILL.md` is the canonical source. `SKILL.zh.md` is the Chinese mirror — update both together; if they drift, English wins.
