"""Windowing must publish pixels during a held drag, even with a stalled worker.

Check the provider and source notifications, not just WW/WL state. A render-only
implementation can pass final-state tests while displaying nothing until release.
"""
from dataclasses import replace
from unittest.mock import Mock

import numpy as np
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage

from voxplane.core.color_maps import apply_color_map
from voxplane.core.dicom_loader import DicomLoader
from voxplane.core.pet_fusion import blend_pet_ct, pet_rgb
from voxplane.core.pet_reconstruction import PetReconstructor
from voxplane.core.volume_manager import VolumeManager
from voxplane.model import WindowLevel, WindowLevelChange
from voxplane.ui.controller.workspace_controller import WorkspaceController
from voxplane.ui.dicom_image_provider import DicomImageProvider
from voxplane.ui.workers.dicom_render_worker import DicomRenderWorker
from test_compare_2d import comparison, open_pair as open_2d_pair
from test_compare_mpr import open_pair as open_mpr_pair
from test_dicom_tags import qt_app, wait_until
from test_pet_fusion import paired_series
from test_volume_view import volume, make_tab


def image_pixels(provider, key):
    image = provider._images[key].convertToFormat(QImage.Format_RGBA8888)
    return np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.bytesPerLine())[:, :image.width()*4].reshape(image.height(), image.width(), 4).copy()


def assert_image(provider, key, expected):
    actual = image_pixels(provider, key)[..., :3]
    if expected.ndim == 2:
        expected = np.repeat(expected[..., None], 3, axis=2)
    np.testing.assert_array_equal(actual, expected[..., :3])


def begin_drag(view, tool='window'):
    view._tool_controller.activateTool(tool)
    view.setViewportSize(512, 512)
    # Away from the MPR locator/handles: this gesture must select windowing.
    view.beginInteraction(20, 20, 1, True, .37, .63, .001, .001)
    assert view._active_drag_operation is not None


def move_drag(view, step):
    start = QPointF(20, 20)
    delta = QPointF(24 * step, 12 * step)
    view.updateInteraction(start, start + delta, QPointF(24, 12), delta, True, 0, 0)


def assert_live(view, provider, before_source):
    assert view.imageSource != before_source, 'Image must change before release or worker completion'
    assert_live_labels(view)
    expected = apply_color_map(DicomLoader.apply_window(
        view._modality_pixel, view.current_window, view.inverted), view.activeColorMap)
    assert_image(provider, view.viewportId, expected)


def assert_live_labels(view):
    assert float(view.overlayInfo['windowCenter']) == float(f'{view.current_window.center:.0f}')
    signed_width = view.current_window.width * (-1 if view.inverted else 1)
    assert float(view.overlayInfo['windowWidth']) == float(f'{signed_width:.0f}')


def pause_worker(app):
    wait_until(lambda: not app.render_service._active and not app.render_service._pending)
    app.workspaceController.renderRequested.disconnect(app.render_service.submit)
    pending = []
    app.workspaceController.renderRequested.connect(pending.append)
    return pending


def drain(app, pending):
    worker = DicomRenderWorker(app._series_catalog, app._volume_manager)
    worker.render_finished.connect(app.workspaceController.handleRenderResult)
    failures = []
    worker.render_failed.connect(failures.append)
    count = 0
    while pending:
        worker.handleRenderRequest(pending.pop(0))
        count += 1
        assert count < 100
    assert not failures


