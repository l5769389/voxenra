"""Build the product website and manual from the desktop app's content."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import struct
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

from PIL import Image, ImageSequence


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src/qt_dicom_viewer/qml/assets"
HELP = ASSETS / "help"
SITE = ROOT / "docs/manual-site"
PRODUCT_SCREENSHOTS = {
    "hero-mpr.png": "11-mpr-3d-layout.png",
    "feature-mr-reading.png": "07-mr-reading.png",
    "feature-fusion.png": "05-pet-ct-fusion.png",
    "feature-analysis.gif": "38-segmentation-refinement.gif",
    "feature-ai-segmentation.gif": "49-ai-workflow-2.1.1.gif",
    "feature-ai-segmentation.png": "48-ai-complete-2.1.1.png",
    "feature-measurements.png": "01-2d-measurement.png",
    "feature-theme-graphite.png": "37-theme-graphite.png",
    "feature-theme-dark.png": "25-theme-dark.png",
    "feature-theme-light.png": "26-theme-light.png",
    "feature-pacs.png": "16-pacs-browser.png",
    "feature-zip-drop.png": "35-zip-drop.png",
    "feature-zip-drag.gif": "06-zip-drag.gif",
    "feature-workspace-overview.png": "45-workspace-home-2.1.3.png",
    "feature-4d.gif": "03-4d-playback.gif",
    "feature-water-qa.png": "19-water-qa-2.1.3.png",
    "feature-mtf.png": "28-mtf-analysis.png",
}
for media, source in {
    'feature-cpr-reference.png': '61-cpr-reference-2.2.0.png',
    'feature-dimse-settings.png': '51-dimse-settings.png',
    'feature-dimse-import.gif': '52-dimse-import.gif',
    'feature-dimse-import.png': '52-dimse-import.png',
    'feature-toolbar.gif': '53-toolbar-customization.gif',
    'feature-toolbar.png': '53-toolbar-customization.png',
    'feature-focus.gif': '54-focus-view.gif',
    'feature-focus.png': '54-focus-view.png',
    'feature-window-favorites.png': '55-window-favorites.png',
}.items():
    PRODUCT_SCREENSHOTS[media] = source
    PRODUCT_SCREENSHOTS['en-' + media] = 'en/' + source
PRODUCT_IMAGE_WIDTHS = (640, 960, 1600)
PRODUCT_IMAGE_SIZES = {
    "hero": "(max-width: 940px) calc(100vw - 48px), (max-width: 1536px) 54vw, 800px",
    "half": "(max-width: 620px) calc(100vw - 48px), (max-width: 1536px) 44vw, 700px",
    "third": "(max-width: 620px) calc(100vw - 48px), (max-width: 1536px) 28vw, 450px",
    "wide": "(max-width: 1536px) calc(100vw - 48px), 1400px",
}
LANGUAGES = {
    "zh": {"pack": "zh-CN", "name": "简体中文", "search": "搜索章节与正文", "menu": "目录", "site": "操作手册", "home": "手册首页", "related": "相关章节", "shortcuts": "快捷键", "figure": "示意图", "examples": ("CT 示例", "PET 示例"), "repo": "GitHub 仓库"},
    "en": {"pack": "en-US", "name": "English", "search": "Search chapters and content", "menu": "Contents", "site": "Manual", "home": "Manual home", "related": "Related chapters", "shortcuts": "Shortcuts", "figure": "Diagram", "examples": ("CT example", "PET example"), "repo": "GitHub repository"},
}


def site_asset(prefix: str, name: str) -> str:
    """Change the URL when CSS or JS changes so cached layouts stay in sync."""
    digest = hashlib.sha256((SITE / name).read_bytes()).hexdigest()[:12]
    return f"{prefix}assets/{name}?v={digest}"


def product_image_asset(prefix: str, name: str) -> str:
    """Refresh product screenshots when their source file changes."""
    source = ROOT / "docs/screenshots" / PRODUCT_SCREENSHOTS[name]
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
    return f"{prefix}assets/{name}?v={digest}"


def product_image_size(name: str) -> str:
    """Reserve screenshot space before lazy loading, keeping section anchors stable."""
    return image_size(ROOT / "docs/screenshots" / PRODUCT_SCREENSHOTS[name])


@lru_cache(maxsize=128)
def encode_webp(source: Path, source_digest: str, width: int) -> bytes:
    """Cache by source content, preserving GIF timing and composited frames.

    These are website previews only; full-resolution source files stay unchanged.
    """
    with Image.open(source) as image:
        color_profile = image.info.get("icc_profile")
        target_width = min(width, image.width)
        size = (target_width, max(1, round(image.height * target_width / image.width)))
        frames, durations = [], []
        for frame in ImageSequence.Iterator(image):
            frames.append(frame.convert("RGBA").resize(size, Image.Resampling.LANCZOS))
            durations.append(frame.info.get("duration", 100))
        output = BytesIO()
        animation = dict(save_all=True, append_images=frames[1:], duration=durations,
                         loop=image.info.get("loop", 0)) if len(frames) > 1 else {}
        color_options = {"icc_profile": color_profile} if color_profile else {}
        frames[0].save(output, format="WEBP", quality=82, method=6, **animation, **color_options)
        return output.getvalue()


def product_image_variants(name: str) -> list[tuple[int, str, bytes]]:
    source = ROOT / "docs/screenshots" / PRODUCT_SCREENSHOTS[name]
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    with Image.open(source) as image:
        widths = sorted({min(width, image.width) for width in PRODUCT_IMAGE_WIDTHS})
    stem = Path(name).stem + ("-animated" if name.endswith(".gif") else "")
    return [(width, f"{stem}-{width}.webp", encode_webp(source, source_digest, width))
            for width in widths]


def product_image_sources(prefix: str, name: str) -> list[tuple[int, str]]:
    return [(width, f"{prefix}assets/{filename}?v={hashlib.sha256(data).hexdigest()[:12]}")
            for width, filename, data in product_image_variants(name)]


def product_image_attributes(prefix: str, name: str, layout: str = "half") -> str:
    sources = product_image_sources(prefix, name)
    srcset = ", ".join(f"{url} {width}w" for width, url in sources)
    return (f'src="{sources[-1][1]}" srcset="{srcset}" '
            f'sizes="{PRODUCT_IMAGE_SIZES[layout]}" decoding="async"')


def image_size(path: Path) -> str:
    with path.open("rb") as source:
        header = source.read(24)
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        width, height = struct.unpack(">II", header[16:24])
    elif header[:6] in (b"GIF87a", b"GIF89a"):
        width, height = struct.unpack("<HH", header[6:10])
    else:
        raise ValueError(f"Unsupported screenshot format: {path}")
    return f'width="{width}" height="{height}"'


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def rich(value: str) -> str:
    """Match the desktop manual's limited emphasis syntax; never trust HTML."""
    parts = re.split(r"(\*\*[^\n*]+\*\*|`[^\n`]+`)", value)
    return "".join(
        "<strong>" + escape(part[2:-2]) + "</strong>" if part.startswith("**") and part.endswith("**")
        else "<strong>" + escape(part[1:-1]) + "</strong>" if part.startswith("`") and part.endswith("`")
        else escape(part).replace("\n", "<br>")
        for part in parts
    )


