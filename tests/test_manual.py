"""Offline manual resources, singleton navigation and real workspace rendering."""
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import pytest
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtTest import QTest

from qt_dicom_viewer.ui.controller.manual_tab_controller import ManualTabController, manual_content, manual_rich_text
from qt_dicom_viewer.ui.svg_icon_provider import render_icon
from test_dicom_tags import qt_app, wait_until
from test_pacs_qml import scene
from test_series_sidebar import sidebar_scene
from test_tag_qml import find, click, type_text, descendants

ROOT = Path(__file__).resolve().parents[1]
QML = ROOT / 'src/qt_dicom_viewer/qml'


def test_manual_content_and_bundled_resources(qt_app):
    content = manual_content()
    categories = {c['id'] for c in content['categories']}
    chapters = content['chapters']
    assert len(categories) == 8 and len({c['id'] for c in chapters}) == len(chapters)
    assert next(c for c in content['categories'] if c['id'] == 'start')['title'] != next(
        c for c in chapters if c['id'] == 'quick-start')['title']
    assert {'workspace', 'measurement-report'} <= {c['id'] for c in chapters}
    resources = {f.text for f in ET.parse(ROOT / 'Voxenra.qrc').iter('file')}
    expected = {'assets/help/manual.json', 'assets/icons/manual.svg'}
    expected.update('assets/help/' + c['file'] for c in content['categories'])
    expected.add('sections/manual/ManualNavigation.qml')
    valid_ids = {c['id'] for c in chapters} | set(content['aliases'])
    for category in content['categories']:
        expected.add('assets/icons/' + category['icon'] + '.svg')
    for alias in content['aliases'].values():
        target = next(c for c in chapters if c['id'] == alias['chapter'])
        assert 0 <= alias['section'] < len(target['sections'])
    for chapter in chapters:
        assert chapter['category'] in categories
        assert chapter['title'] and all(s['title'] and s['body'] for s in chapter['sections'])
        assert chapter['summary']
        assert set(chapter.get('related', [])) <= valid_ids
        expected.add('assets/icons/' + chapter['icon'] + '.svg')
        for example in chapter.get('examples', []) + ([chapter['example']] if chapter.get('example') else []):
            expected.add('assets/help/' + example)
    for path in expected:
        assert (QML / path).is_file()
        assert 'src/qt_dicom_viewer/qml/' + path in resources
    for size in (18, 36):
        image = render_icon('manual', '#aabcc8', 'transparent', size, size)
        assert not image.isNull() and image.width() == size


def test_manual_emphasis_preserves_literal_html_and_searchable_shortcuts(qt_app):
    assert manual_rich_text('选择 **调窗**，按 `Enter`。\nA < B & C') == (
        '选择 <b>调窗</b>，按 <b>Enter</b>。<br>A &lt; B &amp; C')
    assert manual_rich_text('**<img src="file:///private/image">**') == (
        '<b>&lt;img src=&quot;file:///private/image&quot;&gt;</b>')
    assert manual_rich_text('**未完成\n**') == '**未完成<br>**'
    controller = ManualTabController()
    for term, chapter_id in [('Ctrl+V', 'measurement-edit'), ('⌘S', 'workspace'), ('自动恢复', 'workspace')]:
        controller.setSearch(term)
        assert chapter_id in [c['id'] for group in controller.navigation for c in group['chapters']]
    controller.selectChapter('export')
    assert any(s.get('important') and '<b>' in s['bodyHtml'] for s in controller.currentChapter['sections'])