@pytest.mark.parametrize('mode', ['stack', 'axial', 'coronal', 'sagittal', 'mpr', 'compare2d', 'comparempr'])
def test_ct_drag_publishes_every_view_before_worker_finishes(comparison, mode):
    app, records = comparison
    ws, provider = app.workspaceController, app._image_provider
    if mode == 'comparempr':
        tab = open_mpr_pair(app, records)
        tab.setLink('window', True)
    elif mode == 'compare2d':
        tab, _ = open_2d_pair(app, records)
    else:
        ws.createTab(records[0].series_instance_uid, 'Live window', 'mpr' if mode == 'mpr' else '2d')
        wait_until(lambda: ws.activeLoadState.status == 'ready')
        tab = ws.activeTab
        if mode in ('axial', 'coronal', 'sagittal'):
            tab.twoDLayout.setLayout('1x2')
            tab.twoDLayout.loadSeries(1, records[1].series_instance_uid)
            wait_until(lambda: tab.activeViewport.loadState == 'ready')
            tab.twoDLayout.setMode(0, mode)
            wait_until(lambda: tab.activeViewport.loadState == 'ready')
    pending = pause_worker(app)
    source = tab.activeViewport
    linked = list(tab.viewports_by_id.values()) if mode in ('mpr', 'compare2d', 'comparempr') else [source]
    untouched = {v.viewportId: image_pixels(provider, v.viewportId)
                 for v in tab.viewports_by_id.values() if v not in linked}
    original_samples = {v.viewportId: v._modality_pixel.copy() for v in linked}
    initial_images = {v.viewportId: image_pixels(provider, v.viewportId) for v in linked}
    begin_drag(source)
    for step in range(1, 7):
        previous = [v.imageSource for v in linked]
        move_drag(source, step)
        for view, before in zip(linked, previous):
            assert_live(view, provider, before)
            np.testing.assert_array_equal(view._modality_pixel, original_samples[view.viewportId])
        for key, pixels in untouched.items():
            np.testing.assert_array_equal(image_pixels(provider, key), pixels)
    assert all(np.any(initial_images[v.viewportId] != image_pixels(provider, v.viewportId)) for v in linked)
    # Old queued results must neither roll back the latest intent nor its pixels.
    intended = [(v.current_window, v.inverted) for v in linked]
    drain(app, pending)
    assert [(v.current_window, v.inverted) for v in linked] == intended
    for view in linked:
        assert_image(provider, view.viewportId, apply_color_map(DicomLoader.apply_window(
            view._modality_pixel, view.current_window, view.inverted), view.activeColorMap))
    # No endInteraction was called during any assertion above.
    source.endInteraction(164, 92, True, 0, 0)


def test_montage_all_retained_slices_window_live_and_release_samples(comparison):
    app, records = comparison
    ws, provider = app.workspaceController, app._image_provider
    ws.createTab(records[0].series_instance_uid, 'Montage', 'montage')
    view = ws.activeTab.activeViewport
    view.setVisibleRange(0, 2)
    wait_until(lambda: len(view._display_samples) == 3 and not view._active_request)
    pending = pause_worker(app)
    view._tool_controller.activateTool('window')
    view.beginInteraction(20, 20, 1, 512, 512)
    for step in range(1, 7):
        before = [view._slice_model.item(i)['imageSource'] for i in range(3)]
        delta = QPointF(step * 24, step * 12)
        view.updateInteraction(QPointF(20,20), QPointF(20,20)+delta, QPointF(24,12), delta)
        for index in range(3):
            assert view._slice_model.item(index)['imageSource'] != before[index]
            assert_image(provider, view.image_key(index), DicomLoader.apply_window(
                view._display_samples[index], view.viewport_state.window, view.inverted))
    drain(app, pending)
    view.dispose()
    assert not view._display_samples
    assert not any(view.image_key(i) in provider._images for i in range(3))


