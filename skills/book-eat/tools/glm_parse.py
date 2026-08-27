#!/usr/bin/env python3
r"""glm_parse —— 多模态直读逐页解析流水线（fs1 三轮对比实验后固化的原子能力）。

把一本书的全量扫描页交给 GLM 直读（每页产出：有没有图/表 + bbox% + 文字全文），
脚本负责其中一切可测量环节：渲染、分片 prompt 生成、分片回收校验合并、对账报告。
视觉阅读由 Claude Code 会话派 Agent 执行（prompts 子命令输出即派工文本）；
"测量优先于叙述"：页况结论以 roundX-all.jsonl 数据为准，不采信口报。

子命令：
  render  <书> [--pdf 路径] [--dpi 100] [--workdir /tmp/glm_parse_<slug>]
          渲染全书页码图（单一进程串行，遵守低占铁律）
  prompts <书> [--workdir ...] [--shard 45] [--round A] [--out 目录]
          按正典 PROMPT 打印各分片派工文本（含页区间与交付文件名）
  merge   <书> --round A [--dir /tmp/glm_parse]
          校验并合并 round<A>-pa-*.jsonl 分片 → books/<书>/glm-parse/roundA-all.jsonl
          （自动修复行内直引号；校验行数/连续性/字段完整性）
  compare <书> --round A [--table-pages 201-266]
          页级漏报/误报（GT=图录有图页∪表页）＋区域 IoU（vs 图录 rect）
          ＋文字抽检相似度（vs ocr/pages）；--table-pages 缺省只用图录页当 GT 并注明局限

正典 PROMPT（2026-08-28 用户确认合并版：A 判据条款 × C 示例校准 × B/C 双保险交付）：
见 PROMPT 常量。改它须经用户确认。

用法示例（在库根目录）：
  python3 tools/glm_parse.py render 今-汉宝德-风水与环境
  python3 tools/glm_parse.py prompts 今-汉宝德-风水与环境 --round A
  python3 tools/glm_parse.py merge 今-汉宝德-风水与环境 --round A
  python3 tools/glm_parse.py compare 今-汉宝德-风水与环境 --round A --table-pages 201-266
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
3. regions：每个图表的最小完整外接框，必须把题注、图内标注、紧邻图例一起包入（表格含边框整体）；坐标为页面百分比（x0左/y0上/x1右/y1下，0–100，原点左上）；无图表填 []
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
            if fn.lower().endswith('.pdf') and book.split('-')[-1] in fn:
                hits.append(os.path.join(d, fn))
    if len(hits) != 1:
        sys.exit('PDF 不唯一/未找到，用 --pdf 指定: ' + '; '.join(hits))
    return hits[0]

def npages(pdf):
    import fitz
    doc = fitz.open(pdf)
    n = len(doc); doc.close()
    return n

def cmd_render(a):
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
    outdir = os.path.join(broot, 'glm-parse')
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, 'round%s-all.jsonl' % a.round)
    open(out, 'w', encoding='utf8').write(
        '\n'.join(json.dumps(rows[p], ensure_ascii=False) for p in pages) + '\n')
    nf = sum(rows[p]['has_figure'] for p in pages)
    nt = sum(rows[p]['has_table'] for p in pages)
    print('✓ %s（%d 页 %d-%d 连续）has_figure=%d has_table=%d' % (out, len(pages), pages[0], pages[-1], nf, nt))

def cmd_compare(a):
    broot = book_root(a.book)
    path = os.path.join(broot, 'glm-parse', 'round%s-all.jsonl' % a.round)
    rows = {r['page']: r for r in map(json.loads, filter(str.strip, open(path, encoding='utf8')))}
    man = json.load(open(os.path.join(broot, 'img', '图录.json')))
    gt = {e['page'] for e in man}
    if a.table_pages:
        for seg in a.table_pages.split(','):
            if '-' in seg:
                lo, hi = map(int, seg.split('-')); gt |= set(range(lo, hi + 1))
            else:
                gt.add(int(seg))
    else:
        print('（未指定 --table-pages：GT 仅图录页，附录类整段表格页会算误报，注意口径）')
    g = {p for p, r in rows.items() if r['has_figure'] or r['has_table']}
    t = {p for p, r in rows.items() if r['has_table']}
    print('图形页: GT=%d 漏=%d%s 误=%d%s' % (len(gt), len(gt - g), sorted(gt - g)[:10] or '', len(g - gt), sorted(g - gt)[:10] or ''))
    if a.table_pages:
        tt = {p for p in gt if p not in {e['page'] for e in man}}
        print('表页: GT=%d 漏=%d%s 误=%d' % (len(tt), len(tt - t), sorted(tt - t)[:10] or '', len(t - tt)))
    # IoU vs 图录
    import fitz
    pdf = find_pdf(a.book, a.pdf)
    doc = fitz.open(pdf)
    def iou(x, y):
        x0, y0 = max(x[0], y[0]), max(x[1], y[1]); x1, y1 = min(x[2], y[2]), min(x[3], y[3])
        if x1 <= x0 or y1 <= y0: return 0.0
        A = (x[2] - x[0]) * (x[3] - x[1]); B = (y[2] - y[0]) * (y[3] - y[1])
        return (x1 - x0) * (y1 - y0) / (A + B - (x1 - x0) * (y1 - y0))
    vals = []
    for e in man:
        pw, ph = doc[e['page'] - 1].rect.width, doc[e['page'] - 1].rect.height
        gtbox = [e['rect'][0] / pw * 100, e['rect'][1] / ph * 100, e['rect'][2] / pw * 100, e['rect'][3] / ph * 100]
        regs = [r[:4] for r in rows.get(e['page'], {}).get('regions', [])]
        vals.append(max((iou(gtbox, rg) for rg in regs), default=0.0))
    doc.close()
    vals.sort()
    print('区域IoU vs 图录%d条: 中位=%.2f 均值=%.2f >=0.5 %d/%d' %
          (len(vals), vals[len(vals)//2], sum(vals)/len(vals), sum(1 for v in vals if v >= .5), len(vals)))
    # 文字抽检
    import difflib, random
    opages = glob.glob(os.path.join(broot, 'ocr', 'pages', 'p*.txt'))
    if opages:
        random.seed(7)
        sample = sorted(random.sample(opages, min(12, len(opages))))
        sims = []
        for op in sample:
            p = int(re.search(r'p(\d+)\.txt', op).group(1))
            if p not in rows: continue
            o = open(op, errors='ignore').read().replace('\n', '')
            x = rows[p]['text'].replace('\n', '')
            if o and x:
                sims.append((p, difflib.SequenceMatcher(None, x[:3000], o[:3000]).ratio()))
        if sims:
            s = sorted(v for _, v in sims)
            print('文字抽检%d页: 中位=%.2f 明细=%s' % (len(sims), s[len(s)//2], [(p, round(v, 2)) for p, v in sims]))

def main():
    ap = argparse.ArgumentParser(description=__doc__.split('子命令：')[0])
    ap.add_argument('cmd', choices=['render', 'prompts', 'merge', 'compare'])
    ap.add_argument('book')
    ap.add_argument('--pdf'); ap.add_argument('--dpi', type=int, default=100)
    ap.add_argument('--workdir', default=None)
    ap.add_argument('--shard', type=int, default=45)
    ap.add_argument('--round', default='A')
    ap.add_argument('--out', default='/tmp/glm_parse')
    ap.add_argument('--dir', default='/tmp/glm_parse')
    ap.add_argument('--table-pages', default=None)
    a = ap.parse_args()
    if a.workdir is None:
        a.workdir = '/tmp/glm_parse_' + re.sub(r'[^\w]', '', a.book)
    {'render': cmd_render, 'prompts': cmd_prompts, 'merge': cmd_merge, 'compare': cmd_compare}[a.cmd](a)

if __name__ == '__main__':
    main()
