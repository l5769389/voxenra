"""Loading work must not monopolize GUI events or survive a closed viewport."""
from dataclasses import replace
import os
from threading import Event, get_ident
from unittest.mock import Mock

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QTimer
from PySide6.QtTest import QTest

from qt_dicom_viewer.core.volume_render_data import prepare_volume_data, prepare_fusion_data
from qt_dicom_viewer.core.volume_manager import VolumeManager
from qt_dicom_viewer.core.dicom_loader import DicomLoader
from qt_dicom_viewer.model.dicom_types import MrParameters
from qt_dicom_viewer.model.render_models import StackRenderRequest
from qt_dicom_viewer.service.render_serivce import RenderService
from qt_dicom_viewer.ui.controller.workspace_controller import WorkspaceController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from qt_dicom_viewer.ui.volume_viewport_host import VolumeViewportHost
from test_measurement_qml import qt_app
from test_dicom_tags import wait_until
from test_live_windowing import headless_volume_interactor
from test_volume_view import volume
from test_volume_display import loaded_tab
from test_series_sidebar import sidebar_scene
from test_pet_fusion import paired_series
from test_pet_2d import _pet_render_result


def test_preparation_shares_finite_pixels_and_preserves_mr_padding(volume):
    ready = prepare_volume_data(volume)
    assert ready.pixels is volume.modality_pixels
    assert ready.validity is None and ready.mask_pixels is None
    pixels = volume.modality_pixels.copy()
    pixels[0, 0, 0] = np.nan
    mr = replace(volume, modality_pixels=pixels, representative_instance_meta=replace(
        volume.representative_instance_meta, mr_parameters=MrParameters()))
    for photo in ["MONOCHROME1", "MONOCHROME2"]:
        source = replace(mr, representative_instance_meta=replace(mr.representative_instance_meta,
                                                                 photometric_interpretation=photo))
        ready = prepare_volume_data(source)
        assert np.isnan(source.modality_pixels[0, 0, 0])
        assert np.isfinite(ready.pixels).all()
        assert ready.mask_pixels[0, 0, 0] == 0
        assert ready.mask_pixels[0, 0, 1] == 255
        expected = np.nanmax(pixels) if photo == "MONOCHROME1" else np.nanmin(pixels)
        assert ready.pixels[0, 0, 0] == expected
    with pytest.raises(ValueError):
        prepare_volume_data(replace(volume, modality_pixels=pixels))


def test_fusion_preparation_keeps_separate_padding_domains(volume):
    pixels = volume.modality_pixels.copy()
    pixels[0, 0, 0] = np.nan
    ct, pet = prepare_fusion_data(replace(volume, modality_pixels=pixels), replace(volume, modality_pixels=pixels))
    assert ct.pixels[0, 0, 0] <= -4096
    assert pet.pixels[0, 0, 0] == 0
    assert np.isnan(pixels[0, 0, 0])


@pytest.fixture
def host(qt_app, loaded_tab, headless_volume_interactor, monkeypatch):
    c = loaded_tab.activeViewport
    h = VolumeViewportHost(c)
    # Keep real VTK data objects; replace only the GPU draw for headless CI.
    monkeypatch.setattr(h.backend, "render", Mock())
    monkeypatch.setattr(h, "windowHandle", lambda: Mock(isExposed=lambda: True))
    monkeypatch.setattr(h.vtk_widget, "windowHandle", lambda: Mock(isExposed=lambda: True))
    monkeypatch.setattr(h.vtk_widget, "isVisible", lambda: True)
    h._active = True
    yield h, c
    h.dispose()
    loaded_tab.dispose()


