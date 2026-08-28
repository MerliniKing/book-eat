---
name: book-eat
description: 吃书流水线（中文镜像版）：提取优先、视觉兜底——直接取文字层/结构化解包，扫描页才用视觉直读；逐页档案（图/表有无+bbox+全文）是唯一真相源；定纲有确认门；图片收割由档案 bbox 驱动；固定单一正典 PROMPT、全流程不依赖 OCR。本文件为 SKILL.md 英文版的中文镜像——两份同步更新，失同步时以英文版为准。
---

# book-eat · 吃一本书（中文镜像版）

> **维护声明**：英文 `SKILL.md` 是规范真相源，本文件是其中文镜像。改 skill 时两份一起改；失同步以英文版为准。
> **原则（第 1 条）**：提取优先——源里有的文字（文字层/结构化文本）直接取；视觉识别只用于扫描页转写与图表判定。

## 库布局

```
sources/                     书源（PDF/EPUB）——仅本机，gitignore
book-content/books/<书>/
  book-parse/                真相源
    pages.jsonl              PDF：{page, book_page, is_toc, toc, has_figure, has_table, regions[bbox%], text}
    chapters.jsonl           章节表：{title, print_page, pdf_page, end_pdf_page, verified}
    media/                   EPUB 内嵌媒体（抽出未登记）
  img/                       已收割图（crop 产物）＋ 图录.json
  chapter-<slug>-<NN>-<标题>.md   章节页（发布单元）
  精读-*.md 摘要-*.md README.md 学习进度.md
site/                        私库网站（build_html/publish_web/home/theme/assets/dist）
tools/                       book_parse 等流水线工具
```

## 工具状态（未经用户确认不得复活）

| 工具 | 状态 |
|---|---|
| book_parse.py | **现行**——render/prompts/merge/chapters/crop |
| pages_probe.py | 仅预筛，绝不作为完整性证据 |
| extract_figures.py | 遗留（私库自持），已被 crop 取代 |
| run_ocr.py · quote_check.py · check_source.py | **随 OCR 退役**（2026-08-28） |
| fig_coverage_lint.py · audit_library.py | 清理后失效（依赖 books/*/ocr/），仅存档 |

## 第 0 步 · 状态检测（每次调用）

| book-parse/ | chapter-*.md | 状态 |
|---|---|---|
| 无 | 无 | 全新 → ① |
| 有 | 无 | 已解析 → ②定纲门 |
| 有 | 有 | 写作/发布 → ③–⑥ |
| 半满 | 任意 | 中断 → `book_parse merge` 续跑 |

## ① 解析（全书档案）——提取优先，视觉兜底

| 源 | 文字 | 图/表 |
|---|---|---|
| 原生 PDF（有文字层） | 文字层直取 | 渲染页→视觉判有无与 bbox |
| 扫描 PDF | **视觉直读转写即文字源** | 同一视觉遍 |
| EPUB | 结构化解包：spine XHTML→章文本 | 内嵌媒体整包抽到 media/（按章锚定，无页码语义） |

扫描路径：`book_parse render`（串行 dpi100）→ `prompts` 打印分片派工文本 → 每片一个只读 Agent（逐页：有无+bbox+全文）→ `merge`（校验连续性/字段、修引号）。正典 PROMPT 内嵌于 book_parse.py，改动须经用户确认。

## ② 定纲 → ⛔ 确认门

提出分级方案（精读/摘要/跳过）＋章节页切分建议。**停下等用户确认分级**，未确认不写一个字。

## ③④⑤ 精读 → 归档 → 卡片

- 引文一律从 book-parse 档案全文复制；档案里没有的段落不得引用，标 ⚠未验证
- 图片：`book_parse crop` 按档案 bbox 收割（表格含内嵌小图只给一组 table 坐标）；章节页引用 `img/<slug>-…`，缺图＝发布失败（强校验，是门不是故障）
- 卡片入 cards/*.md，带出处+难度+复习梯

## ⑥ 看板与发布

学习进度.md 是进度账本（已读标记经 mihomo 代理 127.0.0.1:7890 从 CF KV 收割）。发布走 publish_web.sh，发布后**必须经代理验证**改动的 URL 返回 200（Workers 构建窗口约 30–60 秒，404 先重试再诊断）。

## 硬规则

- 提取优先，视觉兜底；全流程无 OCR 工具，OCR 历史保持已删状态
- 单一正典 PROMPT；不做 A/B/C 多轮对比；不用像素探针当完整性证据；档案是“有没有”的唯一证人
- 笔记里禁止“没有图/已全覆盖”式断言——只写解析到了什么、在哪
- 装饰纹样（鱼形尾花/印章）不算图

## Red Flags（停下自检）

- “这段我记得”——凭记忆引用而非档案复制（P0 级）
- 没跑档案对账就宣布收割完成
- 第三方识图当终验收口（会误判；Claude 直读才是收口）
- 分片 Agent 只在对话里贴结果不写盘（merge 校验不过）
- EPUB 媒体当页码锚定对象（无页码语义）

## 维护

PROMPT/流水线改动须经用户确认后在开源仓提交（github.com/MerliniKing/book-eat），私库以 symlink 指入。OCR 时代的历史提取产物已于 2026-08-28 清空（git 34e6842^ 可回溯）。
