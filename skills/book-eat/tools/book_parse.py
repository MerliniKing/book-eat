#!/usr/bin/env python3
r"""book_parse —— 多模态直读逐页解析流水线（固化的原子能力；固定单一正典 PROMPT，无多轮对比，不依赖 OCR）。

把一本书的全量扫描页交给 GLM 直读（每页产出：有没有图/表 + bbox% + 文字全文），
脚本负责其中一切可测量环节：渲染、分片 prompt 生成、分片回收校验合并、对账报告。
视觉阅读由 Claude Code 会话派 Agent 执行（prompts 子命令输出即派工文本）；
"测量优先于叙述"：页况结论以 roundX-all.jsonl 数据为准，不采信口报。

子命令：
  render  <书> [--pdf 路径] [--dpi 100] [--workdir /tmp/book_parse_<slug>]
          渲染全书页码图（单一进程串行，遵守低占铁律）
  prompts <书> [--workdir ...] [--shard 45] [--round A] [--out 目录]
          按正典 PROMPT 打印各分片派工文本（含页区间与交付文件名）
  merge   <书> --round A [--dir /tmp/book_parse]
          校验并合并 round<A>-*.jsonl 分片 → books/<书>/book-parse/pages.jsonl（页况档案真相源）
          （自动修复行内直引号；校验行数/连续性/字段完整性）
  chapters <书> [--offset N]  从档案解析目录→章名/起止页（merge 后自动跑；--offset 手动校正）
  crop    <书> --round A [--slug fs1] [--type figure|table] [--pages 1,5-9] [--dry-run]
          消费 round jsonl 的 regions：按框裁剪源 PDF 并登记 img/图录.json
          （文件名 <slug>-glm-p<页>-<序>.jpg；--dry-run 只列将产出的裁剪不落盘）
          页级漏报/误报（GT=图录有图页∪表页）＋区域 IoU（vs 图录 rect）
          抽验走 overlay 叠框图/人工抽页协议）

正典 PROMPT（2026-08-28 用户确认合并版：A 判据条款 × C 示例校准 × B/C 双保险交付）：
见 PROMPT 常量。改它须经用户确认。

用法示例（在库根目录）：
  python3 tools/book_parse.py render 今-汉宝德-风水与环境
  python3 tools/book_parse.py prompts 今-汉宝德-风水与环境 --round A
  python3 tools/book_parse.py merge 今-汉宝德-风水与环境 --round A
"""
import argparse, glob, json, os, re, sys

PROMPT = """你是书页解析员。{workdir}/ 目录下是某本书的逐页扫描图 pNNN.png。用 Read 工具逐张查看 {lo_png} 至 {hi_png}，为每页输出一行 JSON：
{{"page":N,"has_figure":布尔,"has_table":布尔,"regions":[[x0,y0,x1,y1,"figure"或"table"]],"text":"…"}}

示例——假如某页上半是一张带边框的「历代纪元表」、中间一段正文、下方一幅无框山水示意图，理想输出是：
{{"page":57,"has_figure":true,"has_table":true,"regions":[[8,10,92,40,"table"],[12,55,88,82,"figure"]],"text":"…正文自表格之后抄起…"}}
要点：表格框含边框整体；示意图连同它下方那行题注一起框；text 只抄正文文字，表格里和图里的字不抄。

判定规则：
1. has_table=true 当且仅当页面存在由边框线/行列分隔线构成的表格结构
2. has_figure=true 当页面存在正文文字排版之外的图形：插图、照片、地图、图表、示意图、手绘图皆算；纯装饰纹样、页眉页脚不算
3. regions：每个独立图表的最小完整外接框，必须把题注、图内标注、紧邻图例一起包入（表格含边框整体）；坐标为页面百分比（x0左/y0上/x1右/y1下，0–100，原点左上）；无图表填 []
   ★ 表格内部嵌的小图不单独标注坐标——一张表只给一组 table 坐标；表格之外的独立图才单独框
4. text：忠实转写该页全部正文文字，按阅读顺序，含章节标题；表格与图内部文字不转写；空白页输出 ""；辨认不清的字写【不可辨】
5. 纪律：每页必须亲眼看过再判定；不跳页、不臆测；扫描污渍不是图

交付：全部 {n} 行 JSONL 用 Write 工具写入 {outfile}，然后在最终回复里原样贴出这 {n} 行（双保险）。不要输出任何解释文字。"""