def test_language_pack_tutorial_animation_and_english_switch(scene):
    window, app, warnings = scene
    window.resize(1440, 900)
    app.workspaceController.openManual('language-packs')
    controller = app.workspaceController.manualController
    wait_until(lambda: find(window, 'manualExample').property('frameCount') == 5)
    example = find(window, 'manualExample')
    assert find(window, 'manualChapterTitle').property('text') == '新增语言包'
    frame = example.property('currentFrame')
    wait_until(lambda: example.property('currentFrame') != frame)
    click(window, find(window, 'manualScreenshotButton'))
    preview = window.findChild(QObject, 'manualScreenshotPreview')
    wait_until(lambda: preview.property('visible'))
    full = preview.findChild(QObject, 'manualFullScreenshot')
    assert full.property('frameCount') == 5 and full.property('playing')
    assert not example.property('playing')
    QTest.keyClick(full.window(), Qt.Key_Escape)
    wait_until(lambda: not preview.property('visible'))

    app.languageController.selectLanguage('en-US')
    wait_until(lambda: find(window, 'manualChapterTitle').property('text') == 'Add a language pack')
    assert controller.chapterId == 'language-packs'
    assert controller.currentChapter['example'] == 'en/language-pack.gif'
    assert 'Restart and select' in controller.currentChapter['sections'][3]['title']
    assert example.property('source').toString().endswith('/en/language-pack.gif')
    controller.setSearch('language pack')
    assert 'language-packs' in [c['id'] for group in controller.navigation for c in group['chapters']]
    app.languageController.selectLanguage('zh-CN')
    wait_until(lambda: find(window, 'manualChapterTitle').property('text') == '新增语言包')
    assert controller.currentChapter['example'] == 'language-pack.gif'
    assert not warnings, warnings


def test_manual_shortcuts_screenshot_zoom_and_related_chapter(sidebar_scene, tmp_path):
    window, app, _, warnings = sidebar_scene
    window.resize(1000, 600)
    ws = app.workspaceController
    ws.openManual('measurement-edit')
    QTest.qWait(100)
    shortcut = find(window, 'manualShortcut-0')
    assert shortcut.property('keys') == ('⌘C' if sys.platform == 'darwin' else 'Ctrl+C')
    body = find(window, 'manualSectionBody-0')
    assert ('<b>' in body.property('text') or 'font-weight:700' in body.property('text'))
    assert '**' not in body.property('text')
    assert body.property('paintedWidth') <= body.width() + 1
    reading = find(window, 'manualReadingArea')
    before = reading.property('contentY')
    assert window.grabWindow().save(str(tmp_path/'manual-shortcuts.png'))
    click(window, find(window, 'manualScreenshotButton'))
    preview = window.findChild(QObject, 'manualScreenshotPreview')
    wait_until(lambda: preview.property('visible'))
    image = preview.findChild(QObject, 'manualFullScreenshot')
    native = image.window()
    assert native is not window
    assert image.property('sourceSize').width() > 0
    assert preview.property('width') <= window.width() - 32
    assert preview.property('height') <= window.height() - 32
    button = preview.findChild(QObject, 'manualScreenshotOriginalSize')
    click(native, button)
    assert button.property('checked')
    assert image.width() == image.property('sourceSize').width()
    assert native.grabWindow().save(str(tmp_path/'manual-original-screenshot.png'))
    QTest.keyClick(native, Qt.Key_Escape)
    wait_until(lambda: not preview.property('visible'))
    assert reading.property('contentY') == before
    reading.setProperty('contentY', reading.property('contentHeight') - reading.height())
    QTest.qWait(50)
    click(window, find(window, 'manualRelated-measurement-style'))
    wait_until(lambda: ws.manualController.chapterId == 'measurement-roi')
    QTest.qWait(100)
    assert reading.property('contentY') > 0
    section = find(window, 'manualSection-4')
    assert section.mapToScene(QPointF()).y() < reading.mapToScene(QPointF(0, reading.height())).y()
    assert window.grabWindow().save(str(tmp_path/'manual-rich-layout.png'))
    assert not warnings, warnings


