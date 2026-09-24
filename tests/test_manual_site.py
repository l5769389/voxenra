"""Check that the published manual stays complete and self-contained."""

from html.parser import HTMLParser
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from urllib.parse import urlsplit
import json


ROOT = Path(__file__).resolve().parents[1]
SPEC = spec_from_file_location("build_manual_site", ROOT / "scripts/build_manual_site.py")
SITE = module_from_spec(SPEC)
SPEC.loader.exec_module(SITE)


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        for name in ("href", "src"):
            if name in attributes:
                self.references.append(attributes[name])


def test_generated_manual_has_all_chapters_and_local_assets(tmp_path):
    SITE.build(tmp_path)
    manifest = json.loads((SITE.HELP / "manual.json").read_text(encoding="utf-8"))
    chapter_ids = [chapter["id"] for category in manifest["categories"]
                   for chapter in json.loads((SITE.HELP / category["file"]).read_text(encoding="utf-8"))]
    for language in ("zh", "en"):
        pages = list((tmp_path / language).glob("*.html"))
        assert len(pages) == len(chapter_ids) + 1
        landing = (tmp_path / language / "index.html").read_text(encoding="utf-8")
        assert "site-shell.css" in landing
        assert "manual.css?v=" in landing
        assert 'class="site-header"' in landing
        assert 'class="site-nav"' in landing
        assert 'class="home-visual"' in landing
        assert 'hero-mpr.png' in landing
        assert ('入门与导入' if language == 'zh' else 'Getting started &amp; importing') in landing
        assert landing.count('href="quick-start.html"') == 1
        assert landing.count('data-search=') == len(chapter_ids)
        for chapter_id in chapter_ids:
            page = tmp_path / language / f"{chapter_id}.html"
            source = page.read_text(encoding="utf-8")
            assert "<h1>" in source
            assert 'class="step' in source
            assert 'class="site-header"' in source
            links = Links()
            links.feed(source)
            for reference in links.references:
                parsed = urlsplit(reference)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                target = (page.parent / parsed.path).resolve()
                assert target.is_relative_to(tmp_path.resolve()), reference
                assert target.is_file(), f"{page}: {reference}"
                if parsed.fragment:
                    assert f'id="{parsed.fragment}"' in target.read_text(encoding="utf-8")
    assert "快速开始" in (tmp_path / "zh/quick-start.html").read_text(encoding="utf-8")
    assert "Quick start" in (tmp_path / "en/quick-start.html").read_text(encoding="utf-8")


def test_product_home_is_bilingual_and_keeps_manual_urls(tmp_path):
    SITE.build(tmp_path)
    release = json.loads((SITE.SITE / "release.json").read_text(encoding="utf-8"))
    for page, heading, manual in (
        (tmp_path / "index.html", "让医学影像工作更连贯", "zh/index.html"),
        (tmp_path / "en-us/index.html", "A connected workspace for medical imaging", "en/index.html"),
    ):
        source = page.read_text(encoding="utf-8")
        assert heading in source.replace("<br>", "")
        assert "#download" in source
        assert "v" + release["version"] in source
        for key in ("macos", "windows_installer", "windows_portable"):
            assert f'/releases/download/{release["tag"]}/{release[key]}' in source
        assert manual in source
        assert "hero-mpr.png" in source
        assert "feature-fusion.png" in source
        assert "feature-pacs.png?v=" in source
        assert "feature-workspace.png?v=" in source
        assert 'class="workflow-media-grid"' in source
        assert "feature-4d.gif" in source
        assert "feature-water-qa.png" in source
        assert "feature-mtf.png" in source
        assert 'feature-mtf.png?v=' in source
        assert 'class="product-quality product-container"' in source
        assert source.count('href="#quality"') == 1
        assert ('图像质量分析</a>' if page.parent == tmp_path else 'Image-quality analysis</a>') in source
        assert source.count('class="product-topics product-container"') == 1
        assert source.count('class="feature-media-grid"') == 2
        assert ("从二维切片到三维重建" if page.parent == tmp_path else "From 2D slices to 3D reconstruction") in source
        assert ("DICOM SR" if page.parent == tmp_path else "DICOM SR") in source
        assert 'id="workflow"' in source
        assert 'class="workflow-grid"' in source
        assert ("PACS 查询" if page.parent == tmp_path else "PACS query") in source
        assert 'class="site-header"' in source
        assert "site-shell.css?v=" in source
        assert "product.css?v=" in source
        links = Links()
        links.feed(source)
        for reference in links.references:
            parsed = urlsplit(reference)
            if parsed.scheme or parsed.netloc:
                continue
            target = (page.parent / parsed.path).resolve() if parsed.path else page
            assert target.is_relative_to(tmp_path.resolve()), reference
            assert target.is_file(), f"{page}: {reference}"
            if parsed.fragment:
                assert f'id="{parsed.fragment}"' in target.read_text(encoding="utf-8")
    assert (tmp_path / "zh/index.html").is_file()
    assert (tmp_path / "en/index.html").is_file()


def test_manual_rich_text_escapes_untrusted_markup():
    assert SITE.rich("<script>x</script> **重点** `Ctrl+O`") == (
        "&lt;script&gt;x&lt;/script&gt; <strong>重点</strong> <strong>Ctrl+O</strong>"
    )