def paragraphs(value: str) -> str:
    return "".join(f"<p>{rich(part)}</p>" for part in re.split(r"\n\s*\n", value) if part.strip())


def chapter_search(chapter: dict, messages: dict[str, str]) -> str:
    prefix = f'manual.{chapter["id"]}.'
    parts = [messages[prefix + "title"], messages[prefix + "summary"]]
    for index, section in enumerate(chapter["sections"]):
        key = section.get("messageId", prefix + f"section{index}")
        parts.extend(messages[key + suffix] for suffix in (".title", ".body"))
    for item in chapter.get("shortcuts", []):
        parts.extend((item["keys"], item["mac"]))
    return " ".join(parts).lower()


def tutorial(item: dict, code: str) -> str:
    name = f'{code}-{item["name"]}'
    caption = item["captions"][code]
    if code == "en" and item.get("chinese_ui"):
        caption += " Recorded with the Chinese interface; follow the steps above in English."
    if item.get("chinese_ui"):
        caption += (" 录屏中的工具位置可能与当前版本不同，请以本页文字步骤为准。" if code == "zh"
                    else " Tool positions may differ from the current version; follow the written steps on this page.")
    play, stop = (("播放演示", "停止并返回静态图") if code == "zh" else ("Play demo", "Stop and show still image"))
    full = "查看完整动图" if code == "zh" else "Open full animation"
    # The GIF is not requested until the reader explicitly starts it.
    return (f'<figure class="tutorial"><img src="../assets/tutorials/{name}.png" '
            f'data-still="../assets/tutorials/{name}.png" data-animation="../assets/tutorials/{name}.gif" '
            f'{image_size(HELP / item["posters"][code])} alt="{escape(caption)}" loading="lazy">'
            f'<figcaption>{escape(caption)}</figcaption><div class="tutorial-controls">'
            f'<button type="button" hidden aria-pressed="false" data-play="{play}" data-stop="{stop}">{play}</button>'
            f'<a href="../assets/tutorials/{name}.gif" target="_blank" rel="noopener">{full}</a>'
            '</div></figure>')


def icon(name: str) -> str:
    return f'<img src="../assets/icons/{escape(name)}.svg" alt="" aria-hidden="true">'


def site_header(code: str, section: str, chapter_id: str | None = None) -> str:
    """Keep navigation identical across the product site and both manual views."""
    prefix = "../" if section == "manual" or code == "en" else ""
    home = prefix + ("index.html" if code == "zh" else "en-us/index.html")
    manual = prefix + ("zh/index.html" if code == "zh" else "en/index.html")
    if section == "manual":
        other = "en" if code == "zh" else "zh"
        alternate = f"../{other}/{escape(chapter_id or 'index')}.html"
    else:
        alternate = prefix + ("en-us/index.html" if code == "zh" else "index.html")
    labels = {
        "zh": ("功能", "操作手册", "English", "主导航", "目录"),
        "en": ("Features", "Manual", "简体中文", "Main navigation", "Contents"),
    }[code]
    menu = (f'<button type="button" class="menu-toggle" aria-label="{labels[4]}" '
            'aria-expanded="false" aria-controls="sidebar"><span></span><span></span><span></span></button>'
            if chapter_id else "")
    active_manual = ' class="is-active" aria-current="location"' if section == "manual" else ""
    current_brand = ' aria-current="page"' if section == "product" else ""
    return (f'<header class="site-header"><div class="site-header-inner">{menu}'
            f'<a class="site-brand" href="{home}" aria-label="Voxenra"{current_brand}><img src="{prefix}assets/voxenra-mark.svg" alt=""><span>Voxenra</span></a>'
            f'<nav class="site-nav" aria-label="{labels[3]}">'
            f'<a class="site-nav-features" href="{home}#features">{labels[0]}</a>'
            f'<a{active_manual} href="{manual}">{labels[1]}</a>'
            '<a class="site-nav-github" href="https://github.com/l5769389/voxenra">GitHub</a>'
            f'<a class="site-nav-language" href="{alternate}" lang="{"en-US" if code == "zh" else "zh-CN"}">{labels[2]}</a>'
            '</nav></div></header>')


def figure(kind: str, messages: dict[str, str], language: dict[str, str]) -> str:
    """Portable diagram for the two QML canvas illustrations."""
    if kind == "segmentation":
        labels = [messages[f"text.{n}"] for n in ("0928", "0929", "0930", "0931", "0932", "0933", "0934")]
        drawing = '<path d="M80 86h180v100H80zM130 40h180v100H130zM80 86l50-46m130 46 50-46m-50 146 50-46" fill="none" stroke="#ef77e3" stroke-width="2"/>'
        coordinates = [(130, 208), (10, 135), (270, 30), (400, 67), (400, 102), (400, 137), (400, 172)]
    elif kind == "voi":
        labels = [messages[f"text.{n}"] for n in ("0935", "0936", "0937", "0938", "0939")]
        drawing = '<circle cx="130" cy="110" r="65" fill="none" stroke="#ef77e3" stroke-width="2"/><path d="M130 110h65" stroke="#61d7eb" stroke-width="2"/><ellipse cx="385" cy="110" rx="70" ry="40" fill="none" stroke="#61d7eb" stroke-width="2"/><circle cx="625" cy="95" r="62" fill="none" stroke="#ef77e3" stroke-width="2"/><circle cx="625" cy="95" r="32" fill="none" stroke="#61d7eb" stroke-width="2"/>'
        coordinates = [(75, 25), (140, 102), (50, 203), (310, 203), (520, 203)]
    else:
        raise ValueError(f"Unknown manual diagram: {kind}")
    text = "".join(f'<text x="{x}" y="{y}">{escape(label)}</text>' for label, (x, y) in zip(labels, coordinates))
    return f'<div class="figure" role="img" aria-label="{escape(language["figure"])}"><svg viewBox="0 0 760 220" xmlns="http://www.w3.org/2000/svg">{drawing}<g fill="#d8e4ed" font-size="13" font-family="system-ui,sans-serif">{text}</g></svg></div>'


