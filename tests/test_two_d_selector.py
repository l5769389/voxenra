"""Real corner-menu switching, preserved overlays and clean image capture."""
import pytest
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtTest import QTest

from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_tag_qml import find, click, descendants
from test_two_d_layout import open_scene
from test_anonymous_view_export import capture, pixels
from test_workspace_persistence import draw_length


def choose(window, index, mode):
    click(window, find(window, 'twoDPlane-' + str(index)))
    click(window, find(window, 'twoDModeOption-' + mode))


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('locale', ['zh-CN', 'en-US'])
def test_corner_menu_switches_real_planes_without_losing_stack_edits(sidebar_scene, theme, locale, tmp_path):
    window, app, records, warnings = sidebar_scene
    app.settingsController.setValue('appearance', 'theme', theme)
    app.languageController.selectLanguage(locale)
    tab, layout = open_scene(app, records)
    stack = tab.activeViewport
    stack.setSliceIndex(1)
    stack.setZoom(1.5)
    wait_until(lambda: stack._frame_meta.slice_index == 1)
    mid = draw_length(stack)
    tab.toolController.activateTool('pan')
    original_pan = (stack._state.pan_x, stack._state.pan_y)
    selector = find(window, 'twoDPlane-0')
    image = find(window, 'imageViewport-' + stack.viewportId)
    cell = find(window, 'twoDCell-0')
    # The image begins immediately inside its frame: no old 30-pixel heading.
    assert image.mapToItem(cell, QPointF()).y() == 5
    assert selector.mapToItem(image, QPointF()).x() == 10
    assert selector.mapToItem(image, QPointF()).y() == 10
    click(window, selector)
    assert (stack._state.pan_x, stack._state.pan_y) == original_pan
    assert not tab.focusedViewportId
    QTest.qWait(60)
    assert window.grabWindow().save(str(tmp_path / ('corner-menu-' + theme + '.png')))
    click(window, find(window, 'twoDModeOption-axial'))
    labels = ['轴位重建', '冠状位重建', '矢状位重建'] if locale == 'zh-CN' else ['Axial MPR', 'Coronal MPR', 'Sagittal MPR']
    for mode, label in zip(['axial', 'coronal', 'sagittal'], labels):
        if mode != 'axial': choose(window, 0, mode)
        wait_until(lambda: tab.activeViewport.loadState == 'ready')
        view = tab.activeViewport
        assert view.viewportType == mode and not view.hasCrosshair
        assert find(window, 'twoDPlane-0').property('displayText') == label
        position = find(window, 'twoDModePosition').property('text')
        assert position == view.overlayInfo['viewPosition'].split(', ', 1)[1].replace('mm', ' mm')
        corner = find(window, 'overlay-topLeft').property('text')
        assert 'Slice:' in corner and view.overlayInfo['manufacturer'] in corner
    choose(window, 0, 'stack')
    assert tab.activeViewport is stack and stack.sliceIndex == 1 and stack.zoom == 1.5
    assert mid in stack._measure_controller._measurements
    expected = stack.overlayInfo['viewPosition'].replace(', ', ' · ').replace('mm', ' mm')
    if locale == 'zh-CN': expected = expected.replace('Axial', '轴位')
    assert find(window, 'twoDModePosition').property('text') == expected
    assert find(window, 'twoDPlane-0').property('displayText') == ('原始切片' if locale == 'zh-CN' else 'Original slices')
    QTest.qWait(60)
    assert window.grabWindow().save(str(tmp_path / ('corner-stack-' + theme + '.png')))
    # Live language changes resize both the control and exported plain label.
    app.languageController.selectLanguage('en-US' if locale == 'zh-CN' else 'zh-CN')
    QTest.qWait(30)
    selector = find(window, 'twoDPlane-0')
    assert selector.property('displayText') == ('Original slices' if locale == 'zh-CN' else '原始切片')
    assert selector.width() == find(window, 'twoDModeLabel').width() + 30
    assert not warnings, warnings