def book_root(book):
    p = os.path.join('books', book)
    if not os.path.isdir(p):
        sys.exit('书目录不存在: ' + p)
    return p

def find_pdf(book, override):
    if override:
        return override
    hits = []
    for d, _, fs in os.walk(os.path.join('sources')):
        for fn in fs:
            if fn.lower().endswith(('.pdf', '.epub')) and book.split('-')[-1] in fn:
                hits.append(os.path.join(d, fn))
    if len(hits) != 1:
        sys.exit('PDF 不唯一/未找到，用 --pdf 指定: ' + '; '.join(hits))
    return hits[0]

def npages(pdf):
    import fitz
    doc = fitz.open(pdf)
    n = len(doc); doc.close()
    return n

def cmd_render_epub(a, epub):
    import zipfile, html.parser, json
    broot = book_root(a.book)
    outdir = os.path.join(broot, 'book-parse'); os.makedirs(outdir, exist_ok=True)
    mediadir = os.path.join(outdir, 'media'); os.makedirs(mediadir, exist_ok=True)
    class _P(html.parser.HTMLParser):
        def __init__(self):
            super().__init__(); self.txt=[]; self.title=''; self.media=[]; self._h=None
        def handle_starttag(self, tag, attrs):
            if tag in ('h1','h2','h3') and not self.title: self._h=tag
            if tag=='img':
                d=dict(attrs)
                if d.get('src'): self.media.append(os.path.basename(d['src']))
        def handle_endtag(self, tag):
            if tag==self._h: self._h=None
            if tag in ('p','div','h1','h2','h3'): self.txt.append('\n')
        def handle_data(self, d):
            d=d.strip()
            if d:
                if self._h and not self.title: self.title=d
                self.txt.append(d+' ')
    z=zipfile.ZipFile(epub)
    names=set(z.namelist())
    container=z.read('META-INF/container.xml').decode('utf-8','ignore')
    opf=re.search(r'full-path="([^"]+)"',container).group(1)
    opfdir=os.path.dirname(opf)
    opfxml=z.read(opf).decode('utf-8','ignore')
    man={}
    for tag in re.finditer(r'<item\b[^>]*/?>',opfxml):
        t=tag.group(0)
        gid=re.search(r'id="([^"]+)"',t); ghref=re.search(r'href="([^"]+)"',t); gmt=re.search(r'media-type="([^"]+)"',t)
        if gid and ghref: man[gid.group(1)]=(ghref.group(1), gmt.group(1) if gmt else '')
    spine=[m.group(1) for m in re.finditer(r'<itemref[^>]*idref="([^"]+)"',opfxml)]
    chapters=[]
    for i,idref in enumerate(spine,1):
        href,mt=man.get(idref,('',''))
        full=os.path.normpath(os.path.join(opfdir,href)).replace('\\','/')
        if mt and 'html' not in mt or full not in names: continue
        p=_P(); p.feed(z.read(full).decode('utf-8','ignore'))
        txt=re.sub(r'\n{3,}','\n\n',''.join(p.txt)).strip()
        chapters.append(dict(chapter=i,href=href,title=p.title or os.path.basename(href),text=txt,media=p.media))
    out=os.path.join(outdir,'chapters.jsonl')
    open(out,'w',encoding='utf8').write('\n'.join(json.dumps(c,ensure_ascii=False) for c in chapters)+'\n')
    media_all=sorted({m for c in chapters for m in c['media']})
    extracted=0
    for mname in media_all:
        full=[n for n in names if n.endswith(mname)]
        if full:
            open(os.path.join(mediadir,os.path.basename(mname)),'wb').write(z.read(full[0])); extracted+=1
    print('✓ EPUB 结构化解析：%d 章 → %s；媒体 %d 个 → %s（未登记图录；收割时用 crop --register-media 或明确指示）'
          % (len(chapters), out, extracted, mediadir))
    print('  章文本即档案文字；媒体无页码语义，按章节锚定（chapters.jsonl 的 media 字段）')