def render_chapter(chapter: dict, messages: dict[str, str], language: dict[str, str], titles: dict[str, str], aliases: dict) -> str:
    chapter_id = chapter["id"]
    prefix = f"manual.{chapter_id}."
    title = messages[prefix + "title"]
    summary = messages[prefix + "summary"]
    category_title = messages["manual.category." + chapter["category"]]
    breadcrumb_middle = (f'<span aria-hidden="true">/</span><span>{escape(category_title)}</span>'
                         if category_title != title else "")
    content = [f'<nav class="breadcrumbs" aria-label="Breadcrumb"><a href="index.html">{escape(language["home"])}</a>{breadcrumb_middle}<span aria-hidden="true">/</span><span>{escape(title)}</span></nav>',
               f'<h1>{escape(title)}</h1>',
               f'<p class="summary">{escape(summary)}</p>']
    if chapter.get("shortcuts"):
        chips = []
        for index, item in enumerate(chapter["shortcuts"]):
            label = messages[item.get("messageId", prefix + f"shortcut{index}")]
            chips.append(f'<span class="shortcut"><span>{escape(label)}</span><span>Windows <kbd>{escape(item["keys"])}</kbd></span><span>macOS <kbd>{escape(item["mac"])}</kbd></span></span>')
        content.append(f'<div class="shortcuts" aria-label="{escape(language["shortcuts"])}">{"".join(chips)}</div>')
    images = [chapter["example"]] if "example" in chapter else chapter.get("examples", [])
    images = [name for name in images if not name.endswith(".gif")]
    if images:
        cards = []
        for index, image in enumerate(images):
            # The English screenshots are maintained separately in the same help bundle.
            folder = "en/" if language["pack"] == "en-US" else ""
            label = language["examples"][index] if len(images) > 1 else messages.get(prefix + "caption", title)
            cards.append(f'<figure><a href="../assets/help/{folder}{escape(image)}" target="_blank" rel="noopener"><img src="../assets/help/{folder}{escape(image)}" {image_size(HELP / folder / image)} alt="{escape(label)}" loading="lazy"></a><figcaption>{escape(label)}</figcaption></figure>')
        content.append(f'<div class="examples">{"".join(cards)}</div>')
    if chapter.get("figure"):
        content.append(figure(chapter["figure"], messages, language))
    chapter_tutorials = [item for item in load_json(HELP / "tutorials.json") if item["chapter"] == chapter_id]
    for index, section in enumerate(chapter["sections"]):
        key = section.get("messageId", prefix + f"section{index}")
        css = "step important" if section.get("important") else "step"
        code = "zh" if language["pack"] == "zh-CN" else "en"
        notice = ('<p class="notice-label">' + ("重要提示" if code == "zh" else "Important") + '</p>'
                  if section.get("important") else "")
        demos = "".join(tutorial(item, code) for item in chapter_tutorials if item["section"] == key)
        content.append(f'<section class="{css}" id="step-{index + 1}">{notice}<h2>{escape(messages[key + ".title"])}</h2>{paragraphs(messages[key + ".body"])}{demos}</section>')
    if chapter.get("related"):
        links = []
        for related in chapter["related"]:
            alias = aliases.get(related)
            target = (f'{alias["chapter"]}.html#step-{alias["section"] + 1}' if alias
                      else f"{related}.html")
            label = messages.get(f"manual.{related}.title", titles.get(related, related))
            links.append(f'<a href="{escape(target)}">{escape(label)} <span aria-hidden="true">↗</span></a>')
        content.append(f'<nav class="related" aria-label="{escape(language["related"])}"><h2>{escape(language["related"])}</h2><div>{"".join(links)}</div></nav>')
    return "\n".join(content)


def render_page(chapter: dict, categories: list[dict], chapters: list[dict], messages: dict[str, str], code: str, aliases: dict) -> str:
    language = LANGUAGES[code]
    titles = {item["id"]: messages[f'manual.{item["id"]}.title'] for item in chapters}
    groups = []
    for category in categories:
        links = []
        for item in chapters:
            if item["category"] != category["id"]:
                continue
            selected = ' aria-current="page" class="selected"' if item["id"] == chapter["id"] else ""
            searchable = chapter_search(item, messages)
            links.append(f'<a href="{escape(item["id"])}.html"{selected} data-search="{escape(searchable.lower())}">{escape(titles[item["id"]])}</a>')
        groups.append(f'<section class="nav-group"><h2>{escape(messages["manual.category." + category["id"]])}</h2>{"".join(links)}</section>')
    title = titles[chapter["id"]]
    nav = "\n".join(groups)
    article = render_chapter(chapter, messages, language, titles, aliases)
    header = site_header(code, "manual", chapter["id"])
    outline_links = []
    for index, section in enumerate(chapter["sections"]):
        key = section.get("messageId", f'manual.{chapter["id"]}.section{index}')
        outline_links.append(f'<a href="#step-{index + 1}">{escape(messages[key + ".title"])}</a>')
    outline = "".join(outline_links)
    compact_outline = f'<details class="compact-outline"><summary>{"本页内容 · 点击展开" if code == "zh" else "On this page"}</summary><nav>{outline}</nav></details>'
    summary_html = '<p class="summary">' + escape(messages[f'manual.{chapter["id"]}.summary']) + '</p>'
    article = article.replace(summary_html, summary_html + compact_outline, 1)
    return f'''<!doctype html>
<html lang="{language["pack"]}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="{escape(messages[f'manual.{chapter["id"]}.summary'])}">
<title>{escape(title)} · Voxenra {escape(language["site"])}</title>
<link rel="icon" href="../assets/voxenra-mark.svg" type="image/svg+xml"><link rel="stylesheet" href="{site_asset('../', 'site-shell.css')}"><link rel="stylesheet" href="{site_asset('../', 'manual.css')}">
<link rel="alternate" hreflang="zh-CN" href="../zh/{escape(chapter["id"])}.html"><link rel="alternate" hreflang="en-US" href="../en/{escape(chapter["id"])}.html">
</head><body>{header}
<div class="layout"><aside id="sidebar" class="sidebar"><div class="search"><label class="sr-only" for="manual-search">{escape(language["search"])}</label><input id="manual-search" type="search" placeholder="{escape(language["search"])}" autocomplete="off"></div><a class="sidebar-home" href="index.html">{escape(language["home"])}</a><nav aria-label="{escape(language["menu"])}">{nav}</nav><p class="no-results" hidden>{'没有匹配的章节' if code == 'zh' else 'No matching chapters'}</p></aside>
<main id="content"><div class="reading-layout"><article>{article}</article><aside class="page-outline"><h2>{'本页内容' if code == 'zh' else 'On this page'}</h2><nav>{outline}</nav></aside></div><footer>Voxenra · <a href="https://github.com/l5769389/voxenra">GitHub</a></footer></main></div>
<script src="{site_asset('../', 'manual.js')}" defer></script></body></html>'''


