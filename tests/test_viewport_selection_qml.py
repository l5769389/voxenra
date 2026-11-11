"""Image transforms must never obscure or resize the active viewport's frame."""
import os
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest

from voxplane.model import DicomFolderScanSnapshot
from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_pet_fusion import paired_series
from test_four_d import _cross_series_four_d
from test_tag_qml import find, click
from qt_pointer import move_pointer
from test_cpr_controller import cpr
from test_cpr_qml import cpr_page, named_item
from test_pinch_zoom import trackpad, gesture


def assert_frame_pixels(window, frame, inset=2):
    image = window.grabWindow()
    sx, sy = image.width() / window.width(), image.height() / window.height()
    for fraction in (.2, .5, .8):
        for local in (QPointF(inset, frame.height() * fraction),
                      QPointF(frame.width() - inset - 1, frame.height() * fraction),
                      QPointF(frame.width() * fraction, inset),
                      QPointF(frame.width() * fraction, frame.height() - inset - 1)):
            p = frame.mapToScene(local)
            assert image.pixelColor(round(p.x() * sx), round(p.y() * sy)) == QColor('#66d0ff'), local


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('kind', ['2d', 'mpr', '4d', 'pet', 'fusion', 'compare2d', 'comparempr'])
def test_active_frame_survives_hover_tool_focus_and_single_view(sidebar_scene, paired_series, tmp_path, theme, kind):
    window, app, records, warnings = sidebar_scene
    window.resize(1000, 600)
    app.settingsController.setValue('appearance', 'theme', theme)
    registry = app.workspaceController
    if kind in ('pet', 'fusion', '4d'):
        _, ct, pet = paired_series
        series = _cross_series_four_d(tmp_path / 'phases') if kind == '4d' else [ct, pet]
        app._series_catalog.update(DicomFolderScanSnapshot(tmp_path, 6, 6, 0, series))
        if kind == 'fusion':
            registry.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
        else:
            registry.createTab((series[0] if kind == '4d' else pet).series_instance_uid,
                               kind, '4d' if kind == '4d' else 'mpr')
    elif kind.startswith('compare'):
        create = registry.createCompareTab if kind == 'compare2d' else registry.createMprCompareTab
        create(*(r.series_instance_uid for r in records[:2]))
    else:
        registry.createTab(records[0].series_instance_uid, 'Synthetic CT', kind)
    wait_until(lambda: registry.activeLoadState.status == 'ready')
    tab = registry.activeTab
    views = list(tab.viewports_by_id.values())
    frames = [find(window, 'viewportFrame-' + view.viewportId) for view in views]
    canvases = [find(window, 'imageViewport-' + view.viewportId) for view in views]
    QTest.qWait(120)

    def dimensions():
        return [(canvas.mapToScene(QPointF()), canvas.width(), canvas.height()) for canvas in canvases]

    def assert_selected(view):
        assert tab.activeViewport is view
        assert [frame.property('active') for frame in frames] == [candidate is view for candidate in views]
        frame = frames[views.index(view)]
        assert_frame_pixels(window, frame)

    original_dimensions = dimensions()
    for view, canvas, frame in zip(views, canvases, frames):
        previous = tab.activeViewport
        move_pointer(window, canvas.mapToScene(QPointF(canvas.width() * .35, canvas.height() * .65)).toPoint())
        QTest.qWait(40)
        assert tab.activeViewport is previous  # Hover never selects a different image.
        if view is not previous:
            image = window.grabWindow()
            point = frame.mapToScene(QPointF(1, frame.height() / 2))
            assert image.pixelColor(round(point.x() * image.width() / window.width()),
                                    round(point.y() * image.height() / window.height())) == QColor('#8599a8')
        click(window, canvas)
        QTest.qWait(40)
        assert_selected(view)
        if kind == 'comparempr':
            # Activating the other comparison group changes its heading's
            # emphasis; capture that layout before testing image transforms.
            original_dimensions = dimensions()
        assert dimensions() == original_dimensions
        click(window, find(window, 'primaryTool-zoom'))
        QTest.qWait(40)
        assert_selected(view)  # Moving to the tool panel must keep the frame visible.
        assert dimensions() == original_dimensions
        for transform in (lambda: view.setZoom(3), lambda: view.apply_pan(120, -80),
                          lambda: view.applyTransformAction('rotate:cw90'),
                          lambda: view.applyTransformAction('rotate:mirror-h')):
            transform()
            QTest.qWait(40)
            assert_selected(view)
            assert dimensions() == original_dimensions
        assert view.zoom == 3
    assert window.grabWindow().save(str(tmp_path / f'selection-{kind}-{theme}.png'))

    if len(views) > 1 and not kind.startswith('compare'):
        tab.focusSingleViewport(views[-1].viewportId)
        QTest.qWait(80)
        assert sum(frame.isVisible() for frame in frames) == 1
        assert_selected(views[-1])
        tab.focusSingleViewport('')
        QTest.qWait(80)
        assert dimensions() == original_dimensions
        assert_selected(views[-1])
    assert not warnings, warnings