def cmd_render(a):
    pdf = find_pdf(a.book, a.pdf)
    if pdf.lower().endswith('.epub'):
        return cmd_render_epub(a, pdf)
    import fitz
    pdf = find_pdf(a.book, a.pdf)
    os.makedirs(a.workdir, exist_ok=True)
    doc = fitz.open(pdf)
    for i in range(len(doc)):
        doc[i].get_pixmap(dpi=a.dpi).save(os.path.join(a.workdir, 'p%03d.png' % (i + 1)))
    n = len(doc); doc.close()
    print('rendered %d pages -> %s' % (n, a.workdir))

def cmd_prompts(a):
    pdf = find_pdf(a.book, a.pdf)
    n = npages(pdf)
    slug = re.sub(r'[^\w]', '', a.book.split('-')[-1])[:8] or 'book'
    a.workdir = a.workdir.rstrip('/')
    i = 1
    while i <= n:
        hi = min(i + a.shard - 1, n)
        name = '%s-pa-%s.jsonl' % (a.round.lower(), chr(ord('a') + (i - 1) // a.shard))
        out = os.path.join(a.out, name)
        print('=== 分片 %s（p%d–%d）→ 交付 %s' % (chr(ord('a') + (i - 1) // a.shard).upper(), i, hi, out))
        print(PROMPT.format(workdir=a.workdir, lo_png='p%03d.png' % i, hi_png='p%03d.png' % hi,
                            n=hi - i + 1, outfile=out))
        print()
        i = hi + 1

def _fix_line(line):
    m = re.match(r'^(\{"page":\d+,"has_figure":(?:true|false),"has_table":(?:true|false),'
                 r'"regions":\[(?:\[[^\]]*\],?)*\]),"text":"(.*)"\}$', line)
    if m:
        return m.group(1) + ',"text":"' + m.group(2).replace('\\', '\\\\').replace('"', '\\"') + '"}'
    json.loads(line)
    return line

def cmd_merge(a):
    broot = book_root(a.book)
    shards = [f for f in sorted(glob.glob(os.path.join(a.dir, 'round%s-*.jsonl' % a.round)))
              if '-all' not in os.path.basename(f)]
    if not shards:
        sys.exit('无分片: %s/round%s-*.jsonl' % (a.dir, a.round))
    rows = {}
    for sp in shards:
        if '.part' in sp:
            continue
        for line in open(sp, encoding='utf8'):
            line = line.strip()
            if not line:
                continue
            r = json.loads(_fix_line(line))
            rows[r['page']] = r
    pages = sorted(rows)
    gaps = [p for p in range(pages[0], pages[-1] + 1) if p not in rows]
    need = {'page', 'has_figure', 'has_table', 'regions', 'text'}
    bad = [p for p in pages if not need <= set(rows[p])]
    if gaps or bad:
        sys.exit('分片不完整: 缺页 %s 坏行 %s' % (gaps[:10], bad[:10]))
    outdir = os.path.join(broot, 'book-parse')
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, 'pages.jsonl')
    open(out, 'w', encoding='utf8').write(
        '\n'.join(json.dumps(rows[p], ensure_ascii=False) for p in pages) + '\n')
    nf = sum(rows[p]['has_figure'] for p in pages)
    nt = sum(rows[p]['has_table'] for p in pages)
    print('✓ %s（%d 页 %d-%d 连续）has_figure=%d has_table=%d' % (out, len(pages), pages[0], pages[-1], nf, nt))
    try:
        entries, off, _ = parse_chapters(rows, None)
        cout = os.path.join(outdir, 'chapters.jsonl')
        open(cout, 'w', encoding='utf8').write(
            '\n'.join(json.dumps(e, ensure_ascii=False) for e in entries) + '\n')
        ver = sum(1 for e in entries if e['verified'])
        print('  ↳ 章节解析：%d 条 → %s（偏移=%s，页眉校验 %d/%d；细调用 book_parse chapters --offset）'
              % (len(entries), cout, off, ver, len(entries)))
    except Exception as e:
        print('  ↳ 章节解析跳过：%s' % e)

def parse_chapters(rows, offset=None):
    """从档案解析目录页→章名/起止页。返回 entries 列表（含 pdf 换算与页眉校验）。"""
    toc_texts = []
    for p in sorted(rows):
        t = (rows[p].get('text') or '').strip()
        if not t:
            continue
        pairs = re.findall(r'([\u4e00-\u9fff《》〔〕][^0-9\n]{1,40}?)\s?(\d{1,3})(?=\s|$)', t)
        if re.search(r'目\s*录', t[:24]) or len(pairs) >= 6:
            toc_texts.append((p, t))
    entries = []
    for p, t in toc_texts:
        t = re.sub(r'^.*?目\s*录', '', t, count=1, flags=re.S) if re.search(r'目\s*录', t[:24]) else t
        for m in re.finditer(r'([\u4e00-\u9fff《》〔〕][^0-9\n]{1,40}?)\s?(\d{1,3})(?=\s|$)', t):
            title = re.sub(r'\s', '', m.group(1))
            if len(title) >= 2:
                entries.append({'title': title, 'print_page': int(m.group(2)), 'toc_page': p})
    # 去重（跨目录页重复项）并保持单调
    seen, mono = set(), []
    last = 0
    for e in entries:
        key = (e['title'], e['print_page'])
        if key in seen or e['print_page'] < last:
            continue
        seen.add(key); mono.append(e); last = e['print_page']
    entries = mono
    # 偏移自动探测：对 0..40 逐个试，取“章首页含章名前4字”的命中数最大者
    def score(off):
        hit = 0
        for e in entries:
            pg = e['print_page'] + off
            t = rows.get(pg, {}).get('text', '')
            if t and e['title'][:4] in t.replace(' ', ''):
                hit += 1
        return hit
    if offset is None:
        best = max(range(0, 41), key=score)
        if score(best) == 0:
            return entries, None, 0
        offset = best
    for e in entries:
        e['pdf_page'] = e['print_page'] + offset
        t = rows.get(e['pdf_page'], {}).get('text', '').replace(' ', '')
        e['verified'] = bool(t) and e['title'][:4] in t
    for i, e in enumerate(entries):
        nxt = entries[i + 1]['pdf_page'] if i + 1 < len(entries) else max(rows) + 1
        e['end_pdf_page'] = max(e['pdf_page'], nxt - 1)
    return entries, offset, 0

def cmd_chapters(a):
    broot = book_root(a.book)
    path = os.path.join(broot, 'book-parse', 'pages.jsonl')
    if not os.path.exists(path):
        sys.exit('档案不存在: %s（先跑 merge）' % path)
    rows = {r['page']: r for r in map(json.loads, filter(str.strip, open(path, encoding='utf8')))}
    entries, off, _ = parse_chapters(rows, a.offset)
    out = os.path.join(broot, 'book-parse', 'chapters.jsonl')
    open(out, 'w', encoding='utf8').write(
        '\n'.join(json.dumps(e, ensure_ascii=False) for e in entries) + '\n')
    verified = sum(1 for e in entries if e['verified'])
    print('✓ %s（%d 章，偏移=%s，页眉校验通过 %d/%d）' % (out, len(entries), off, verified, len(entries)))
    for e in entries:
        mark = '✓' if e['verified'] else '?'
        print('  p%-4d-%-4d %s %s' % (e['pdf_page'], e['end_pdf_page'], mark, e['title']))


def cmd_crop(a):
    import fitz
    broot = book_root(a.book)
    path = os.path.join(broot, 'glm-parse', 'round%s-all.jsonl' % a.round)
    rows = {r['page']: r for r in map(json.loads, filter(str.strip, open(path, encoding='utf8')))}
    man_path = os.path.join(broot, 'img', '图录.json')
    figs = json.load(open(man_path)) if os.path.exists(man_path) else []
    have = {e['file'] for e in figs}
    pdf = find_pdf(a.book, a.pdf)
    doc = fitz.open(pdf)
    slug = a.slug or a.book.split('-')[-1]
    want_pages = None
    if a.pages:
        want_pages = set()
        for seg in a.pages.split(','):
            if '-' in seg:
                lo, hi = map(int, seg.split('-')); want_pages |= set(range(lo, hi + 1))
            else:
                want_pages.add(int(seg))
    plan = []
    for p in sorted(rows):
        if want_pages and p not in want_pages:
            continue
        pw, ph = doc[p - 1].rect.width, doc[p - 1].rect.height
        k = 0
        for rg in rows[p].get('regions', []):
            x0, y0, x1, y1, typ = rg[0], rg[1], rg[2], rg[3], rg[4] if len(rg) > 4 else 'figure'
            if a.type and typ != a.type:
                continue
            k += 1
            fn = '%s-glm-p%03d-%d.jpg' % (slug, p, k)
            plan.append((p, typ, (x0 / 100 * pw, y0 / 100 * ph, x1 / 100 * pw, y1 / 100 * ph), fn))
    doc.close()
    print('计划裁剪 %d 项（round%s / type=%s / pages=%s）' % (len(plan), a.round, a.type or '全部', a.pages or '全部'))
    if a.dry_run:
        for p, typ, rect, fn in plan:
            dup = ' [文件名已存在，将跳过]' if fn in have else ''
            print('  p%-4d %-6s %s%s' % (p, typ, fn, dup))
        return
    import fitz as F
    doc = F.open(pdf)
    added = skipped = 0
    for p, typ, rect, fn in plan:
        if fn in have:
            skipped += 1; continue
        clip = F.Rect(*rect)
        pix = doc[p - 1].get_pixmap(clip=clip, dpi=a.dpi, colorspace=F.csGRAY)
        out = os.path.join(broot, 'img', fn)
        pix.save(out)
        entry = {'file': fn, 'pdf': pdf, 'page': p,
                 'rect': [round(v, 1) for v in rect], 'dpi': a.dpi,
                 'caption': 'book_parse round%s p%d %s 区域裁剪' % (a.round, p, typ)}
        figs = [e for e in figs if e.get('file') != fn] + [entry]
        added += 1
    doc.close()
    json.dump(figs, open(man_path, 'w'), ensure_ascii=False, indent=1)
    print('✓ 新增登记 %d 项，跳过已存在 %d 项 → 图录 %s（共 %d 条）' % (added, skipped, man_path, len(figs)))



def main():
    ap = argparse.ArgumentParser(description=__doc__.split('子命令：')[0])
    ap.add_argument('cmd', choices=['render', 'prompts', 'merge', 'chapters', 'crop'])
    ap.add_argument('book')
    ap.add_argument('--pdf'); ap.add_argument('--dpi', type=int, default=100)
    ap.add_argument('--workdir', default=None)
    ap.add_argument('--shard', type=int, default=45)
    ap.add_argument('--round', default='A')
    ap.add_argument('--out', default='/tmp/book_parse')
    ap.add_argument('--dir', default='/tmp/book_parse')
    ap.add_argument('--slug', default=None)
    ap.add_argument('--type', default=None, choices=[None, 'figure', 'table'])
    ap.add_argument('--pages', default=None)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--offset', type=int, default=None)
    a = ap.parse_args()
    if a.workdir is None:
        a.workdir = '/tmp/book_parse_' + re.sub(r'[^\w]', '', a.book)
    {'render': cmd_render, 'prompts': cmd_prompts, 'merge': cmd_merge,
     'chapters': cmd_chapters, 'crop': cmd_crop}[a.cmd](a)

if __name__ == '__main__':
    main()