def render_landing(categories: list[dict], chapters: list[dict], messages: dict[str, str], code: str) -> str:
    language = LANGUAGES[code]
    heading = "操作手册" if code == "zh" else "Manual"
    description = ("从导入影像到测量、分割与导出，按任务查找操作步骤。" if code == "zh"
                   else "Find practical steps for importing, viewing, measuring, segmenting, and exporting medical images.")
    header = site_header(code, "manual")
    routes = (
        (("第一次使用", "打开影像、浏览并保存", "quick-start.html#step-1"),
         ("测量与标注", "看演示，跟着完成一次测量", "measurement.html#step-1"),
         ("自动分割", "配置环境、运行并检查结果", "segmentation.html#step-11"),
         ("遇到问题", "加载、恢复与失败处理", "faq.html#step-1"))
        if code == "zh" else
        (("First use", "Open, browse, and save", "quick-start.html#step-1"),
         ("Measure & annotate", "Follow the steps and demos", "measurement.html#step-1"),
         ("AI segmentation", "Set up, run, and review", "segmentation.html#step-11"),
         ("Get help", "Loading, recovery, and errors", "faq.html#step-1"))
    )
    start_links = ''.join(f'<a href="{url}"><strong>{title}</strong><span>{body}</span></a>' for title, body, url in routes)
    start = f'<nav class="start-routes" aria-label="{"按任务开始" if code == "zh" else "Start with a task"}">{start_links}</nav>'
    groups = []
    for category in categories:
        links = []
        for chapter in chapters:
            if chapter["category"] != category["id"]:
                continue
            title = messages[f'manual.{chapter["id"]}.title']
            searchable = chapter_search(chapter, messages)
            links.append(f'<a href="{escape(chapter["id"])}.html" data-search="{escape(searchable.lower())}">{escape(title)}</a>')
        groups.append(f'<section class="home-group">{icon(category["icon"])}<div><h2>{escape(messages["manual.category." + category["id"]])}</h2>{"".join(links)}</div></section>')
    return f'''<!doctype html><html lang="{language["pack"]}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="{escape(description)}"><title>Voxenra · {escape(heading)}</title>
<link rel="icon" href="../assets/voxenra-mark.svg" type="image/svg+xml"><link rel="stylesheet" href="{site_asset('../', 'site-shell.css')}"><link rel="stylesheet" href="{site_asset('../', 'manual.css')}">
<link rel="alternate" hreflang="zh-CN" href="../zh/index.html"><link rel="alternate" hreflang="en-US" href="../en/index.html"></head>
<body class="home">{header}
<main class="home-main"><div class="home-hero"><div class="home-copy"><span class="home-eyebrow">{'使用指南' if code == 'zh' else 'Documentation'}</span><h1>{escape(heading)}</h1><p>{escape(description)}</p><div class="home-search"><label class="sr-only" for="landing-search">{escape(language["search"])}</label><input id="landing-search" type="search" placeholder="{escape(language["search"])}" autocomplete="off"></div></div><figure class="home-visual"><img {product_image_attributes('../', 'hero-mpr.png', 'hero')} {product_image_size('hero-mpr.png')} fetchpriority="high" alt="{'Voxenra 多平面重建与三维视图' if code == 'zh' else 'Voxenra multiplanar and 3D views'}" loading="eager"></figure></div>
{start}<div class="home-directory" aria-label="{escape(language["menu"])}">{"".join(groups)}</div><p class="no-results" hidden>{'没有匹配的章节' if code == 'zh' else 'No matching chapters'}</p>
<footer>Voxenra · <a href="https://github.com/l5769389/voxenra">GitHub</a></footer></main><script src="{site_asset('../', 'manual.js')}" defer></script></body></html>'''


