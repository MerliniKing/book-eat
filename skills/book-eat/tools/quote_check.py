#!/usr/bin/env python3
"""Write-side fidelity gate: verify that every quotation in a note file
actually exists in the book's OCR/text cache.

Write-side?  Existing checks verify you READ a page correctly (OCR vs image).
This one verifies you WROTE faithfully: each blockquote in the note must trace
back to ocr/full.txt. It catches (all real incidents):
  - quotes written from memory against a cache that lacks the passage
    (silently incomplete EPUB text layers)
  - transcription inversions / character swaps inside "verbatim" quotes
  - paraphrases accidentally wrapped in quotation marks

Usage:
  python3 tools/quote_check.py <ocr_full.txt> <note.md> [more.md ...]

Method: blockquote lines are split on punctuation into fragments (>=5 chars);
whitespace/stripped-control-char cache is searched for each fragment verbatim.
A MISS is only a *suspect*, never a verdict: OCR noise, traditional/simplified
variants, edition variants and translated quotes (foreign-language books) all
miss legitimately. The gate's job is to force every miss to be *resolved* as
one of: (a) OCR/variant noise — checked and documented, (b) translation,
(c) marked ⚠unverified with the reason. Exit 1 if any miss remains, so it can
gate a commit.

Limitations: no fuzzy matching (deliberately — misses must be eyeballed);
inline (non-blockquote) quotes are not scanned; synthetic EPUB page numbering
means page citations are not checked, only text presence.
"""
import re
import sys
import pathlib

MIN_FRAG = 5
# common OCR/edition glyph pairs worth trying before declaring a miss
VARIANTS = {'入': '人', '微': '薇', '辨': '辯', '蚀': '食', '睺': '喉'}


def load_cache(path: str) -> str:
    raw = pathlib.Path(path).read_bytes().decode('utf-8', errors='ignore')
    return re.sub(r'[\x00-\x08\x0b-\x1f\x7f\s]', '', raw)


def fragments(line: str):
    line = re.sub(r'^\s*>\s?', '', line)
    line = re.sub(r'[*_`]', '', line)
    line = re.sub(r'（[^）]*）', '', line)  # drop inline editorial parentheses
    parts = re.split(
        r'[……。；：、，！？“”「」『』《》\[\]()（）·—\-\s]', line)
    return [p for p in parts if len(p) >= MIN_FRAG]


def check_note(note_path: str, cache: str):
    suspects = []
    for i, line in enumerate(pathlib.Path(note_path).read_text(
            errors='ignore').splitlines(), 1):
        if not line.lstrip().startswith('>'):
            continue
        for frag in fragments(line):
            if frag in cache:
                continue
            if any(frag.replace(k, v) in cache for k, v in VARIANTS.items()
                   if k in frag):
                continue
            suspects.append((i, frag))
    return suspects


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    cache = load_cache(sys.argv[1])
    total_miss = 0
    for note in sys.argv[2:]:
        if 'ocr' in pathlib.Path(note).parts:  # never scan the cache itself
            continue
        suspects = check_note(note, cache)
        name = pathlib.Path(note).name
        if suspects:
            for line_no, frag in suspects:
                print(f'  MISS {name}:L{line_no}  {frag}')
            total_miss += len(suspects)
        else:
            print(f'  OK   {name}')
    if total_miss:
        print(f'\n{total_miss} unresolved quotation fragment(s). Every MISS must be '
              'resolved as: OCR/variant noise (verified), translation, or '
              '⚠unverified-marked with reason. Do not commit unresolved.')
        sys.exit(1)
    print('\nAll quotations trace to the cache (or are documented variants).')


if __name__ == '__main__':
    main()