def test_background_preparation_leaves_gui_timer_running(host, monkeypatch):
    h, c = host
    entered, release = Event(), Event()
    threads, installed = [], []
    gui_thread = get_ident()
    def prepare(v):
        threads.append(get_ident())
        entered.set()
        assert release.wait(3)
        return prepare_volume_data(v)
    monkeypatch.setattr(h.backend, "preparation_request", lambda v: (prepare, (v,)))
    actual = h.backend.set_volume
    def install(v, p):
        installed.append(get_ident())
        actual(v, p)
    monkeypatch.setattr(h.backend, "set_volume", install)
    ticks=[]
    timer=QTimer(); timer.setInterval(10); timer.timeout.connect(lambda:ticks.append(True)); timer.start()
    try:
        h.sync_status()
        wait_until(entered.is_set)
        QTest.qWait(100)
        assert len(ticks) >= 4 and not installed
        assert h.stack.currentWidget() is h.status_page
        assert h.message.isHidden()
        wait_until(lambda: not h.message.isHidden())
        release.set()
        wait_until(lambda: h.backend.volume is c.volume)
        assert threads == [threads[0]] and threads[0] != gui_thread
        assert installed == [gui_thread]
        assert h.stack.currentWidget() is h.vtk_widget
        assert h.message.isHidden()
    finally:
        release.set(); timer.stop()


def test_late_preparation_cannot_replace_new_volume(host, monkeypatch):
    h, c = host
    old = c.volume
    entered, release, finished = Event(), Event(), Event()
    def prepare(v):
        if v is old:
            entered.set()
            assert release.wait(3)
        result=prepare_volume_data(v)
        if v is old: finished.set()
        return result
    monkeypatch.setattr(h.backend, "preparation_request", lambda v: (prepare, (v,)))
    try:
        h.sync_status()
        wait_until(entered.is_set)
        new=replace(old, modality_pixels=old.modality_pixels+10)
        c.volume=new
        h.sync_status()
        wait_until(lambda:h.backend.volume is new)
        release.set()
        wait_until(finished.is_set)
        QTest.qWait(30)
        assert h.backend.volume is new
        np.testing.assert_array_equal(h.backend._pixels, new.modality_pixels)
    finally:
        release.set()


def test_disposal_during_preparation_never_installs_late_result(host, monkeypatch):
    h,c=host
    entered,release,finished=Event(),Event(),Event()
    def prepare(v):
        entered.set()
        assert release.wait(3)
        result=prepare_volume_data(v)
        finished.set()
        return result
    monkeypatch.setattr(h.backend,"preparation_request",lambda v:(prepare,(v,)))
    installed=Mock()
    monkeypatch.setattr(h.backend,"set_volume",installed)
    try:
        h.sync_status();wait_until(entered.is_set)
        h.dispose()
        release.set();wait_until(finished.is_set);QTest.qWait(30)
        installed.assert_not_called()
    finally:release.set()


def test_expose_after_buffer_swap_does_not_loop_rendering(host, monkeypatch):
    h,_=host
    request=Mock();monkeypatch.setattr(h,"request_render",request)
    from PySide6.QtGui import QWindow
    surface=QWindow()
    exposed=[True]
    monkeypatch.setattr(surface,"isExposed",lambda:exposed[0])
    for _ in range(20):h.eventFilter(surface,QEvent(QEvent.Expose))
    assert request.call_count == 1
    exposed[0]=False;h.eventFilter(surface,QEvent(QEvent.Expose))
    exposed[0]=True;h.eventFilter(surface,QEvent(QEvent.Expose))
    assert request.call_count == 2


def test_close_cancels_volume_decode_and_reopen_does_not_wait_for_obsolete_slices(qt_app, paired_series, monkeypatch):
    catalog,ct,_=paired_series
    ws=WorkspaceController(catalog,DicomImageProvider())
    manager=VolumeManager(); service=RenderService(catalog,manager)
    ws.renderRequested.connect(service.submit);ws.renderCancelled.connect(service.cancel)
    service.rendered.connect(ws.handleRenderResult);service.failed.connect(ws.handleRenderFailure)
    entered,release=Event(),Event()
    reads=[]; failures=[];service.failed.connect(failures.append)
    actual=DicomLoader.read_frame
    def read(loader,*args,**kwargs):
        reads.append(args[0])
        if len(reads)==1:
            entered.set();assert release.wait(3)
        return actual(loader,*args,**kwargs)
    monkeypatch.setattr(DicomLoader,"read_frame",read)
    try:
        ws.createTab(ct.series_instance_uid,"first","3d");old=ws.activeViewport
        wait_until(entered.is_set)
        ws.closeTab(ws.activeTabId)
        ws.createTab(ct.series_instance_uid,"second","3d");new=ws.activeViewport
        release.set()
        wait_until(lambda:new.loadState=="ready")
        assert old._disposed and old.volume is None
        assert len(reads)==1+len(ct.instances)
        assert manager.get_volume(ct.series_instance_uid) is new.volume
        assert not failures
    finally:
        release.set();ws.shutdown();service.shutdown()