def test_manual_navigation_groups_search_aliases_and_width_persist(scene):
    from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
    window, app, warnings = scene
    window.resize(1440, 900)
    app.workspaceController.openManual()
    controller = app.workspaceController.manualController
    QTest.qWait(80)
    assert [g['id'] for g in controller.navigation if g['expanded']] == ['start']
    click(window, find(window, 'manualCategory-start'))
    assert not any(g['expanded'] for g in controller.navigation)
    controller.setSearch('比例尺')
    assert all(g['expanded'] for g in controller.navigation)
    assert 'corners' in [c['id'] for g in controller.navigation for c in g['chapters']]
    controller.setSearch('')
    assert not any(g['expanded'] for g in controller.navigation)

    for old_id, alias in manual_content()['aliases'].items():
        app.workspaceController.openManual(old_id)
        wait_until(lambda: not find(window, 'operationManual').property('restoring'))
        assert controller.chapterId == alias['chapter']
        assert next(g for g in controller.navigation
                    if g['id'] == controller.currentChapter['category'])['expanded']
        reading = find(window, 'manualReadingArea')
        section = find(window, 'manualSection-' + str(alias['section']))
        assert 0 <= section.mapToItem(reading, QPointF()).y() < reading.height()

    app.languageController.selectLanguage('en-US')
    scroll = find(window, 'manualNavigationScroll').property('contentItem')
    def selected_is_visible():
        button = find(window, 'manualChapter-' + controller.chapterId)
        top = button.mapToItem(scroll, QPointF()).y()
        return 0 <= top and top + button.height() <= scroll.height() + 1
    wait_until(selected_is_visible)

    navigation = find(window, 'manualNavigation')
    assert navigation.width() == 260
    handle = find(window, 'manualNavigationResizeHandle')
    start = handle.mapToScene(QPointF(4, 160)).toPoint()
    end = start + QPointF(70, 0).toPoint()
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(window, end, 40)
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
    QTest.qWait(80)
    assert navigation.width() == 330
    assert SettingsController(path=app.settingsController._path).section('layout')['manualNavigationWidth'] == 330
    window.resize(960, 720)
    QTest.qWait(60)
    assert find(window, 'manualReadingArea').width() >= 360
    assert controller.navigationWidth == 330
    window.resize(1440, 900)
    QTest.qWait(60)
    assert navigation.width() == 330
    assert not warnings, warnings


def test_manual_search_and_reading_state(qt_app):
    controller = ManualTabController()
    assert controller.chapterId == 'quick-start'
    controller.selectChapter('measurement')
    controller.setScrollPosition(120)
    controller.setScrollPosition(float('nan'))
    assert controller.scrollPosition == 120
    controller.setSearch('控制点')
    ids = [c['id'] for group in controller.navigation for c in group['chapters']]
    assert 'measurement-edit' in ids
    controller.setSearch('no-such-manual-topic')
    assert controller.navigation == [] and controller.chapterId == 'measurement'
    controller.setSearch('')
    assert len(controller.navigation) == 8
    controller.selectChapter('measurement')
    assert controller.scrollPosition == 0
    controller.selectChapter('not-found')
    assert controller.chapterId == 'quick-start'


def test_manual_empty_workspace_singleton_mru_and_export(scene):
    window, app, warnings = scene
    ws = app.workspaceController
    book, settings = find(window, 'sidebarManual'), find(window, 'sidebarSettings')
    assert (book.width(), book.height()) == (28, 28)
    assert settings.mapToScene(QPointF()).x() - book.mapToScene(QPointF(book.width(), 0)).x() == 4
    assert find(window, 'sidebarSettingsFooter').height() == 36
    click(window, book)
    assert ws.activeTabType == 'manual' and ws.activeViewport is None
    assert ws.currentTabAllViewports == [] and len(ws.tabs) == 1
    assert not any(i.isVisible() and i.objectName() == 'rightPanel' for i in descendants(window.contentItem()))
    assert app.exportController.current_series() == []
    manual = ws.manualController
    click(window, find(window, 'sidebarManual'))
    assert ws.manualController is manual and len(ws.tabs) == 1
    ws.openSettings()
    ws.openPacs()
    ws.openManual('measurement')
    assert len(ws.tabs) == 3 and ws.manualController is manual
    ws.closeTab('workspace-settings')
    assert ws.activeTabType == 'manual'
    ws.closeTab('workspace-manual')
    assert ws.activeTabType == 'pacs' and ws.manualController is None
    ws.openManual()
    assert ws.manualController.chapterId == 'quick-start'
    ws.closeTab('workspace-pacs')
    ws.closeTab('workspace-manual')
    QTest.qWait(40)
    assert not ws.tabs and ws.activeViewport is None
    assert not warnings, warnings