PRODUCT_COPY = {
    "zh": {
        'development_note': '本页包含当前开发版新增功能：DIMSE、工具栏自定义、窗模板收藏与视图区最大化。下方下载仍为正式版 v{version}，这些新增功能将在后续版本提供。',
        'pacs_title': '连接 DICOMweb 或传统 DICOM PACS',
        'pacs_body': '按服务器选择连接方式，查询检查、勾选序列并导入。DIMSE 使用 C-ECHO 测试连接、C-FIND 查询、C-MOVE 回传；请管理员先登记本机接收 AE、IP 和端口。连接测试成功后，仍需实际导入一个序列验证回传。',
        'pacs_captions': ('DIMSE 连接配置 · 合成数据演示', '本机 DIMSE 实际查询、选择与导入'),
        'pacs_link': '查看 PACS 配置与故障排查',
        'controls_title': '让常用工具更顺手',
        'controls_body': '按六类视图选择配置，直接拖动图标调整顺序或移入“更多”，保存后在重启时保留；对比模式与图像类型保持独立配置。收藏窗模板可优先显示，列表单独滚动。点击页签栏的最大化按钮或按 F12，收起两侧工具，专注影像。',
        'controls_captions': ('可视化拖拽工具栏 · 选择、拖动与保存', '最大化视图区 · 隐藏两侧并恢复原布局'),
        'controls_link': '查看工具栏设置教程',
        'favorites_link': '查看窗模板收藏示例',
        "lang": "zh-CN", "title": "Voxenra · DICOM 医学影像工作台",
        "description": "跨平台 DICOM 影像工作台：CT/MR/PET 阅片、MPR / CPR 与 3D、融合、测量分割和导出。支持基于 TotalSegmentator 的本地 AI 自动分割。",
        "features": "功能", "manual": "操作手册", "language": "English",
        "heading": "让医学影像工作更连贯", "intro": "导入 CT、MR 与 PET 影像，在同一工作区中完成阅片、重建、融合与分析。",
        "download": "下载应用", "explore": "阅读操作手册",
        "ai_highlight": "本地 AI 自动分割 · TotalSegmentator",
        "ai_caption": "合成模体流程演示：失败重试与成功导入；模拟推理输出，不表示模型精度或耗时。",
        "ai_scope": "需另行安装 TotalSegmentator 与 CT 快速模型；自动结果可核查和精修。",
        "topics": (("导入与工作区", "workflow"), ("PACS 连接", "pacs"), ("AI 自动分割", "ai"), ("阅片与重建", "viewing"), ("PET/CT 融合", "fusion"), ("测量与导出", "analysis"), ("阅片效率", "controls"), ("图像质量分析", "quality")),
        "workflow_title": "导入与工作区",
        "workflow_intro": "从获取影像到恢复工作状态，常用流程都在同一工作台中完成。",
        "workflow_cards": (
            ("本地导入", "文件、文件夹和压缩包可混合选择，也可拖入窗口。"),
            ("PACS 查询", "支持 DICOMweb 与传统 DICOM（DIMSE），查询检查并选择序列导入。"),
            ("工作区", "新建、保存与恢复工作区；关闭页签保留结果，重新打开可继续编辑。请同时保留原始影像。"),
        ),
        "workflow_images": (("拖拽 ZIP 压缩包导入", "feature-zip-drag.gif"), ("PACS 检索与序列选择", "feature-pacs.png"), ("保存与恢复工作区", "feature-workspace-overview.png")),
        "cpr_title": "沿路径查看曲面与横截面",
        "cpr_body": "在 CT 或 MR 参考影像中逐点绘制路径，按毫米定位横截面。锁定路径查看参考图，或返回已有测量的历史切面。路径支持编辑、撤销与工作区保存；物理测量在参考图和横截面完成。",
        "cpr_caption": "手动 CPR：参考平面、曲面图和横截面联动",
        "alt_cpr": "CPR 曲面重建与路径编辑界面",
        "viewing_title": "从二维切片到三维重建",
        "viewing_body": "查看原始切片并联动比较多组序列；通过 MPR、手动 CPR 曲面重建和 3D 体绘制查看空间结构，或同步播放 CT 多时相影像。常见彩色 DICOM 支持二维浏览与多帧播放。",
        "fusion_title": "PET/CT 联动融合",
        "fusion_body": "并排查看 CT、PET、融合与 MIP 视图，调整融合比例，并在需要时进行手动刚性配准。",
        "analysis_title": "测量、分割与结果交换",
        "ai_title": "本地 AI 自动分割 · TotalSegmentator",
        "ai_body": "连接独立安装的 TotalSegmentator，在 CT 的 MPR / 4D 中选择器官，快速分割当前时相。结果可继续精修、撤销并随工作区保存；环境与模型在设置中的 AI 页面配置。",
        "ai_link": "配置与使用教程",
        "analysis_body": "在列表中管理和定位长度、角度、曲线与 ROI 测量，导出附对应参考图的 PDF；支持阈值分割、画笔／橡皮精修、连通区域处理、轮廓与不透明度调节及 VOI 分析，通过 DICOM SEG 或 NRRD 与 Slicer 交换分割，并可导出 DICOM SR。",
        "viewing_caption": "MR 原始切片阅片", "viewing_4d_caption": "CT 多时相 4D 播放",
        "fusion_caption": "PET/CT 联动融合", "analysis_caption": "画笔、橡皮与撤销重做",
        "quality_title": "CT 图像质量分析",
        "quality_body": "水模 QA、点源 MTF 和斜坡线 FWHM 独立分析。QA 未识别水模时自动创建普通圆形 ROI，支持移动、复制、删除和撤销重做；曲线、层厚与统计结果随工作区保存。",
        "quality_captions": ("水模 QA · CT 值与均匀性", "点源 MTF · 曲线与指标"),
        "closing_title": "开始使用 Voxenra", "closing_body": "适用于 macOS Apple Silicon 与 Windows。",
        "mac_download": "下载 DMG", "win_setup": "下载安装版", "win_portable": "下载便携版",
        "mac_help": "适用于 Apple 芯片（M 系列），不适用于 Intel Mac。打开 DMG 后，将 Voxenra 拖入应用程序文件夹。",
        "win_help": "日常使用建议选安装版；便携版无需安装，保存 EXE 后直接运行。两者均适用于 64 位 Windows。",
        "first_run": "下载后从快速开始入门",
        "releases": "发布记录", "github": "GitHub 仓库", "alt_hero": "Voxenra 中的 MR 多平面重建与 3D 视图",
        "alt_viewing": "Voxenra 中的 MR 原始切片视图", "alt_fusion": "Voxenra 中的 CT、PET 与融合视图",
        "alt_analysis": "Voxenra 中的 MPR 分割与统计面板",
        "measurement_caption": "ROI 统计与测量结果列表",
        "appearance_title": "适合你的外观与操作习惯",
        "appearance_body": "支持深色、中性深灰与浅色主题；可调整界面大小、鼠标操作和工具快捷键，偏好在重启后保留。",
        "appearance_captions": ("深色", "中性深灰", "浅色"),
    },
    "en": {
        'development_note': 'This page includes current development features: DIMSE, customizable toolbars, favorite window presets and image-area maximization. Downloads below are still the stable v{version}; these additions will arrive in a later release.',
        'pacs_title': 'Connect to DICOMweb or traditional DICOM PACS',
        'pacs_body': 'Choose the server protocol, find a study, select series and import them. DIMSE uses C-ECHO to test the connection, C-FIND to query and C-MOVE for retrieval. Ask the administrator to register your receiver AE, IP and port. Import a small series after testing to verify the return route.',
        'pacs_captions': ('DIMSE connection settings · synthetic-data demonstration', 'Real query, selection and import with a local DIMSE peer'),
        'pacs_link': 'PACS setup and troubleshooting',
        'controls_title': 'Keep your reading tools within reach',
        'controls_body': 'Choose one of six view categories, drag icons to reorder or move them into More, and save the arrangement for future sessions. Comparison modes and image types retain independent configurations. Favorite window presets appear first and their list scrolls independently. Use the tab-bar maximize button or F12 to hide both sidebars and focus on the images.',
        'controls_captions': ('Visual toolbar editing · choose, drag and save', 'Maximize the image area and restore the previous layout'),
        'controls_link': 'Toolbar settings guide',
        'favorites_link': 'View favorite window presets',
        "lang": "en-US", "title": "Voxenra · DICOM imaging workspace",
        "description": "A cross-platform DICOM workspace for CT/MR/PET, MPR, 3D, fusion, segmentation and export. Supports local AI auto-segmentation with TotalSegmentator.",
        "features": "Features", "manual": "Manual", "language": "简体中文",
        "heading": "A connected workspace for medical imaging", "intro": "Import CT, MR, and PET studies, then view, reconstruct, fuse, and analyze them in one workspace.",
        "download": "Download", "explore": "Read the manual",
        "ai_highlight": "Local AI segmentation · TotalSegmentator",
        "ai_caption": "Synthetic phantom workflow demo (Chinese UI): failure, retry and successful import. Simulated inference output; not model accuracy or runtime.",
        "ai_scope": "Requires a separate TotalSegmentator environment and CT fast model. Review and refine automatic results.",
        "topics": (("Import & workspace", "workflow"), ("PACS connections", "pacs"), ("AI segmentation", "ai"), ("Viewing & reconstruction", "viewing"), ("PET/CT fusion", "fusion"), ("Measurement & export", "analysis"), ("Reading controls", "controls"), ("Image-quality analysis", "quality")),
        "workflow_title": "Import and workspace",
        "workflow_intro": "Bring images in, then pick up your work where you left off.",
        "workflow_cards": (
            ("Local import", "Select files, folders, and archives together, or drag them into the window."),
            ("PACS query", "Use DICOMweb or traditional DICOM (DIMSE) to find studies and import selected series."),
            ("Workspace", "Create, save and restore workspaces; reopen closed tabs with their results. Keep the original image files alongside the workspace."),
        ),
        "workflow_images": (("Drag a ZIP archive to import", "feature-zip-drag.gif"), ("PACS search and series selection", "feature-pacs.png"), ("Save and restore a workspace", "feature-workspace-overview.png")),
        "cpr_title": "Follow a path through curved and cross-sectional views",
        "cpr_body": "Trace a path on CT or MR images and enter a distance in mm to locate a cross-section. Browse locked reference images or return to the original plane of a saved measurement. Edit or undo path changes and save them in a workspace. Physical measurements use reference planes and cross-sections.",
        "cpr_caption": "Manual CPR with linked reference planes, curved image, and cross-section",
        "alt_cpr": "CPR reconstruction and path editing interface",
        "viewing_title": "From 2D slices to 3D reconstruction",
        "viewing_body": "Read original slices and compare linked series. Explore spatial structures with MPR, manual CPR paths, and volume rendering, or play multi-phase CT in sync. Common color DICOM also supports 2D viewing and multi-frame playback.",
        "fusion_title": "Linked PET/CT fusion",
        "fusion_body": "See linked CT, PET, fused, and MIP views, adjust blending, and perform manual rigid registration when needed.",
        "analysis_title": "Measurement, segmentation, and DICOM results",
        "ai_title": "Local AI segmentation · TotalSegmentator",
        "ai_body": "Connect a separately installed TotalSegmentator environment, select organs in CT MPR / 4D, and segment the current phase in fast mode. Refine, undo, and save results in a workspace. Configure the environment and models under Settings → AI.",
        "ai_link": "Setup and workflow guide",
        "analysis_body": "Manage and locate length, angle, curve, and ROI measurements in a list, then export PDF reports with matching reference images. Refine segments with paint, erase, and connected-region tools; adjust outlines and fill opacity. Use thresholding and VOI analysis, exchange segments with Slicer through NRRD or DICOM SEG, and export DICOM SR.",
        "viewing_caption": "MR original-slice viewing", "viewing_4d_caption": "Multi-phase CT 4D playback",
        "fusion_caption": "Linked PET/CT fusion", "analysis_caption": "Paint, erase, undo and redo",
        "quality_title": "CT image-quality analysis",
        "quality_body": "Analyze water-phantom QA, point-source MTF and ramp FWHM separately. When no phantom is detected, QA creates ordinary circular ROIs that you can move, duplicate, delete, undo and redo. Save curves, slice thickness and statistics in the workspace.",
        "quality_captions": ("Water-phantom QA · CT values and uniformity", "Point-source MTF · curve and metrics"),
        "closing_title": "Get started with Voxenra", "closing_body": "Available for macOS Apple Silicon and Windows.",
        "mac_download": "Download DMG", "win_setup": "Download installer", "win_portable": "Download portable",
        "mac_help": "For Apple silicon (M-series), not Intel Macs. Open the DMG, then drag Voxenra into Applications.",
        "win_help": "Choose the installer for everyday use. The portable EXE runs without installation. Both require 64-bit Windows.",
        "first_run": "After downloading, follow Quick start",
        "releases": "Releases", "github": "GitHub repository", "alt_hero": "MR multiplanar and 3D views in Voxenra",
        "alt_viewing": "MR original-slice view in Voxenra", "alt_fusion": "CT, PET, and fused views in Voxenra",
        "alt_analysis": "MPR segmentation and statistics panel in Voxenra",
        "measurement_caption": "ROI statistics and measurement list",
        "appearance_title": "Appearance and controls",
        "appearance_body": "Choose dark, neutral gray, or light, and customize interface size, mouse bindings, and tool shortcuts. Preferences persist after restart.",
        "appearance_captions": ("Dark", "Neutral gray", "Light"),
    },
}