@pytest.mark.parametrize('mode', ['2d', 'mpr', 'fusion-ct', 'fusion-pet'])
def test_pet_and_fusion_window_live_without_reslicing(qt_app, paired_series, mode):
    catalog, ct, pet = paired_series
    provider = DicomImageProvider()
    ws = WorkspaceController(catalog, provider)
    pending = []
    ws.renderRequested.connect(pending.append)
    renderer = PetReconstructor(catalog, VolumeManager())
    worker = DicomRenderWorker(catalog, VolumeManager())
    worker.render_finished.connect(ws.handleRenderResult)
    if mode.startswith('fusion'):
        ws.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
    else:
        ws.createTab(pet.series_instance_uid, 'PET', mode)
    tab = ws.activeTab
    def finish():
        while pending:
            request = pending.pop(0)
            if mode == '2d':
                worker.handleRenderRequest(request)
            else:
                ws.handleRenderResult(renderer.render(request))
    finish()
    source = (next(v for v in tab.viewports_by_id.values() if v.viewportRole == ('ct' if mode == 'fusion-ct' else 'pet'))
              if mode.startswith('fusion') else tab.activeViewport)
    views = list(tab.viewports_by_id.values())
    target_views = [v for v in views if (v.viewportRole in ('ct', 'fusion') if mode == 'fusion-ct' else v.viewportRole != 'ct')]
    initial = {v.viewportId: image_pixels(provider, v.viewportId) for v in target_views}
    begin_drag(source, 'ct-window' if mode == 'fusion-ct' else 'pet-window' if mode == 'fusion-pet' else 'window')
    for step in range(1, 6):
        before = [v.imageSource for v in target_views]
        move_drag(source, step)
        for view, old in zip(target_views, before):
            assert view.imageSource != old
            if view.viewportRole == 'ct':
                expected = DicomLoader.apply_window(view._modality_pixel, tab._ct_window, tab._ct_inverted)
            else:
                target = view._pet_display.target
                gray = DicomLoader.apply_window(view._modality_pixel, target.window, False, target.minimum)
                if view.viewportRole == 'fusion':
                    expected = blend_pet_ct(DicomLoader.apply_window(view._ct_pixels, tab._ct_window, tab._ct_inverted),
                                            gray, view._modality_pixel, tab._opacity, tab._fusion_color)
                else:
                    expected = apply_color_map(gray, view.activeColorMap)
            assert_image(provider, view.viewportId, expected)
    assert any(np.any(initial[v.viewportId] != image_pixels(provider, v.viewportId)) for v in target_views)
    finish()
    # Unit changes stay transactional; cached samples must not acquire new units.
    old_sources = [v.imageSource for v in views]
    source.setPetUnit('kbqml')
    assert [v.imageSource for v in views] == old_sources
    finish()
    ws.closeTab(tab.tab_config.tab_id)


def test_four_d_drag_live_during_pending_phase_and_obsolete_result(qt_app):
    from voxplane.model import TabConfig, TabType, MprFrame
    from voxplane.application.series_catalog import SeriesCatalog
    from voxplane.ui.controller.tab.tab_controller import TabController
    from test_four_d import _four_d_meta
    from test_linked_ct_window import result_for
    tab = TabController(TabConfig('live-4d', '4D', TabType.FOUR_D, (_four_d_meta(),)))
    provider = DicomImageProvider()
    ws = WorkspaceController(SeriesCatalog(), provider)
    ws._tab_dict[tab.tab_config.tab_id] = tab
    ws.connect_signal(tab)
    pending = []
    ws.renderRequested.connect(pending.append)
    frame = MprFrame.standard_lps((0., 0., 0.))
    def finish():
        while pending:
            request = pending.pop(0)
            result = result_for(tab, request, frame)
            pixels = np.arange(12, dtype=np.float32).reshape(3, 4) * 30
            result = replace(result, modality_pixel=pixels, image=DicomLoader.apply_window(
                pixels, result.frame_meta.window, result.frame_meta.inverted))
            ws.handleRenderResult(result)
    tab.init_render()
    finish()
    tab.setPhaseIndex(1)
    view = tab.activeViewport
    begin_drag(view)
    for step in range(1, 7):
        old = [v.imageSource for v in tab.viewports_by_id.values()]
        move_drag(view, step)
        for peer, source in zip(tab.viewports_by_id.values(), old):
            assert_live(peer, provider, source)
    desired = view.current_window
    finish()
    assert tab.currentPhaseIndex == 1
    assert all(v.current_window == desired for v in tab.viewports_by_id.values())
    ws.shutdown()


