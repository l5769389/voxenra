"""Build the product website and manual from the desktop app's content."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src/qt_dicom_viewer/qml/assets"
HELP = ASSETS / "help"
SITE = ROOT / "docs/manual-site"
LANGUAGES = {
    "zh": {"pack": "zh-CN", "name": "简体中文", "search": "搜索章节与正文", "menu": "目录", "site": "操作手册", "home": "手册首页", "related": "相关章节", "shortcuts": "快捷键", "figure": "示意图", "examples": ("CT 示例", "PET 示例"), "repo": "GitHub 仓库"},
    "en": {"pack": "en-US", "name": "English", "search": "Search chapters and content", "menu": "Contents", "site": "Manual", "home": "Manual home", "related": "Related chapters", "shortcuts": "Shortcuts", "figure": "Diagram", "examples": ("CT example", "PET example"), "repo": "GitHub repository"},
}


def site_asset(prefix: str, name: str) -> str:
    """Change the URL when CSS or JS changes so cached layouts stay in sync."""
    digest = hashlib.sha256((SITE / name).read_bytes()).hexdigest()[:12]
    return f"{prefix}assets/{name}?v={digest}"


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
        "zh": ("产品主页", "功能", "操作手册", "English", "主导航", "目录"),
        "en": ("Product home", "Features", "Manual", "简体中文", "Main navigation", "Contents"),
    }[code]
    menu = (f'<button type="button" class="menu-toggle" aria-label="{labels[5]}" '
            'aria-expanded="false" aria-controls="sidebar"><span></span><span></span><span></span></button>'
            if chapter_id else "")
    active_home = ' class="is-active" aria-current="location"' if section == "product" else ' class="site-nav-home"'
    active_manual = ' class="is-active" aria-current="location"' if section == "manual" else ""
    return (f'<header class="site-header"><div class="site-header-inner">{menu}'
            f'<a class="site-brand" href="{home}" aria-label="Voxenra"><img src="{prefix}assets/voxenra-mark.svg" alt=""><span>Voxenra</span></a>'
            f'<nav class="site-nav" aria-label="{labels[4]}">'
            f'<a{active_home} href="{home}">{labels[0]}</a>'
            f'<a class="site-nav-features" href="{home}#features">{labels[1]}</a>'
            f'<a{active_manual} href="{manual}">{labels[2]}</a>'
            '<a class="site-nav-github" href="https://github.com/l5769389/voxenra">GitHub</a>'
            f'<a class="site-nav-language" href="{alternate}" lang="{"en-US" if code == "zh" else "zh-CN"}">{labels[3]}</a>'
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
            chips.append(f'<span class="shortcut"><span>{escape(label)}</span><kbd>{escape(item["keys"])}</kbd><kbd>{escape(item["mac"])}</kbd></span>')
        content.append(f'<div class="shortcuts" aria-label="{escape(language["shortcuts"])}">{"".join(chips)}</div>')
    images = [chapter["example"]] if "example" in chapter else chapter.get("examples", [])
    if images:
        cards = []
        for index, image in enumerate(images):
            # The English screenshots are maintained separately in the same help bundle.
            folder = "en/" if language["pack"] == "en-US" else ""
            label = language["examples"][index] if len(images) > 1 else messages.get(prefix + "caption", title)
            cards.append(f'<figure><a href="../assets/help/{folder}{escape(image)}" target="_blank" rel="noopener"><img src="../assets/help/{folder}{escape(image)}" alt="{escape(label)}" loading="lazy"></a><figcaption>{escape(label)}</figcaption></figure>')
        content.append(f'<div class="examples">{"".join(cards)}</div>')
    if chapter.get("figure"):
        content.append(figure(chapter["figure"], messages, language))
    for index, section in enumerate(chapter["sections"]):
        key = section.get("messageId", prefix + f"section{index}")
        css = "step important" if section.get("important") else "step"
        content.append(f'<section class="{css}" id="step-{index + 1}"><h2>{escape(messages[key + ".title"])}</h2><p>{rich(messages[key + ".body"])}</p></section>')
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
            searchable = " ".join([titles[item["id"]], messages[f'manual.{item["id"]}.summary']] +
                                  [messages[section.get("messageId", f'manual.{item["id"]}.section{i}') + ".body"] for i, section in enumerate(item["sections"])])
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
    groups = []
    for category in categories:
        links = []
        for chapter in chapters:
            if chapter["category"] != category["id"]:
                continue
            title = messages[f'manual.{chapter["id"]}.title']
            searchable = " ".join([title, messages[f'manual.{chapter["id"]}.summary']] +
                                  [messages[section.get("messageId", f'manual.{chapter["id"]}.section{i}') + ".body"] for i, section in enumerate(chapter["sections"])])
            links.append(f'<a href="{escape(chapter["id"])}.html" data-search="{escape(searchable.lower())}">{escape(title)}</a>')
        groups.append(f'<section class="home-group">{icon(category["icon"])}<div><h2>{escape(messages["manual.category." + category["id"]])}</h2>{"".join(links)}</div></section>')
    return f'''<!doctype html><html lang="{language["pack"]}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="{escape(description)}"><title>Voxenra · {escape(heading)}</title>
<link rel="icon" href="../assets/voxenra-mark.svg" type="image/svg+xml"><link rel="stylesheet" href="{site_asset('../', 'site-shell.css')}"><link rel="stylesheet" href="{site_asset('../', 'manual.css')}">
<link rel="alternate" hreflang="zh-CN" href="../zh/index.html"><link rel="alternate" hreflang="en-US" href="../en/index.html"></head>
<body class="home">{header}
<main class="home-main"><div class="home-hero"><div class="home-copy"><span class="home-eyebrow">{'使用指南' if code == 'zh' else 'Documentation'}</span><h1>{escape(heading)}</h1><p>{escape(description)}</p><div class="home-search"><label class="sr-only" for="landing-search">{escape(language["search"])}</label><input id="landing-search" type="search" placeholder="{escape(language["search"])}" autocomplete="off"></div></div><figure class="home-visual"><img src="../assets/hero-mpr.png" alt="{'Voxenra 多平面重建与三维视图' if code == 'zh' else 'Voxenra multiplanar and 3D views'}" loading="eager"></figure></div>
<div class="home-directory" aria-label="{escape(language["menu"])}">{"".join(groups)}</div><p class="no-results" hidden>{'没有匹配的章节' if code == 'zh' else 'No matching chapters'}</p>
<footer>Voxenra · <a href="https://github.com/l5769389/voxenra">GitHub</a></footer></main><script src="{site_asset('../', 'manual.js')}" defer></script></body></html>'''


PRODUCT_COPY = {
    "zh": {
        "lang": "zh-CN", "title": "Voxenra · DICOM 医学影像工作台",
        "description": "跨平台 DICOM 影像工作台：本地与 PACS 导入、工作区保存、CT/MR/PET 阅片、MPR 与 3D、融合、测量分割和导出。",
        "features": "功能", "manual": "操作手册", "language": "English",
        "heading": "让医学影像工作更连贯", "intro": "导入 CT、MR 与 PET 影像，在同一工作区中完成阅片、重建、融合与分析。",
        "download": "下载应用", "explore": "阅读操作手册",
        "topics": (("导入与工作区", "workflow"), ("阅片与重建", "viewing"), ("PET/CT 融合", "fusion"), ("测量与导出", "analysis")),
        "workflow_title": "导入与工作区",
        "workflow_intro": "从获取影像到恢复工作状态，常用流程都在同一工作台中完成。",
        "workflow_cards": (
            ("本地导入", "文件、文件夹和压缩包可混合选择，也可拖入窗口。"),
            ("PACS 查询", "连接 DICOMweb PACS，查询检查并选择序列导入。"),
            ("工作区", "保存页签、布局和操作状态，下次继续处理。"),
        ),
        "viewing_title": "从切片到三维，保持空间语境",
        "viewing_body": "查看原始切片并联动比较多组序列；用 MPR、斜面重建和 3D 体绘制探索空间结构，CT 多时相可同步播放。",
        "fusion_title": "在同一视图中理解解剖与代谢",
        "fusion_body": "并排查看 CT、PET、融合与 MIP 视图，调整融合比例，并在需要时进行手动刚性配准。",
        "analysis_title": "让测量与结果留在影像语境中",
        "analysis_body": "使用长度、角度、曲线及 ROI 测量，进行阈值分割与 VOI 分析；导出 DICOM SEG、结构化测量报告及常用图像和表格格式。",
        "viewing_caption": "MR 原始切片阅片", "fusion_caption": "PET/CT 联动融合", "analysis_caption": "MPR 分割与统计",
        "closing_title": "开始使用 Voxenra", "closing_body": "适用于 macOS Apple Silicon 与 Windows。",
        "mac_download": "下载 DMG", "win_setup": "下载安装版", "win_portable": "下载便携版",
        "releases": "发布记录", "github": "GitHub 仓库", "alt_hero": "Voxenra 中的 MR 多平面重建与 3D 视图",
        "alt_viewing": "Voxenra 中的 MR 原始切片视图", "alt_fusion": "Voxenra 中的 CT、PET 与融合视图",
        "alt_analysis": "Voxenra 中的 MPR 分割与统计面板",
    },
    "en": {
        "lang": "en-US", "title": "Voxenra · DICOM imaging workspace",
        "description": "A cross-platform DICOM workspace for local and PACS import, CT/MR/PET viewing, MPR and 3D, fusion, measurement, segmentation, and export.",
        "features": "Features", "manual": "Manual", "language": "简体中文",
        "heading": "A connected workspace for medical imaging", "intro": "Import CT, MR, and PET studies, then view, reconstruct, fuse, and analyze them in one workspace.",
        "download": "Download", "explore": "Read the manual",
        "topics": (("Import & workspace", "workflow"), ("Viewing & reconstruction", "viewing"), ("PET/CT fusion", "fusion"), ("Measurement & export", "analysis")),
        "workflow_title": "Import and workspace",
        "workflow_intro": "Bring images in, then pick up your work where you left off.",
        "workflow_cards": (
            ("Local import", "Select files, folders, and archives together, or drag them into the window."),
            ("PACS query", "Connect to a DICOMweb PACS, find studies, and import selected series."),
            ("Workspace", "Save tabs, layouts, and work state so you can continue later."),
        ),
        "viewing_title": "Keep spatial context from slices to 3D",
        "viewing_body": "Read original slices and compare linked series. Explore anatomy with MPR, oblique views, and volume rendering, or play multi-phase CT in sync.",
        "fusion_title": "View anatomy and metabolism together",
        "fusion_body": "See linked CT, PET, fused, and MIP views, adjust blending, and perform manual rigid registration when needed.",
        "analysis_title": "Keep results connected to the image",
        "analysis_body": "Measure lengths, angles, curves, and ROIs; work with threshold segments and VOIs; export DICOM SEG, structured measurement reports, images, and tables.",
        "viewing_caption": "MR original-slice viewing", "fusion_caption": "Linked PET/CT fusion", "analysis_caption": "MPR segmentation and statistics",
        "closing_title": "Get started with Voxenra", "closing_body": "Available for macOS Apple Silicon and Windows.",
        "mac_download": "Download DMG", "win_setup": "Download installer", "win_portable": "Download portable",
        "releases": "Releases", "github": "GitHub repository", "alt_hero": "MR multiplanar and 3D views in Voxenra",
        "alt_viewing": "MR original-slice view in Voxenra", "alt_fusion": "CT, PET, and fused views in Voxenra",
        "alt_analysis": "MPR segmentation and statistics panel in Voxenra",
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
    feature_rows = []
    for key, image in (("viewing", "feature-mr-reading.png"), ("fusion", "feature-fusion.png"), ("analysis", "feature-analysis.png")):
        title = escape(copy[key + "_title"])
        if code == "zh":
            title = {
                "viewing": "从切片到三维，<br>保持空间语境",
                "fusion": "在同一视图中<br>理解解剖与代谢",
                "analysis": "让测量与结果<br>留在影像语境中",
            }[key]
        feature_rows.append(f'''<section class="product-feature" id="{key}">
<div class="product-feature-copy"><h2>{title}</h2><p>{escape(copy[key + "_body"])}</p></div>
<figure><img src="{prefix}assets/{image}" alt="{escape(copy["alt_" + key])}" loading="lazy"><figcaption>{escape(copy[key + "_caption"])}</figcaption></figure></section>''')
    topics = "".join(f'<a href="#{anchor}">{escape(label)}</a>' for label, anchor in copy["topics"])
    workflow_cards = "".join(
        f'<article class="workflow-card"><h3>{escape(title)}</h3><p>{escape(body)}</p></article>'
        for title, body in copy["workflow_cards"]
    )
    return f'''<!doctype html><html lang="{copy["lang"]}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="{escape(copy["description"])}"><title>{escape(copy["title"])}</title>
<link rel="icon" href="{prefix}assets/voxenra-mark.svg" type="image/svg+xml"><link rel="stylesheet" href="{site_asset(prefix, 'site-shell.css')}"><link rel="stylesheet" href="{site_asset(prefix, 'product.css')}">
<link rel="alternate" hreflang="zh-CN" href="{prefix}index.html"><link rel="alternate" hreflang="en-US" href="{prefix}en-us/index.html"></head>
<body><a class="skip-link" href="#main">{'跳转到正文' if code == 'zh' else 'Skip to content'}</a>{header}
<main id="main"><section class="product-hero product-container"><div class="hero-copy"><h1>{heading}</h1><p>{escape(copy["intro"])}</p><div class="product-actions"><a class="primary-action" href="#download">{escape(copy["download"])}</a><a class="text-action" href="{prefix}{manual_home}">{escape(copy["explore"])}</a></div></div>
<figure class="hero-visual"><img src="{prefix}assets/hero-mpr.png" alt="{escape(copy["alt_hero"])}" fetchpriority="high"><figcaption class="sr-only">{escape(copy["alt_hero"])}</figcaption></figure></section>
<nav class="product-topics product-container" aria-label="{escape(copy["features"])}">{topics}</nav>
<div id="features"><section class="product-workflow product-container" id="workflow"><div class="workflow-heading"><h2>{escape(copy["workflow_title"])}</h2><p>{escape(copy["workflow_intro"])}</p></div><div class="workflow-grid">{workflow_cards}</div></section>
<div class="product-features product-container">{"".join(feature_rows)}</div></div>
<section class="product-closing product-container" id="download"><h2>{escape(copy["closing_title"])}</h2><p>{escape(copy["closing_body"])}</p>
<div class="download-platforms"><div class="download-platform"><img src="{prefix}assets/macos.svg" alt=""><h3>macOS</h3><p>Apple Silicon · {version}</p><div class="download-links"><a href="{mac_url}">{escape(copy["mac_download"])}</a></div></div>
<div class="download-platform"><img src="{prefix}assets/windows.svg" alt=""><h3>Windows</h3><p>x64 · {version}</p><div class="download-links"><a href="{win_setup_url}">{escape(copy["win_setup"])}</a><a href="{win_portable_url}">{escape(copy["win_portable"])}</a></div></div></div>
<a class="closing-manual" href="{prefix}{manual_home}">{escape(copy["explore"])}</a></section></main>
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
    screenshots = {
        "hero-mpr.png": "11-mpr-3d-layout.png",
        "feature-mr-reading.png": "07-mr-reading.png",
        "feature-fusion.png": "05-pet-ct-fusion.png",
        "feature-analysis.png": "02-mpr-segmentation.png",
    }
    for target, source in screenshots.items():
        shutil.copy2(ROOT / "docs/screenshots" / source, asset_output / target)
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