def render_product_home(code: str, release: dict[str, str]) -> str:
    copy = PRODUCT_COPY[code]
    header = site_header(code, "product")
    heading = "让医学影像<br>工作更连贯" if code == "zh" else escape(copy["heading"])
    prefix = "" if code == "zh" else "../"
    other_home = "en-us/index.html" if code == "zh" else "index.html"
    manual_home = "zh/index.html" if code == "zh" else "en/index.html"
    download_base = f'https://github.com/l5769389/voxenra/releases/download/{quote(release["tag"], safe="")}/'
    mac_url = escape(download_base + quote(release["macos"], safe=""))
    win_setup_url = escape(download_base + quote(release["windows_installer"], safe=""))
    win_portable_url = escape(download_base + quote(release["windows_portable"], safe=""))
    version = escape('v' + release["version"])
    development_notice = (f'<p class="development-note product-container">{escape(copy["development_note"].format(version=release["version"]))}</p>'
                          if release["version"] == "2.1.3" else "")
    ai_image = product_image_asset(prefix, "feature-ai-segmentation.gif")
    ai_still = ", ".join(f"{url} {width}w" for width, url in product_image_sources(prefix, "feature-ai-segmentation.png"))
    feature_rows = [f'''<section class="product-feature product-feature-wide" id="ai">
<div class="product-feature-copy"><h2>{escape(copy["ai_title"])}</h2><p>{escape(copy["ai_body"])}</p></div>
<figure><a href="{ai_image}" target="_blank" rel="noopener"><picture><source media="(prefers-reduced-motion: reduce)" srcset="{ai_still}" sizes="{PRODUCT_IMAGE_SIZES["wide"]}"><img {product_image_attributes(prefix, "feature-ai-segmentation.gif", "wide")} {product_image_size("feature-ai-segmentation.gif")} alt="{escape(copy["ai_caption"])}" loading="lazy"></picture></a><figcaption>{escape(copy["ai_caption"])}</figcaption></figure>
<div class="ai-details"><p>{escape(copy["ai_scope"])}</p><a href="{prefix}{code}/segmentation.html#step-11">{escape(copy["ai_link"])}</a></div></section>''']
    # New workflow captures have real, separately recorded English interfaces.
    media_prefix = 'en-' if code == 'en' else ''
    workflow_features = {}
    for key, media, guide in (
        ('pacs', ('feature-dimse-settings.png', 'feature-dimse-import.gif'), 'pacs.html'),
        ('controls', ('feature-toolbar.gif', 'feature-focus.gif'), 'settings.html'),
    ):
        figures = []
        for name, caption in zip(media, copy[key + '_captions'], strict=True):
            name = media_prefix + name
            still = ''
            if name.endswith('.gif'):
                poster = ', '.join(f'{url} {width}w' for width, url in product_image_sources(prefix, name[:-4] + '.png'))
                still = f'<source media="(prefers-reduced-motion: reduce)" srcset="{poster}" sizes="{PRODUCT_IMAGE_SIZES["half"]}">'
            figures.append(f'<figure><a href="{product_image_asset(prefix, name)}" target="_blank" rel="noopener">'
                           f'<picture>{still}<img {product_image_attributes(prefix, name)} {product_image_size(name)} '
                           f'alt="{escape(caption)}" loading="lazy"></picture></a><figcaption>{escape(caption)}</figcaption></figure>')
        extra = (f'<a href="{product_image_asset(prefix, media_prefix + "feature-window-favorites.png")}" target="_blank" rel="noopener">'
                 f'{escape(copy["favorites_link"])}</a> · ' if key == 'controls' else '')
        workflow_features[key] = (f'<section class="product-feature product-feature-wide" id="{key}">'
                            f'<div class="product-feature-copy"><h2>{escape(copy[key + "_title"])}</h2><p>{escape(copy[key + "_body"])}</p></div>'
                            f'<div class="feature-media-grid">{"".join(figures)}</div><div class="ai-details">{extra}'
                                 f'<a href="{prefix}{code}/{guide}">{escape(copy[key + "_link"])}</a></div></section>')
    for key, image in (("viewing", "feature-mr-reading.png"), ("cpr", media_prefix + "feature-cpr-reference.png"), ("fusion", "feature-fusion.png"), ("analysis", "feature-analysis.gif")):
        title = escape(copy[key + "_title"])
        image_url = product_image_asset(prefix, image)
        if key in ("viewing", "analysis"):
            media = (
                (("feature-mr-reading.png", copy["viewing_caption"]),
                 ("feature-4d.gif", copy["viewing_4d_caption"]))
                if key == "viewing" else
                (("feature-measurements.png", copy["measurement_caption"]),
                 (image, copy["analysis_caption"]))
            )
            figures = []
            for asset, caption in media:
                url = product_image_asset(prefix, asset)
                figures.append(f'<figure><a href="{url}" target="_blank" rel="noopener"><img {product_image_attributes(prefix, asset)} {product_image_size(asset)} alt="{escape(caption)}" loading="lazy"></a><figcaption>{escape(caption)}</figcaption></figure>')
            feature_rows.append(f'''<section class="product-feature product-feature-wide" id="{key}">
<div class="product-feature-copy"><h2>{title}</h2><p>{escape(copy[key + "_body"])}</p></div>
<div class="feature-media-grid">{"".join(figures)}</div></section>''')
            continue
        feature_rows.append(f'''<section class="product-feature" id="{key}">
<div class="product-feature-copy"><h2>{title}</h2><p>{escape(copy[key + "_body"])}</p></div>
<figure><a href="{image_url}" target="_blank" rel="noopener"><img {product_image_attributes(prefix, image, "hero")} {product_image_size(image)} alt="{escape(copy["alt_" + key])}" loading="lazy"></a><figcaption>{escape(copy[key + "_caption"])}</figcaption></figure></section>''')
    feature_rows.insert(0, workflow_features['pacs'])
    feature_rows.append(workflow_features['controls'])
    topics = "".join(f'<a href="#{anchor}">{escape(label)}</a>' for label, anchor in copy["topics"])
    workflow_cards = []
    for (title, body), (caption, image) in zip(copy["workflow_cards"], copy["workflow_images"], strict=True):
        image_url = product_image_asset(prefix, image)
        full_image_url = product_image_asset(prefix, "feature-zip-drop.png") if image == "feature-zip-drag.gif" else image_url
        full_image_label = ("查看大图：" if code == "zh" else "View full image: ") + caption
        workflow_cards.append(
            f'<article class="workflow-card"><h3>{escape(title)}</h3><p>{escape(body)}</p>'
            f'<figure class="workflow-image"><a href="{full_image_url}" target="_blank" rel="noopener" '
            f'aria-label="{escape(full_image_label)}"><span class="workflow-image-frame">'
            f'<img {product_image_attributes(prefix, image, "third")} {product_image_size(image)} alt="{escape(caption)}" loading="lazy"></span></a>'
            f'<figcaption>{escape(caption)}</figcaption></figure></article>'
        )
    quality_images = []
    for caption, image in zip(copy["quality_captions"], ("feature-water-qa.png", "feature-mtf.png"), strict=True):
        image_url = product_image_asset(prefix, image)
        full_image_label = ("查看大图：" if code == "zh" else "View full image: ") + caption
        quality_images.append(
            f'<figure class="quality-image"><a href="{image_url}" target="_blank" rel="noopener" '
            f'aria-label="{escape(full_image_label)}"><span class="quality-image-frame">'
            f'<img {product_image_attributes(prefix, image)} {product_image_size(image)} alt="{escape(caption)}" loading="lazy"></span></a>'
            f'<figcaption>{escape(caption)}</figcaption></figure>'
        )
    theme_images = []
    for caption, image in zip(copy["appearance_captions"], (
        "feature-theme-dark.png", "feature-theme-graphite.png", "feature-theme-light.png",
    ), strict=True):
        image_url = product_image_asset(prefix, image)
        theme_images.append(
            f'<figure><a href="{image_url}" target="_blank" rel="noopener">'
            f'<img {product_image_attributes(prefix, image, "third")} {product_image_size(image)} alt="{escape(caption)}" loading="lazy"></a>'
            f'<figcaption>{escape(caption)}</figcaption></figure>'
        )
    return f'''<!doctype html><html lang="{copy["lang"]}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="{escape(copy["description"])}"><title>{escape(copy["title"])}</title>
<link rel="icon" href="{prefix}assets/voxenra-mark.svg" type="image/svg+xml"><link rel="stylesheet" href="{site_asset(prefix, 'site-shell.css')}"><link rel="stylesheet" href="{site_asset(prefix, 'product.css')}">
<link rel="alternate" hreflang="zh-CN" href="{prefix}index.html"><link rel="alternate" hreflang="en-US" href="{prefix}en-us/index.html"></head>
<body><a class="skip-link" href="#main">{'跳转到正文' if code == 'zh' else 'Skip to content'}</a>{header}
<main id="main"><section class="product-hero product-container"><div class="hero-copy"><h1>{heading}</h1><p>{escape(copy["intro"])}</p><a class="ai-highlight" href="#ai">{escape(copy["ai_highlight"])}</a><div class="product-actions"><a class="primary-action" href="#download">{escape(copy["download"])}</a><a class="text-action" href="{prefix}{manual_home}">{escape(copy["explore"])}</a></div></div>
<figure class="hero-visual"><img {product_image_attributes(prefix, 'hero-mpr.png', 'hero')} {product_image_size("hero-mpr.png")} alt="{escape(copy["alt_hero"])}" fetchpriority="high"><figcaption class="sr-only">{escape(copy["alt_hero"])}</figcaption></figure></section>
<nav class="product-topics product-container" aria-label="{escape(copy["features"])}">{topics}</nav>
{development_notice}
<div id="features"><section class="product-workflow product-container" id="workflow"><div class="workflow-heading"><h2>{escape(copy["workflow_title"])}</h2><p>{escape(copy["workflow_intro"])}</p></div><div class="workflow-grid">{"".join(workflow_cards)}</div></section>
<div class="product-features product-container">{"".join(feature_rows)}</div>
<section class="product-quality product-container" id="quality"><div class="product-feature-copy"><h2>{escape(copy["quality_title"])}</h2><p>{escape(copy["quality_body"])}</p></div><div class="feature-media-grid">{"".join(quality_images)}</div></section>
<section class="product-appearance product-container" id="appearance"><div class="product-feature-copy"><h2>{escape(copy["appearance_title"])}</h2><p>{escape(copy["appearance_body"])}</p></div>
<div class="theme-media-grid">{"".join(theme_images)}</div></section></div>
<section class="product-closing product-container" id="download"><h2>{escape(copy["closing_title"])}</h2><p>{escape(copy["closing_body"])}</p>
<div class="download-platforms"><div class="download-platform"><img src="{prefix}assets/macos.svg" alt=""><h3>macOS</h3><p>Apple Silicon · {version}</p><div class="download-links"><a href="{mac_url}">{escape(copy["mac_download"])}</a></div><p class="download-help">{escape(copy["mac_help"])}</p></div>
<div class="download-platform"><img src="{prefix}assets/windows.svg" alt=""><h3>Windows</h3><p>x64 · {version}</p><div class="download-links"><a href="{win_setup_url}">{escape(copy["win_setup"])}</a><a href="{win_portable_url}">{escape(copy["win_portable"])}</a></div><p class="download-help">{escape(copy["win_help"])}</p></div></div>
<a class="closing-manual" href="{prefix}{code}/quick-start.html">{escape(copy["first_run"])}</a></section></main>
<footer class="product-footer"><div class="product-container"><div><strong>Voxenra</strong><p>{escape(copy["description"])}</p></div><nav aria-label="{'页脚' if code == 'zh' else 'Footer'}"><a href="https://github.com/l5769389/voxenra">{escape(copy["github"])}</a><a href="{prefix}{manual_home}">{escape(copy["manual"])}</a><a href="https://github.com/l5769389/voxenra/releases">{escape(copy["releases"])}</a><a href="{prefix}{other_home}">{escape(copy["language"])}</a></nav></div></footer></body></html>'''