def test_manual_search_scroll_restore_and_context_jump(scene):
    window, app, warnings = scene
    window.resize(1000, 600)
    ws = app.workspaceController
    ws.openManual('measurement')
    QTest.qWait(80)
    wait_until(lambda: not find(window, 'operationManual').property('restoring'))
    reading = find(window, 'manualReadingArea')
    assert reading.property('contentHeight') > reading.height() + 150
    reading.setProperty('contentY', 140)
    QTest.qWait(20)
    assert ws.manualController.scrollPosition == 140
    ws.openManual()
    assert reading.property('contentY') == 140
    ws.openPacs()
    QTest.qWait(40)
    ws.openManual()
    QTest.qWait(80)
    wait_until(lambda: not find(window, 'operationManual').property('restoring'))
    assert find(window, 'manualReadingArea').property('contentY') == 140
    reading = find(window, 'manualReadingArea')
    ws.openManual('voi')
    # Switching chapters must not persist a clamp from the previous article.
    assert ws.manualController.scrollPosition == 0
    assert reading.property('contentY') == 0
    wait_until(lambda: not find(window, 'operationManual').property('restoring'))
    assert ws.manualController.scrollPosition == 0
    assert find(window, 'manualReadingArea').property('contentY') == 0
    type_text(window, find(window, 'manualSearch'), 'ROI')
    assert ws.manualController.search == 'ROI'
    selected = find(window, 'manualChapter-measurement-roi')
    click(window, selected)
    assert ws.manualController.chapterId == 'measurement-roi'
    ws.openManual('quick-start')
    QTest.qWait(60)
    assert find(window, 'manualSearch').property('text') == ''
    assert not warnings, warnings


@pytest.mark.parametrize('size', [(1280, 720), (1440, 900)])
def test_manual_all_chapters_layout_and_examples(scene, size, tmp_path):
    window, app, warnings = scene
    window.resize(*size)
    ws = app.workspaceController
    ws.openManual()
    QTest.qWait(80)
    navigation = find(window, 'manualNavigation')
    reading = find(window, 'manualReadingArea')
    assert navigation.mapToScene(QPointF(navigation.width(), 0)).x() <= reading.mapToScene(QPointF()).x()
    for chapter in manual_content()['chapters']:
        ws.openManual(chapter['id'])
        wait_until(lambda: not find(window, 'operationManual').property('restoring'))
        assert find(window, 'manualChapterTitle').property('text') == chapter['title']
        assert reading.property('contentY') == 0
        assert reading.property('contentWidth') == reading.width()
        for item in (navigation, reading):
            point = item.mapToScene(QPointF(item.width(), item.height()))
            assert point.x() <= size[0] and point.y() <= size[1]
        if chapter.get('example') or chapter.get('examples'):
            assert find(window, 'manualExample').property('sourceSize').width() > 0
        for index, section in enumerate(chapter['sections']):
            body = find(window, 'manualSectionBody-' + str(index))
            assert body.property('paintedWidth') <= body.width() + 1, chapter['id']
            if section.get('important'):
                assert find(window, 'manualSection-' + str(index)).property('important')
        if chapter['id'] in ('workspace', 'measurement-edit', 'export'):
            assert window.grabWindow().save(str(tmp_path / (chapter['id'] + '-top.png')))
            reading.setProperty('contentY', max(0, reading.property('contentHeight') - reading.height()))
            QTest.qWait(30)
            assert window.grabWindow().save(str(tmp_path / (chapter['id'] + '-details.png')))
    ws.openManual('measurement')
    QTest.qWait(60)
    assert window.grabWindow().save(str(tmp_path / f'manual-{size[0]}.png'))
    assert not warnings, warnings


