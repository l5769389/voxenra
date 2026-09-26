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
PRODUCT_SCREENSHOTS = {
    "hero-mpr.png": "11-mpr-3d-layout.png",
    "feature-mr-reading.png": "07-mr-reading.png",
    "feature-fusion.png": "05-pet-ct-fusion.png",
    "feature-analysis.png": "02-mpr-segmentation.png",
    "feature-pacs.png": "16-pacs-browser.png",
    "feature-zip-drop.png": "35-zip-drop.png",
    "feature-zip-drag.gif": "06-zip-drag.gif",
    "feature-workspace.png": "36-workspace-full.png",
    "feature-4d.gif": "03-4d-playback.gif",
    "feature-water-qa.png": "19-water-qa.png",
    "feature-mtf.png": "28-mtf-analysis.png",
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
<main class="home-main"><div class="home-hero"><div class="home-copy"><span class="home-eyebrow">{'使用指南' if code == 'zh' else 'Documentation'}</span><h1>{escape(heading)}</h1><p>{escape(description)}</p><div class="home-search"><label class="sr-only" for="landing-search">{escape(language["search"])}</label><input id="landing-search" type="search" placeholder="{escape(language["search"])}" autocomplete="off"></div></div><figure class="home-visual"><img src="{product_image_asset('../', 'hero-mpr.png')}" alt="{'Voxenra 多平面重建与三维视图' if code == 'zh' else 'Voxenra multiplanar and 3D views'}" loading="eager"></figure></div>
<div class="home-directory" aria-label="{escape(language["menu"])}">{"".join(groups)}</div><p class="no-results" hidden>{'没有匹配的章节' if code == 'zh' else 'No matching chapters'}</p>
<footer>Voxenra · <a href="https://github.com/l5769389/voxenra">GitHub</a></footer></main><script src="{site_asset('../', 'manual.js')}" defer></script></body></html>'''


PRODUCT_COPY = {
    "zh": {
        "lang": "zh-CN", "title": "Voxenra · DICOM 医学影像工作台",
        "description": "跨平台 DICOM 影像工作台：本地与 PACS 导入、工作区保存、CT/MR/PET 阅片、MPR 与 3D、融合、测量分割、CT 图像质量分析和导出。",
        "features": "功能", "manual": "操作手册", "language": "English",
        "heading": "让医学影像工作更连贯", "intro": "导入 CT、MR 与 PET 影像，在同一工作区中完成阅片、重建、融合与分析。",
        "download": "下载应用", "explore": "阅读操作手册",
        "topics": (("导入与工作区", "workflow"), ("阅片与重建", "viewing"), ("PET/CT 融合", "fusion"), ("测量与导出", "analysis"), ("图像质量分析", "quality")),
        "workflow_title": "导入与工作区",
        "workflow_intro": "从获取影像到恢复工作状态，常用流程都在同一工作台中完成。",
        "workflow_cards": (
            ("本地导入", "文件、文件夹和压缩包可混合选择，也可拖入窗口。"),
            ("PACS 查询", "连接 DICOMweb PACS，查询检查并选择序列导入。"),
            ("工作区", "保存布局、测量与分析结果，并恢复上次选中的工具。"),
        ),
        "workflow_images": (("拖拽 ZIP 压缩包导入", "feature-zip-drag.gif"), ("PACS 检索与序列选择", "feature-pacs.png"), ("保存与恢复工作区", "feature-workspace.png")),
        "viewing_title": "从二维切片到三维重建",
        "viewing_body": "查看原始切片并联动比较多组序列；通过 MPR、斜面重建和 3D 体绘制查看空间结构，或同步播放 CT 多时相影像。常见彩色 DICOM 支持二维浏览与多帧播放。",
        "fusion_title": "PET/CT 联动融合",
        "fusion_body": "并排查看 CT、PET、融合与 MIP 视图，调整融合比例，并在需要时进行手动刚性配准。",
        "analysis_title": "测量、分割与结果交换",
        "analysis_body": "在列表中管理和定位长度、角度、曲线与 ROI 测量，导出附对应参考图的 PDF；支持阈值分割、VOI 分析及 DICOM SEG 导入导出和 DICOM SR 导出。",
        "viewing_caption": "MR 原始切片阅片", "viewing_4d_caption": "CT 多时相 4D 播放",
        "fusion_caption": "PET/CT 联动融合", "analysis_caption": "MPR 分割与统计",
        "quality_title": "CT 图像质量分析",
        "quality_body": "水模 QA、点源 MTF 和斜坡线 FWHM 各自独立分析；曲线、层厚与统计指标随工作区保存，重新打开后保留原值，可主动重新计算。",
        "quality_captions": ("水模 QA · CT 值与均匀性", "点源 MTF · 曲线与指标"),
        "closing_title": "开始使用 Voxenra", "closing_body": "适用于 macOS Apple Silicon 与 Windows。",
        "mac_download": "下载 DMG", "win_setup": "下载安装版", "win_portable": "下载便携版",
        "releases": "发布记录", "github": "GitHub 仓库", "alt_hero": "Voxenra 中的 MR 多平面重建与 3D 视图",
        "alt_viewing": "Voxenra 中的 MR 原始切片视图", "alt_fusion": "Voxenra 中的 CT、PET 与融合视图",
        "alt_analysis": "Voxenra 中的 MPR 分割与统计面板",
    },
    "en": {
        "lang": "en-US", "title": "Voxenra · DICOM imaging workspace",
        "description": "A cross-platform DICOM workspace for local and PACS import, CT/MR/PET viewing, MPR and 3D, fusion, measurement, segmentation, CT image-quality analysis, and export.",
        "features": "Features", "manual": "Manual", "language": "简体中文",
        "heading": "A connected workspace for medical imaging", "intro": "Import CT, MR, and PET studies, then view, reconstruct, fuse, and analyze them in one workspace.",
        "download": "Download", "explore": "Read the manual",
        "topics": (("Import & workspace", "workflow"), ("Viewing & reconstruction", "viewing"), ("PET/CT fusion", "fusion"), ("Measurement & export", "analysis"), ("Image-quality analysis", "quality")),
        "workflow_title": "Import and workspace",
        "workflow_intro": "Bring images in, then pick up your work where you left off.",
        "workflow_cards": (
            ("Local import", "Select files, folders, and archives together, or drag them into the window."),
            ("PACS query", "Connect to a DICOMweb PACS, find studies, and import selected series."),
            ("Workspace", "Preserve layouts, measurements, analysis results, and the selected tools."),
        ),
        "workflow_images": (("Drag a ZIP archive to import", "feature-zip-drag.gif"), ("PACS search and series selection", "feature-pacs.png"), ("Save and restore a workspace", "feature-workspace.png")),
        "viewing_title": "From 2D slices to 3D reconstruction",
        "viewing_body": "Read original slices and compare linked series. Explore spatial structures with MPR, oblique views, and volume rendering, or play multi-phase CT in sync. Common color DICOM also supports 2D viewing and multi-frame playback.",
        "fusion_title": "Linked PET/CT fusion",
        "fusion_body": "See linked CT, PET, fused, and MIP views, adjust blending, and perform manual rigid registration when needed.",
        "analysis_title": "Measurement, segmentation, and DICOM results",
        "analysis_body": "Manage and locate length, angle, curve, and ROI measurements in a list, then export PDF reports with matching reference images. Threshold segmentation, VOI analysis, DICOM SEG import/export, and DICOM SR export support result exchange.",
        "viewing_caption": "MR original-slice viewing", "viewing_4d_caption": "Multi-phase CT 4D playback",
        "fusion_caption": "Linked PET/CT fusion", "analysis_caption": "MPR segmentation and statistics",
        "quality_title": "CT image-quality analysis",
        "quality_body": "Analyze water-phantom QA, point-source MTF, and ramp FWHM separately. Save curves, slice thickness, and metrics in the workspace. Restore recorded results and recalculate when needed.",
        "quality_captions": ("Water-phantom QA · CT values and uniformity", "Point-source MTF · curve and metrics"),
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
        image_url = product_image_asset(prefix, image)
        if key == "viewing":
            feature_rows.append(f'''<section class="product-feature product-feature-viewing" id="viewing">
<div class="product-feature-copy"><h2>{title}</h2><p>{escape(copy["viewing_body"])}</p></div>
<div class="feature-media-grid"><figure><img src="{image_url}" alt="{escape(copy["alt_viewing"])}" loading="lazy"><figcaption>{escape(copy["viewing_caption"])}</figcaption></figure>
<figure><img src="{product_image_asset(prefix, 'feature-4d.gif')}" alt="{escape(copy["viewing_4d_caption"])}" loading="lazy"><figcaption>{escape(copy["viewing_4d_caption"])}</figcaption></figure></div></section>''')
            continue
        feature_rows.append(f'''<section class="product-feature" id="{key}">
<div class="product-feature-copy"><h2>{title}</h2><p>{escape(copy[key + "_body"])}</p></div>
<figure><img src="{image_url}" alt="{escape(copy["alt_" + key])}" loading="lazy"><figcaption>{escape(copy[key + "_caption"])}</figcaption></figure></section>''')
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
            f'<img src="{image_url}" alt="{escape(caption)}" loading="lazy"></span></a>'
            f'<figcaption>{escape(caption)}</figcaption></figure></article>'
        )
    quality_images = []
    for caption, image in zip(copy["quality_captions"], ("feature-water-qa.png", "feature-mtf.png"), strict=True):
        image_class = "quality-image quality-image-mtf" if image == "feature-mtf.png" else "quality-image"
        image_url = product_image_asset(prefix, image)
        full_image_label = ("查看大图：" if code == "zh" else "View full image: ") + caption
        quality_images.append(
            f'<figure class="{image_class}"><a href="{image_url}" target="_blank" rel="noopener" '
            f'aria-label="{escape(full_image_label)}"><span class="quality-image-frame">'
            f'<img src="{image_url}" alt="{escape(caption)}" loading="lazy"></span></a>'
            f'<figcaption>{escape(caption)}</figcaption></figure>'
        )
    return f'''<!doctype html><html lang="{copy["lang"]}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="{escape(copy["description"])}"><title>{escape(copy["title"])}</title>
<link rel="icon" href="{prefix}assets/voxenra-mark.svg" type="image/svg+xml"><link rel="stylesheet" href="{site_asset(prefix, 'site-shell.css')}"><link rel="stylesheet" href="{site_asset(prefix, 'product.css')}">
<link rel="alternate" hreflang="zh-CN" href="{prefix}index.html"><link rel="alternate" hreflang="en-US" href="{prefix}en-us/index.html"></head>
<body><a class="skip-link" href="#main">{'跳转到正文' if code == 'zh' else 'Skip to content'}</a>{header}
<main id="main"><section class="product-hero product-container"><div class="hero-copy"><h1>{heading}</h1><p>{escape(copy["intro"])}</p><div class="product-actions"><a class="primary-action" href="#download">{escape(copy["download"])}</a><a class="text-action" href="{prefix}{manual_home}">{escape(copy["explore"])}</a></div></div>
<figure class="hero-visual"><img src="{product_image_asset(prefix, 'hero-mpr.png')}" alt="{escape(copy["alt_hero"])}" fetchpriority="high"><figcaption class="sr-only">{escape(copy["alt_hero"])}</figcaption></figure></section>
<nav class="product-topics product-container" aria-label="{escape(copy["features"])}">{topics}</nav>
<div id="features"><section class="product-workflow product-container" id="workflow"><div class="workflow-heading"><h2>{escape(copy["workflow_title"])}</h2><p>{escape(copy["workflow_intro"])}</p></div><div class="workflow-grid">{"".join(workflow_cards)}</div></section>
<div class="product-features product-container">{"".join(feature_rows)}</div>
<section class="product-quality product-container" id="quality"><div class="product-feature-copy"><h2>{escape(copy["quality_title"])}</h2><p>{escape(copy["quality_body"])}</p></div><div class="feature-media-grid">{"".join(quality_images)}</div></section></div>
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
    for target, source in PRODUCT_SCREENSHOTS.items():
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