@pytest.fixture
def headless_volume_interactor(monkeypatch):
    # QVTK needs a native Cocoa/Win32 drawable, unavailable on offscreen CI.
    # Keep the real Qt host/timers and VTK transfer pipeline; replace its canvas.
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget
    from vtkmodules.vtkRenderingOpenGL2 import vtkGenericOpenGLRenderWindow
    from vtkmodules.vtkRenderingUI import vtkGenericRenderWindowInteractor
    from voxplane.ui import volume_viewport_host
    class Canvas(QWidget):
        def __init__(self, host):
            super().__init__(host)
            self.setAttribute(Qt.WA_NativeWindow)
            self.winId()
            self.window = vtkGenericOpenGLRenderWindow()
            self.interactor = vtkGenericRenderWindowInteractor()
            self.interactor.SetRenderWindow(self.window)
        def GetRenderWindow(self):
            return self.window
        def DestroyTimer(self, *args):
            pass
        def Finalize(self):
            self.window.Finalize()
    monkeypatch.setattr(volume_viewport_host, 'VolumeInteractor', Canvas)


def test_native_3d_host_renders_window_changes_during_held_drag(qt_app, volume, monkeypatch, headless_volume_interactor):
    """Exercise the actual 16 ms host scheduler and VTK transfer functions.

    Only the final GPU draw is replaced so this contract runs on headless CI.
    """
    from voxplane.model.render_models import VolumeLoadResult
    from voxplane.ui.volume_viewport_host import VolumeViewportHost
    tab = make_tab('live-3d')
    view = tab.activeViewport
    pending = []
    tab.renderRequested.connect(pending.append)
    tab.init_render()
    request = pending.pop()
    tab.handleRenderResult(VolumeLoadResult(response_id=request.request_id,
        viewport_id=request.viewport_id, series_uid=request.series_uid, volume=volume))
    host = VolumeViewportHost(view)
    host.backend.set_volume(volume)
    host._prepared_key = host.backend.preparation_key(volume)
    renders = []
    def draw(state, interactive, display, mask):
        host.backend.apply_display(display)
        renders.append((interactive, display.window, host.backend.properties.GetRGBTransferFunction().GetMTime()))
    monkeypatch.setattr(host.backend, 'render', draw)
    monkeypatch.setattr(host, 'windowHandle', lambda: Mock(isExposed=lambda: True))
    monkeypatch.setattr(host, 'surface_ready', lambda: True)
    host._active = True
    try:
        view._tools.activateTool('window')
        view.begin_drag((100, 100), (512, 512))
        data = host.backend.mapper.GetInput()
        for step in range(1, 5):
            before = len(renders)
            view.update_drag((100 + step*24, 100 + step*12))
            wait_until(lambda: len(renders) > before)
            assert renders[-1][0] is True
            assert renders[-1][1] == view.display_state.window
            assert host.backend.mapper.GetInput() is data
            assert view._drag is not None
        assert len({r[2] for r in renders}) == len(renders)
        assert not pending, 'Windowing must not reload the 3D volume'
    finally:
        host.dispose()
        host.deleteLater()
        view.cancel_drag()