def test_manual_roundtrip_preserves_mpr_measurement_and_segmentation(sidebar_scene):
    from qt_dicom_viewer.model import TabType
    from test_dicom_tags import wait_until
    from test_measurement_qml import _scene, _mouse_drag
    from test_mpr_voi_qml import _owner, settle

    window, app, records, warnings = sidebar_scene
    window.resize(1400, 900)
    ws = app.workspaceController
    from qt_dicom_viewer.ui.workers.dicom_render_worker import DicomRenderWorker
    from qt_dicom_viewer.core.volume_manager import VolumeManager
    worker = DicomRenderWorker(app._series_catalog, VolumeManager())
    ws.renderRequested.disconnect(app.render_service.submit)
    ws.renderRequested.connect(worker.handleRenderRequest)
    worker.render_finished.connect(ws.handleRenderResult)
    worker.render_failed.connect(lambda failure: pytest.fail(str(failure.error)))
    ws.createTab(records[0].series_instance_uid, 'Synthetic MPR', TabType.MPR)
    tab_id, tab = ws.activeTabId, ws.activeTab
    wait_until(lambda: all(v._plane_geometry is not None for v in tab.viewports_by_id.values()))
    viewport = next(v for v in tab.viewports_by_id.values() if v.viewportType == 'axial')
    tab.activateViewport(viewport.viewportId)
    tab.toolController.activateTool('measure')
    tab.toolController.selectInteraction('measure:rect')
    def active_layer():
        return next((i for i in descendants(window.contentItem())
                     if i.objectName() == 'dicomPixelLayer' and _owner(i) is viewport
                     and i.isVisible() and i.width() > 0 and i.height() > 0), None)
    # The worker may finish before the asynchronous MPR component is created.
    wait_until(lambda: active_layer() is not None)
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    # Physical pixel-layer dimensions exist before its parent layouts are polished.
    # Render a frame before mapping image coordinates to mouse positions.
    assert not window.grabWindow().isNull()
    layer = active_layer()
    _mouse_drag(window, _scene(layer, 15, 18), _scene(layer, 30, 35))
    measurements = viewport.measurementController.measurementItems
    assert len(measurements) == 1
    click(window, find(window, 'measurementManualButton'))
    assert ws.activeTabType == 'manual' and ws.manualController.chapterId == 'measurement'
    ws.activateTabId(tab_id)
    wait_until(lambda: active_layer() is not None)
    assert viewport.measurementController.measurementItems == measurements
    tab.toolController.activateTool('segmentation')
    tab.voiController.begin(viewport, 28, 28, .1)
    tab.voiController.finish(viewport, 58, 58)
    settle(tab.voiController)
    ranges = [r.copy() for r in tab.voiController.records]
    assert ranges
    click(window, find(window, 'voiManualButton'))
    assert ws.activeTabType == 'manual' and ws.manualController.chapterId == 'segmentation'
    ws.closeTab('workspace-manual')
    wait_until(lambda: active_layer() is not None)
    assert ws.activeTabId == tab_id and ws.activeViewport is viewport
    assert tab.voiController.records == ranges
    assert viewport.measurementController.measurementItems == measurements
    assert find(window, 'mprVoiOverlay').isVisible()
    assert not warnings, warnings


def test_manual_roundtrip_preserves_3d_controller_state(sidebar_scene, monkeypatch):
    from dataclasses import replace
    from qt_dicom_viewer.model import TabType
    from qt_dicom_viewer.ui.controller.viewport.volume_viewport_controller import VolumeViewportController
    from test_dicom_tags import wait_until

    # Native GPU rendering has separate smoke tests; this test exercises Loader
    # transitions and the retained controller without requiring a display server.
    monkeypatch.setattr(VolumeViewportController, 'ensureNativeView', lambda self: None)
    monkeypatch.setattr(VolumeViewportController, 'setNativeVisible', lambda self, visible: None)
    window, app, records, warnings = sidebar_scene
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'Synthetic 3D', TabType.THREE_D)
    tab_id, viewport = ws.activeTabId, ws.activeViewport
    wait_until(lambda: viewport.loadState == 'ready')
    viewport._set_state(replace(viewport.state, zoom=1.8, pan=(.1, -.2)))
    state, display = viewport.state, viewport.display_state
    ws.openManual('volume')
    QTest.qWait(60)
    assert ws.activeViewport is None
    ws.activateTabId(tab_id)
    QTest.qWait(60)
    assert ws.activeViewport is viewport and viewport.state == state and viewport.display_state == display
    assert find(window, 'volumeViewport').isVisible()
    assert not warnings, warnings