def test_hidden_or_reordered_information_keeps_selector_and_all_configured_fields(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    tab, layout = open_scene(app, records)
    view = tab.activeViewport
    fields = ['manufacturer', 'slice', 'viewPosition', 'seriesDescription']
    assert app.settingsController.setValue('corners', 'topLeft', fields)
    corner = find(window, 'overlay-topLeft')
    assert view.overlayInfo['viewPosition'] in corner.property('text')
    assert view.overlayInfo['seriesDescription'] in corner.property('text')
    layout.setViewportSetting('window-annotations', False)
    overlay = next(i for i in descendants(find(window, 'imageViewport-' + view.viewportId)) if i.objectName() == 'viewportMetadataOverlay')
    assert not overlay.isVisible()
    choose(window, 0, 'coronal')
    wait_until(lambda: tab.activeViewport.loadState == 'ready')
    assert not tab.activeViewport.showWindowAnnotations
    assert find(window, 'twoDPlane-0').property('displayText') == '冠状位重建'
    layout.setViewportSetting('window-annotations', True)
    assert tab.activeViewport.overlayInfo['viewPosition'] in find(window, 'overlay-topLeft').property('text')
    assert app.settingsController.values['corners']['topLeft'] == fields
    assert not warnings, warnings


def test_controls_are_excluded_from_export_and_plain_mode_position_remain(sidebar_scene, tmp_path):
    window, app, records, warnings = sidebar_scene
    tab, layout = open_scene(app, records)
    image = find(window, 'imageViewport-' + tab.activeViewport.viewportId)
    selector = find(window, 'twoDPlane-0')
    assert selector not in list(descendants(image))
    help_area = find(window, 'twoDPositionHelp-0')
    assert help_area not in list(descendants(image))
    label = next(i for i in descendants(image) if i.objectName() == 'twoDModeLabel')
    position = next(i for i in descendants(image) if i.objectName() == 'twoDModePosition')
    assert label.isVisible() and label.property('text') == '原始切片'
    assert position.isVisible() and 'mm' in position.property('text')
    point = help_area.mapToScene(QPointF(12, help_area.height() / 2)).toPoint()
    QTest.mouseMove(window, point)
    tooltip = help_area.findChild(QObject, 'twoDPositionToolTip-0')
    wait_until(lambda: tooltip.property('visible'))
    assert tooltip.property('text') == 'S/I：上/下；L/R：左/右；P/A：后/前。'
    # Keep the pointer stationary so the cursor-value overlay stays unchanged.
    before = capture(image)
    tooltip.setProperty('visible', False)
    assert pixels(capture(image)) == pixels(before)
    selector.setProperty('visible', False)
    after = capture(image)
    assert pixels(before) == pixels(after)
    assert after.save(str(tmp_path / 'export-without-controls.png'))
    image.setProperty('anonymousExport', True)
    anonymous = capture(image)
    assert not next(i for i in descendants(image) if i.objectName() == 'viewportMetadataOverlay').isVisible()
    assert pixels(anonymous) != pixels(before)
    image.setProperty('anonymousExport', False)
    assert not warnings, warnings


def test_source_without_geometry_does_not_claim_a_plane_or_position(sidebar_scene, tmp_path):
    from test_mr import write_mr_series
    from qt_dicom_viewer.model import DicomFolderScanSnapshot
    window, app, _, warnings = sidebar_scene

    def remove_geometry(ds, index):
        del ds.ImageOrientationPatient
        del ds.ImagePositionPatient

    series = write_mr_series(tmp_path / 'unknown-orientation', change=remove_geometry)
    app.panelController.acceptPacsImport(DicomFolderScanSnapshot(tmp_path, 4, 4, 0, [series]))
    wait_until(lambda: app.workspaceController.activeViewport is not None
               and app.workspaceController.activeViewport.loadState == 'ready')
    assert find(window, 'twoDPlane-0').property('displayText') == '原始切片'
    assert find(window, 'twoDModePosition').property('text') == '方向与位置未知'
    app.languageController.selectLanguage('en-US')
    QTest.qWait(30)
    assert find(window, 'twoDModePosition').property('text') == 'Orientation / position unavailable'
    assert not warnings, warnings


def test_each_cell_menu_targets_its_own_view_and_focus_does_not_change_layout(sidebar_scene, tmp_path):
    window, app, records, warnings = sidebar_scene
    tab, layout = open_scene(app, records)
    layout.setLayout('2x2')
    layout.loadSeries(1, records[1].series_instance_uid)
    wait_until(lambda: tab.activeViewport.loadState == 'ready')
    second = tab.activeViewport
    choose(window, 0, 'coronal')
    wait_until(lambda: tab.activeViewport.loadState == 'ready')
    first = tab.activeViewport
    assert layout.activeCell == 0 and layout.cells[1]['viewport'] is second
    assert second.viewportType == 'stack'
    selector = find(window, 'twoDPlane-0')
    p = selector.mapToScene(QPointF(selector.width()/2, selector.height()/2)).toPoint()
    QTest.mouseDClick(window, Qt.LeftButton, Qt.NoModifier, p)
    QTest.keyClick(window, Qt.Key_Escape)
    assert tab.focusedViewportId == ''
    tab.focusSingleViewport(first.viewportId)
    assert find(window, 'twoDPlane-0').isVisible()
    choose(window, 0, 'sagittal')
    wait_until(lambda: tab.activeViewport.loadState == 'ready')
    # Switching mode while focused must keep the same cell visible.
    assert find(window, 'imageViewport-' + tab.activeViewport.viewportId).isVisible()
    tab.focusSingleViewport('')
    window.resize(1000, 600)
    QTest.qWait(80)
    position = find(window, 'twoDModePosition')
    assert position.width() > 0 and position.y() >= 24
    selector = find(window, 'twoDPlane-0')
    assert not selector.property('contentItem').property('truncated')
    assert 'mm' in position.property('text')
    assert window.grabWindow().save(str(tmp_path / 'corner-multiview.png'))
    assert not warnings, warnings


@pytest.mark.parametrize('invalid_volume', [False, True])
def test_oblique_mr_keeps_source_orientation_and_can_return_after_reconstruction_error(sidebar_scene, tmp_path, invalid_volume):
    from test_mr import write_mr_series
    from qt_dicom_viewer.model import DicomFolderScanSnapshot
    window, app, _, warnings = sidebar_scene
    def oblique(ds, index):
        ds.ImageOrientationPatient = [1, 0, 0, 0, .8, .6]
        ds.ImagePositionPatient = [0, -1.2 * index, 1.6 * index]
        if invalid_volume:
            ds.EchoTime = 80 + index * 10
    series = write_mr_series(tmp_path / 'oblique', change=oblique)
    app.panelController.acceptPacsImport(DicomFolderScanSnapshot(tmp_path, 4, 4, 0, [series]))
    wait_until(lambda: app.workspaceController.activeViewport is not None and app.workspaceController.activeViewport.loadState == 'ready')
    tab = app.workspaceController.activeTab
    stack = tab.activeViewport
    assert stack.viewportType == 'stack'
    assert '斜位' in find(window, 'twoDModePosition').property('text')
    choose(window, 0, 'axial')
    wait_until(lambda: tab.activeViewport.loadState in ('ready', 'error'))
    assert tab.activeViewport.loadState == ('error' if invalid_volume else 'ready')
    assert find(window, 'twoDPlane-0').property('displayText') == '轴位重建'
    choose(window, 0, 'stack')
    assert tab.activeViewport is stack and stack.loadState == 'ready'
    assert '斜位' in find(window, 'twoDModePosition').property('text')
    assert not warnings, warnings