def build(output: Path) -> None:
    manifest = load_json(HELP / "manual.json")
    categories = manifest["categories"]
    chapters = [chapter for category in categories for chapter in load_json(HELP / category["file"])]
    if len({item["id"] for item in chapters}) != len(chapters):
        raise ValueError("Duplicate manual chapter IDs")
    known_ids = {item["id"] for item in chapters}
    aliases = manifest["aliases"]
    for chapter in chapters:
        if any(related not in known_ids and related not in aliases for related in chapter.get("related", [])):
            raise ValueError(f'Unknown related chapter in {chapter["id"]}')
    release = load_json(SITE / "release.json")
    if release["tag"] != "v" + release["version"] or any(
        not re.fullmatch(r"[A-Za-z0-9._-]+", release[key])
        for key in ("macos", "windows_installer", "windows_portable")
    ):
        raise ValueError("Invalid product release metadata")
    output.mkdir(parents=True, exist_ok=True)
    asset_output = output / "assets"
    asset_output.mkdir(exist_ok=True)
    shutil.copy2(ASSETS / "brand/voxenra-mark.svg", asset_output / "voxenra-mark.svg")
    for target, source in PRODUCT_SCREENSHOTS.items():
        shutil.copy2(ROOT / "docs/screenshots" / source, asset_output / target)
        for _, filename, data in product_image_variants(target):
            (asset_output / filename).write_bytes(data)
    for name in ("site-shell.css", "manual.css", "manual.js"):
        shutil.copy2(SITE / name, asset_output / name)
    shutil.copy2(SITE / "product.css", asset_output / "product.css")
    for name in ("macos.svg", "windows.svg"):
        shutil.copy2(SITE / name, asset_output / name)
    used_icons = {item["icon"] for item in categories}
    (asset_output / "icons").mkdir(exist_ok=True)
    for name in used_icons:
        shutil.copy2(ASSETS / "icons" / f"{name}.svg", asset_output / "icons" / f"{name}.svg")
    used_images = {name for chapter in chapters for name in ([chapter["example"]] if "example" in chapter else chapter.get("examples", []))}
    for name in used_images:
        for prefix in ("", "en/"):
            destination = asset_output / "help" / prefix / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(HELP / prefix / name, destination)
    tutorial_output = asset_output / "tutorials"
    tutorial_output.mkdir(exist_ok=True)
    for item in load_json(HELP / "tutorials.json"):
        chapter = next(ch for ch in chapters if ch["id"] == item["chapter"])
        if not any(s.get("messageId", f'manual.{chapter["id"]}.section{i}') == item["section"]
                   for i, s in enumerate(chapter["sections"])):
            raise ValueError(f'Unknown tutorial section: {item["section"]}')
        for code in LANGUAGES:
            shutil.copy2(HELP / item["sources"][code], tutorial_output / f'{code}-{item["name"]}.gif')
            shutil.copy2(HELP / item["posters"][code], tutorial_output / f'{code}-{item["name"]}.png')
    (output / ".nojekyll").touch()
    (output / "index.html").write_text(render_product_home("zh", release), encoding="utf-8")
    (output / "en-us").mkdir(exist_ok=True)
    (output / "en-us/index.html").write_text(render_product_home("en", release), encoding="utf-8")
    for code, language in LANGUAGES.items():
        messages = load_json(ASSETS / "languages" / f'{language["pack"]}.json')["messages"]
        directory = output / code
        directory.mkdir(exist_ok=True)
        for chapter in chapters:
            (directory / f'{chapter["id"]}.html').write_text(render_page(chapter, categories, chapters, messages, code, aliases), encoding="utf-8")
        (directory / "index.html").write_text(render_landing(categories, chapters, messages, code), encoding="utf-8")
    print(f"Built {len(chapters)} chapters in {len(LANGUAGES)} languages at {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="Output directory for static pages")
    build(parser.parse_args().output)