def test_cancelled_queued_requests_are_skipped_before_read(qt_app, paired_series, monkeypatch):
    catalog,_,pet=paired_series
    service=RenderService(catalog,VolumeManager())
    entered,release=Event(),Event();reads=[];results=[];errors=[]
    service.rendered.connect(results.append);service.failed.connect(errors.append)
    def render(r):
        reads.append(r.request_id)
        if r.request_id=="running":entered.set();assert release.wait(3)
        service._worker.render_finished.emit(replace(_pet_render_result(),response_id=r.request_id,viewport_id=r.viewport_id))
    monkeypatch.setattr(service._worker,"_handle_stack_request",render)
    request=StackRenderRequest(request_id="running",viewport_id="a",series_uid=pet.series_instance_uid,
                               slice_index=0,window=None,inverted=False)
    try:
        service.submit(request);wait_until(entered.is_set)
        service.submit(replace(request,request_id="queued",viewport_id="b"))
        service.submit(replace(request,request_id="pending"))
        service.cancel(["a","b"])
        service.submit(replace(request,request_id="fresh",viewport_id="c"))
        release.set();wait_until(lambda:len(results)==1)
        assert reads==["running","fresh"]
        assert results[0].response_id=="fresh" and not errors and not service._pending
    finally:release.set();service.shutdown()


def test_volume_cache_eviction_preserves_live_view_and_one_oversized_volume(volume):
    n=volume.modality_pixels.nbytes
    manager=VolumeManager(maximum_cache_bytes=2*n)
    a=replace(volume,series_uid="a",suv_pixels=volume.modality_pixels)
    b=replace(volume,series_uid="b",modality_pixels=volume.modality_pixels.copy())
    c=replace(volume,series_uid="c",modality_pixels=volume.modality_pixels.copy())
    manager._volumes_by_series_uid[("a",None)]=a
    manager._volumes_by_series_uid[("b",None)]=b
    assert manager.cache_bytes==2*n
    manager.get_volume("a")
    manager._volumes_by_series_uid[("c",None)]=c;manager._trim_cache()
    assert manager.get_volume("b") is None
    assert manager.get_volume("a") is a
    assert b.modality_pixels.size==volume.modality_pixels.size
    manager._maximum_cache_bytes=1;manager._trim_cache()
    assert len(manager._volumes_by_series_uid)==1


@pytest.mark.skipif(os.environ.get('VOXENRA_NATIVE_QA') != '1',
                    reason='requires native desktop window')
def test_native_main_window_switches_during_preparation(sidebar_scene, monkeypatch):
    from qt_dicom_viewer.ui.volume_render_backend import VolumeRenderBackend
    window, app, records, warnings = sidebar_scene
    workspace = app.workspaceController
    entered, release = Event(), Event()
    actual = VolumeRenderBackend.preparation_request

    def request(backend, volume):
        function, args = actual(backend, volume)
        def prepare():
            entered.set()
            assert release.wait(4)
            return function(*args)
        return prepare, ()

    monkeypatch.setattr(VolumeRenderBackend, 'preparation_request', request)
    try:
        workspace.createTab(records[0].series_instance_uid, '3D loading', '3d')
        controller, tab_id = workspace.activeViewport, workspace.activeTabId
        wait_until(entered.is_set)
        host = controller._host
        assert not host.data_ready
        workspace.openManual('volume')
        wait_until(lambda: not host._active)
        release.set()
        workspace.activateTabId(tab_id)
        wait_until(lambda: host.data_ready and host.backend._initialized)
        state = controller.state
        # Exercise Loader destruction both before and after a QML timer fires.
        for delay in (1, 17, 1, 35):
            workspace.openManual('volume')
            QTest.qWait(delay)
            workspace.activateTabId(tab_id)
            QTest.qWait(delay)
        wait_until(lambda: host._active and host.data_ready)
        assert controller.state == state
        assert not controller.snapshot_image().isNull()
        workspace.closeTab(tab_id)
        QTest.qWait(80)
        assert host._disposed and not host._active
        assert not warnings, warnings
    finally:
        release.set()


