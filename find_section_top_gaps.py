#!/usr/bin/env python3
"""Find pages where a section heading sits at the TOP of a page (within a paper),
and report the empty-space gap at the bottom of the PREVIOUS page.

Reuses the geometry conventions of find_orphans.py / find_unbalanced.py.
Works on any `pdftotext -bbox-layout` HTML (full book or a single-paper build).

Usage:  python3 find_section_top_gaps.py pNNN_bbox.html
"""
import sys, re
import xml.etree.ElementTree as ET
from collections import defaultdict

FULL_BOTTOM = 623.0   # 90th-percentile text bottom in the full book (pt); used for gap


def lt(tag):
    return tag.split('}')[-1]


def summarize(pn, ws):
    body = [w for w in ws if 50 < w[0] < 640]
    hdr = [w for w in ws if w[0] <= 50]
    hdr_text = ' '.join(w[3] for w in sorted(hdr, key=lambda w: w[2]))
    lines = defaultdict(list)
    for w in body:
        lines[round(w[0])].append(w)
    # maxbody = bottom of the BODY columns (body glyph height ~9.96).
    # Exclude footnotes (~8.97-9.0), verse markers (~6), and titles (~13), which
    # would otherwise mask the real gap (e.g. a bottom footnote pinned at y~623).
    body_ys = [yk for yk, grp in lines.items()
               if 9.6 < max(w[0] - w[1] for w in grp) < 10.6]
    maxbody = max(body_ys, default=max((round(w[0]) for w in body), default=0))
    first = None
    for yk in sorted(lines):
        grp = lines[yk]
        h = max(w[0] - w[1] for w in grp)
        if h > 8.0:                       # skip ~6pt verse-marker superscripts
            first = (yk, h, ' '.join(w[3] for w in sorted(grp, key=lambda w: w[2])))
            break
    return dict(pn=pn, hdr=hdr_text, has_hdr=bool(hdr), maxbody=maxbody, first=first,
                nlines=len(lines))


def main(path):
    pages = []
    pageno = 0
    words = []
    for ev, el in ET.iterparse(path, events=('start', 'end')):
        t = lt(el.tag)
        if ev == 'start' and t == 'page':
            pageno += 1
            words = []
        elif ev == 'end' and t == 'word':
            txt = (el.text or '').strip()
            if txt:
                words.append((float(el.get('yMax')), float(el.get('yMin')),
                              float(el.get('xMin')), txt))
        elif ev == 'end' and t == 'page':
            pages.append(summarize(pageno, words))
            words = []
            el.clear()

    vr = re.compile(r'(\d+):(\d+)\.(\d+)')
    title_re = re.compile(r'^\s*(\d+(?:\s+and\s+\d+)?)\.\s+\S')
    NORMAL_TOP = 67.0   # flush section title sits at yMax ~65; >72 means whitespace above it
    found = 0
    print(f"{'PDFpg':>5} | {'Paper':>5} {'§top':>6} | {'botGap':>6} {'~ln':>4} | "
          f"{'titleY':>6} {'topGap':>6} | flags | title")
    print('-' * 100)
    for i, p in enumerate(pages):
        f = p['first']
        if not f:
            continue
        yk, h, txt = f
        if not (12.0 < h < 14.5):
            continue
        m = title_re.match(txt)
        if not m or not p['has_hdr']:
            continue
        vm = vr.search(p['hdr'])
        paper = vm.group(1) if vm else '?'
        prev = pages[i - 1] if i > 0 else None
        gap = (FULL_BOTTOM - prev['maxbody']) if prev else 0
        top_gap = yk - NORMAL_TOP        # whitespace above the section title (relocated gap)
        flags = []
        if top_gap > 5:
            flags.append('TOP-GAP!')     # title pushed down -> gap relocated above heading (BAD)
        title = re.sub(r'^\s*\d+(?:\s+and\s+\d+)?\.\s*', '', txt)[:36]
        print(f"{p['pn']:>5} | P{paper:<4} §{m.group(1):>5} | {gap:>6.0f} {gap/11:>4.1f} | "
              f"{yk:>6.0f} {top_gap:>6.0f} | {' '.join(flags):>8} | {title}")
        found += 1
    print(f"\n{found} section-at-top page(s) detected.  "
          f"(botGap = empty space at bottom of previous page; "
          f"topGap = empty space above this title — >5 is BAD)")


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'full_bbox.html')