@pytest.mark.parametrize('fusion', [False, True])
def test_pet_3d_display_controls_request_live_native_render(qt_app, paired_series, monkeypatch, headless_volume_interactor, fusion):
    from voxplane.ui.volume_viewport_host import VolumeViewportHost
    catalog, ct, pet = paired_series
    ws = WorkspaceController(catalog, DicomImageProvider())
    pending = []
    ws.renderRequested.connect(pending.append)
    worker = DicomRenderWorker(catalog, VolumeManager())
    worker.render_finished.connect(ws.handleRenderResult)
    if fusion:
        ws.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
        ws.handleRenderResult(PetReconstructor(catalog, VolumeManager()).render(pending.pop()))
        ws.activeTab.openVolumeView()
    else:
        ws.createTab(pet.series_instance_uid, 'PET 3D', '3d')
        worker.handleRenderRequest(pending.pop())
    view = ws.activeViewport
    # Host owns display-state scheduling for standalone, fusion and MPR 3D panes.
    host = VolumeViewportHost(view, backend_factory=lambda widget: Mock())
    host._prepared_key = host.backend.preparation_key(view.volume)
    monkeypatch.setattr(host, 'windowHandle', lambda: Mock(isExposed=lambda: True))
    monkeypatch.setattr(host, 'surface_ready', lambda: True)
    host._active = True
    try:
        if fusion:
            view._tools.activateTool('window')
            view.begin_drag((100, 100), (512, 512))
        for step in range(1, 5):
            before = host.backend.render.call_count
            if fusion:
                view.update_drag((100 + step*24, 100 + step*12))
            else:
                view.setPetUpper(step * 4.)
            wait_until(lambda: host.backend.render.call_count > before)
            assert host.backend.render.call_args.args[1] is True
        assert not pending
    finally:
        host.dispose()
        host.deleteLater()
        ws.shutdown()


@pytest.mark.parametrize('mpr', [False, True])
def test_disabled_window_link_preserves_peer_pixels_and_selected_lut(comparison, mpr):
    app, records = comparison
    tab = open_mpr_pair(app, records) if mpr else open_2d_pair(app, records)[0]
    if mpr:
        tab.setLink('window', True)
        tab.setLink('window', False)
        source = tab.groups[0].activeViewport
        peers = list(tab.groups[1].viewports_by_id.values())
    else:
        tab.setSyncOperation('window', False)
        source = tab.activeViewport
        peers = [v for v in tab.viewports_by_id.values() if v is not source]
    source.applyColorMap('hotIron')
    source.toggleInverted()
    pause_worker(app)
    original = {v.viewportId: image_pixels(app._image_provider, v.viewportId) for v in peers}
    begin_drag(source)
    for step in range(1, 5):
        old = source.imageSource
        move_drag(source, step)
        assert_live(source, app._image_provider, old)
        for peer in peers:
            np.testing.assert_array_equal(image_pixels(app._image_provider, peer.viewportId), original[peer.viewportId])


def test_pet_failed_window_restores_pixels_and_next_drag_starts_at_visible_window(qt_app, paired_series):
    from voxplane.model import RenderFailure
    catalog, _, pet = paired_series
    provider = DicomImageProvider()
    ws = WorkspaceController(catalog, provider)
    pending = []
    ws.renderRequested.connect(pending.append)
    worker = DicomRenderWorker(catalog, VolumeManager())
    worker.render_finished.connect(ws.handleRenderResult)
    ws.createTab(pet.series_instance_uid, 'PET stack', '2d')
    worker.handleRenderRequest(pending.pop())
    view = ws.activeViewport
    baseline = image_pixels(provider, view.viewportId)
    view.setPetDisplayUpper(view.petDisplayUpper * .5)
    first = view.current_window
    assert first == view._pet_display.target.window
    begin_drag(view)
    # The first drag event at the same point must not jump to an old window.
    move_drag(view, 0)
    assert view.current_window == first
    move_drag(view, 2)
    assert np.any(image_pixels(provider, view.viewportId) != baseline)
    latest = pending[-1]
    ws.handleRenderFailure(RenderFailure(request_id=latest.request_id, viewport_id=view.viewportId,
                                         error=ValueError('simulated failure')))
    np.testing.assert_array_equal(image_pixels(provider, view.viewportId), baseline)
    assert view.current_window == view._pet_display.applied.window
    ws.shutdown()