def test_frame_ready_requires_gpu_draw_and_resets_for_new_volume(host):
    h, c = host
    h.sync_status()
    wait_until(lambda: h.data_ready)
    h._timer.stop()
    assert not h.frame_ready
    h._render()
    assert h.frame_ready

    c.volume = replace(c.volume, modality_pixels=c.volume.modality_pixels.copy())
    assert not h.data_ready and not h.frame_ready
    h.sync_status()
    wait_until(lambda: h.data_ready)
    h._timer.stop()
    assert not h.frame_ready
    h._render()
    assert h.frame_ready


def test_unexposed_native_child_defers_draw_and_recovers(host, monkeypatch):
    h, c = host
    child = Mock(isExposed=Mock(return_value=False))
    monkeypatch.setattr(h.vtk_widget, 'windowHandle', lambda: child)
    h.sync_status()
    wait_until(lambda: h.data_ready)
    h._render()
    assert h._dirty and h._timer.isActive() and not h.frame_ready
    h.backend.render.assert_not_called()
    child.isExposed.return_value = True
    h._render()
    assert h.frame_ready and not h._dirty


def test_native_child_timeout_is_actionable_error_not_empty_tab(host, monkeypatch):
    h, c = host
    h.sync_status()
    wait_until(lambda: h.data_ready)
    monkeypatch.setattr(h, 'surface_ready', lambda: False)
    h._surface_wait_started = 1.0
    monkeypatch.setattr('qt_dicom_viewer.ui.volume_viewport_host.monotonic', lambda: 17.0)
    h._render()
    assert c.loadState == 'error' and '3D' in c.errorMessage
    assert h.stack.currentWidget() is h.status_page
    assert not h.close_button.isHidden()
    assert not h.frame_ready


def test_minimized_surface_wait_does_not_report_failure(host, monkeypatch):
    h, c = host
    h.sync_status()
    wait_until(lambda: h.data_ready)
    monkeypatch.setattr(h, 'windowHandle', lambda: Mock(isExposed=lambda: False))
    h._surface_wait_started = 0
    h._render()
    assert c.loadState == 'ready' and h._dirty
    assert h._surface_wait_started is None


def test_native_creation_exception_becomes_load_error(loaded_tab, monkeypatch):
    c = loaded_tab.activeViewport
    monkeypatch.setattr(c, 'ensureNativeView', Mock(side_effect=RuntimeError('context unavailable')))
    c.acquireNativeView(None)
    assert c.loadState == 'error' and 'context unavailable' in c.errorMessage


def test_windows_paint_is_coalesced_and_swap_paint_does_not_loop(host, monkeypatch):
    h, c = host
    monkeypatch.setattr('qt_dicom_viewer.ui.volume_viewport_host.monotonic', lambda: 50.0)
    h._last_draw = 49.0
    h.native_paint()
    assert h._timer.isActive() and h._dirty
    h._timer.stop()
    h._dirty = False
    h._last_draw = 49.95
    h.native_paint()
    assert not h._timer.isActive() and not h._dirty


def test_four_d_preparation_preserves_last_frame_without_loading_flash(host, monkeypatch):
    from types import SimpleNamespace
    h, c = host
    h.sync_status()
    wait_until(lambda: h.data_ready)
    h._timer.stop()
    h._render()
    assert h.frame_ready
    entered, release = Event(), Event()
    def prepare(volume):
        entered.set()
        assert release.wait(3)
        return prepare_volume_data(volume)
    monkeypatch.setattr(h.backend, 'preparation_request', lambda v: (prepare, (v,)))
    c._layout_owner = SimpleNamespace(tab=SimpleNamespace(temporalPlayback=True))
    old = h.backend.volume
    c.volume = replace(c.volume, modality_pixels=c.volume.modality_pixels + 10)
    try:
        h.sync_status()
        wait_until(entered.is_set)
        assert not h.frame_ready
        assert h.backend.volume is old
        assert h.stack.currentWidget() is h.vtk_widget
        del c._layout_owner
        release.set()
        wait_until(lambda: h.data_ready)
        h._timer.stop()
        h._render()
        assert h.frame_ready and h.backend.volume is c.volume
    finally:
        release.set()
        if hasattr(c, '_layout_owner'):
            del c._layout_owner