def test_cpr_reference_and_result_frames_survive_transforms(cpr_page, tmp_path):
    window, tab = cpr_page
    for role in ('reference-a', 'reference-b', 'curved', 'cross'):
        view = tab.viewForRole(role)
        surface = named_item(window.rootObject(), 'cprViewport-' + role)
        cell = surface.parentItem().parentItem().parentItem()
        bounds = (surface.mapToScene(QPointF()), surface.size())
        tab.activateViewport(view.viewportId)
        path, position = tab.current_path, tab.positionMm
        for transform in (lambda: view.setZoom(3), lambda: view.apply_pan(100, -60),
                          lambda: view.applyTransformAction('rotate:cw90'),
                          lambda: view.applyTransformAction('rotate:mirror-h')):
            transform()
            QTest.qWait(40)
            assert tab.activeViewport is view
            assert_frame_pixels(window, cell, inset=0)
            assert (surface.mapToScene(QPointF()), surface.size()) == bounds
            assert tab.current_path == path and tab.positionMm == position
    assert window.grabWindow().save(str(tmp_path / 'cpr-frames.png'))


@pytest.mark.skipif(os.environ.get('VOXPLANE_NATIVE_QA') != '1', reason='requires native desktop window')
@pytest.mark.parametrize('kind', ['3d', 'mpr'])
def test_native_volume_frame_stays_outside_zoomed_native_surface(sidebar_scene, trackpad, kind, tmp_path):
    window, app, records, warnings = sidebar_scene
    app.settingsController.setValue('appearance', 'theme', 'dark')
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'CT', kind)
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    tab = ws.activeTab
    if kind == 'mpr':
        tab.mprLayout.setLayout('quad')
        volume = tab.mprLayout.volumeViewport
    else:
        volume = tab.activeViewport
    wait_until(lambda: volume._host is not None and volume._host.frame_ready)
    tab.activateViewport(volume.viewportId)
    frame = find(window, 'volumeViewportFrame')
    QTest.qWait(120)
    assert_frame_pixels(window, frame)
    widget = volume._host.vtk_widget
    original_size = widget.size()
    before = volume.snapshot_image()
    assert not before.isNull()
    gesture(widget, trackpad, QPointF(widget.width() * .4, widget.height() * .6), [1, .5])
    QTest.qWait(120)
    assert volume.zoom == pytest.approx(3)
    assert tab.activeViewport is volume and widget.size() == original_size
    assert_frame_pixels(window, frame)
    rendered = volume.snapshot_image()
    assert not rendered.isNull() and rendered != before
    assert rendered.save(str(tmp_path / f'{kind}-native-content.png'))
    assert window.grabWindow().save(str(tmp_path / f'{kind}-frame.png'))
    assert not warnings, warnings