@pytest.mark.parametrize('mode', ['stack', 'axial', 'coronal', 'sagittal', 'mpr', 'compare2d', 'comparempr', 'montage'])
def test_mr_fractional_window_and_polarity_stay_live_across_views(qt_app, tmp_path, mode):
    from voxplane.model import DicomFolderScanSnapshot
    from voxplane.ui.app_controller import AppController
    from test_mr import write_mr_series

    def fractional_mr(ds, index):
        ds.RescaleSlope = .0001
        ds.WindowCenter, ds.WindowWidth = .2, .3
        ds.PhotometricInterpretation = 'MONOCHROME1'
        ds.PixelPaddingValue = 0

    records = [write_mr_series(tmp_path / str(i), change=fractional_mr) for i in range(2)]
    app = AppController(DicomImageProvider(), settings_path=tmp_path / 'settings.json')
    try:
        snapshot = DicomFolderScanSnapshot(tmp_path, 8, 8, 0, records)
        app.panelController.update_series_session(snapshot)
        app.panelController._update_series_record(snapshot)
        ws, provider = app.workspaceController, app._image_provider
        uids = [r.series_instance_uid for r in records]
        if mode == 'comparempr':
            ws.createMprCompareTab(*uids)
        elif mode == 'compare2d':
            ws.createMultiCompareTab(uids)
        else:
            ws.createTab(uids[0], 'Fractional MR', mode if mode in ('mpr', 'montage') else '2d')
        tab = ws.activeTab
        if mode == 'montage':
            tab.activeViewport.setVisibleRange(0, 3)
            wait_until(lambda: len(tab.activeViewport._display_samples) == 4
                       and not tab.activeViewport._active_request)
        else:
            wait_until(lambda: all(v.loadState == 'ready' for v in tab.viewports_by_id.values()))
            if mode in ('axial', 'coronal', 'sagittal'):
                tab.twoDLayout.setMode(0, mode)
                wait_until(lambda: tab.activeViewport.loadState == 'ready')
        pending = pause_worker(app)
        source = tab.activeViewport
        # MR groups keep independent windows; windowing within an MPR group is linked.
        linked = (list(tab.groups[0].viewports_by_id.values()) if mode == 'comparempr'
                  else list(tab.viewports_by_id.values()) if mode == 'mpr' else [source])
        untouched = {v.viewportId: image_pixels(provider, v.viewportId)
                     for v in tab.viewports_by_id.values() if v not in linked}
        source._tool_controller.activateTool('window')
        if mode == 'montage':
            source.beginInteraction(20, 20, 1, 512, 512)
        else:
            begin_drag(source)
        initial = {i: image_pixels(provider, source.image_key(i)) for i in range(4)} if mode == 'montage' else {
            v.viewportId: image_pixels(provider, v.viewportId) for v in linked}
        for step in range(1, 5):
            if mode == 'montage':
                delta = QPointF(step * 24, step * 12)
                source.updateInteraction(QPointF(20, 20), QPointF(20, 20) + delta, QPointF(24, 12), delta)
                for index, pixels in source._display_samples.items():
                    expected = DicomLoader.apply_window(pixels, source.viewport_state.window, not source.inverted, .001)
                    assert_image(provider, source.image_key(index), expected)
            else:
                previous = [v.imageSource for v in linked]
                move_drag(source, step)
                for view, old in zip(linked, previous):
                    assert view.imageSource != old
                    assert 0 < view.current_window.width < 1
                    assert_image(provider, view.viewportId, DicomLoader.apply_window(
                        view._modality_pixel, view.current_window, not view.inverted, .001))
        current = {i: image_pixels(provider, source.image_key(i)) for i in range(4)} if mode == 'montage' else {
            v.viewportId: image_pixels(provider, v.viewportId) for v in linked}
        assert all(np.any(initial[key] != current[key]) for key in current)
        for key, pixels in untouched.items():
            np.testing.assert_array_equal(image_pixels(provider, key), pixels)
        # Obsolete queued results must not revert the live MR preview.
        drain(app, pending)
        for key, pixels in current.items():
            np.testing.assert_array_equal(image_pixels(provider, source.image_key(key) if mode == 'montage' else key), pixels)
    finally:
        app.shutdown()
