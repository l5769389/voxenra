"""Opening lifecycle, GUI responsiveness and the shared view/tool conventions."""
from pathlib import Path
from threading import Event

import pytest
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtTest import QTest
from shiboken6 import delete

from qt_dicom_viewer.model import DicomFolderScanSnapshot, RenderFailure, TabConfig, TabType, MprFrame
from qt_dicom_viewer.core.volume_manager import VolumeManager
from qt_dicom_viewer.service.render_serivce import RenderService
from qt_dicom_viewer.ui.controller.workspace_controller import WorkspaceController
from qt_dicom_viewer.ui.controller.panel_controller import PanelController
from qt_dicom_viewer.ui.controller.tab.tab_controller import TabController
from qt_dicom_viewer.ui.controller.tab.tool_controller import ToolController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
from qt_dicom_viewer.ui.workers.dicom_render_worker import DicomRenderWorker
from test_tag_qml import _App, find, click, descendants
from test_dicom_tags import qt_app, wait_until
from test_pet_fusion import paired_series
from test_four_d import _four_d_meta
from test_linked_ct_window import result_for


@pytest.fixture
def opening_scene(qt_app, paired_series, tmp_path, monkeypatch):
    # Native GPU creation has separate coverage; this fixture checks QML loading.
    from qt_dicom_viewer.ui.controller.viewport.volume_viewport_controller import VolumeViewportController
    monkeypatch.setattr(VolumeViewportController, "ensureNativeView", lambda self: None)
    catalog, ct, pet = paired_series
    provider = DicomImageProvider()
    workspace = WorkspaceController(catalog, provider)
    panel = PanelController(series_catalog=catalog)
    panel._update_series_record(DicomFolderScanSnapshot(tmp_path, 6, 6, 0, [ct, pet]))
    panel.tabCreateRequested.connect(workspace.activeWorkspace)
    app = _App(workspace, panel)
    engine = QQmlApplicationEngine()
    engine.addImageProvider("navigation", SvgIconProvider())
    engine.addImageProvider("dicom", provider)
    engine.rootContext().setContextProperty("appController", app)
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / "src/qt_dicom_viewer/qml/Main.qml")))
    window = engine.rootObjects()[0]
    QTest.qWait(50)
    requests = []
    workspace.renderRequested.connect(requests.append)
    worker = DicomRenderWorker(catalog, VolumeManager())
    worker.render_finished.connect(workspace.handleRenderResult)
    worker.render_failed.connect(workspace.handleRenderFailure)
    try:
        yield window, workspace, ct, pet, requests, worker, warnings
    finally:
        window.hide()
        workspace.shutdown()
        panel.shutdown()
        delete(engine)


def drain(requests, worker):
    count = 0
    while requests:
        worker.handleRenderRequest(requests.pop(0))
        count += 1
        assert count < 40


def visible(window, name):
    return any(i.objectName() == name and i.isVisible() for i in descendants(window.contentItem()))


@pytest.mark.parametrize("view_type,pet_only", [("2d", False), ("mpr", False), ("montage", False),
                                               ("3d", False), ("2d", True), ("mpr", True), ("fusion", False)])
def test_opening_waits_for_all_required_frames(opening_scene, view_type, pet_only, tmp_path):
    window, workspace, ct, pet, requests, worker, warnings = opening_scene
    if view_type == "fusion":
        workspace.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
    else:
        record = pet if pet_only else ct
        workspace.createTab(record.series_instance_uid, record.patient_name, view_type)
    history = workspace.activeTab.historyController
    # PET snapshots carry an object while other edit notifications have no
    # arguments. Both must use static slots before QML caches the controller.
    assert history.metaObject().superClass().className() == "QObject"
    assert workspace.activeLoadState.loading
    wait_until(lambda: visible(window, "workspaceBusyIndicator"))
    # 3D native widgets are not constructed before its data has been decoded.
    if view_type == "3d":
        assert workspace.activeViewport._host is None
    drain(requests, worker)
    assert workspace.activeLoadState.status == "ready"
    wait_until(lambda: not visible(window, "workspaceLoadingState"))
    assert not workspace.loadingStates[workspace.activeTabId] == "loading"
    if pet_only and view_type == "mpr":
        views = list(workspace.currentTabAllViewports)
        assert [v.viewportRole for v in views] == ["axial", "coronal", "sagittal"]
        assert len(worker._pet_reconstructor._mip_cache) == 0
        layers = [i for i in descendants(window.contentItem()) if i.objectName() == "dicomPixelLayer"]
        assert len(layers) == 3
        assert window.grabWindow().save(str(tmp_path / "pet-mpr-three-views.png"))
    assert not warnings, warnings


def test_loading_switch_close_reopen_and_stale_result(opening_scene):
    window, workspace, ct, pet, requests, worker, warnings = opening_scene
    workspace.createTab(pet.series_instance_uid, "PET", "mpr")
    old_id = workspace.activeTabId
    old_request = requests.pop(0)
    old_result = worker._pet_reconstructor.render(old_request)
    workspace.openManual("water-qa")
    assert workspace.activeLoadState is None
    wait_until(lambda: not visible(window, "workspaceLoadingState"))
    workspace.activateTabId(old_id)
    wait_until(lambda: visible(window, "cancelWorkspaceLoad"))
    click(window, find(window, "cancelWorkspaceLoad"))
    assert old_id not in workspace._tab_dict
    workspace.createTab(pet.series_instance_uid, "PET", "mpr")
    workspace.handleRenderResult(old_result)
    assert workspace.activeLoadState.loading
    assert not workspace.activeTab.ready
    drain(requests, worker)
    assert workspace.activeLoadState.status == "ready"
    assert not warnings, warnings


def test_partial_mpr_failure_close_reopen_rejects_old_errors(opening_scene):
    window, workspace, ct, pet, requests, worker, warnings = opening_scene
    workspace.createTab(ct.series_instance_uid, "CT", "mpr")
    worker.handleRenderRequest(requests.pop(0))
    assert workspace.activeLoadState.loading
    assert "1 / 3" in workspace.activeLoadState.message
    failed = requests.pop(0)
    workspace.handleRenderFailure(RenderFailure(request_id=failed.request_id, viewport_id=failed.viewport_id, error=ValueError("模拟读取失败")))
    assert workspace.activeLoadState.status == "error"
    wait_until(lambda: visible(window, "cancelWorkspaceLoad"))
    assert not visible(window, "retryWorkspaceLoad")
    assert "模拟读取失败" in find(window, "workspaceLoadingMessage").property("text")
    QTest.qWait(50)
    click(window, find(window, "cancelWorkspaceLoad"))
    assert workspace.activeTab is None
    requests.clear()
    workspace.createTab(ct.series_instance_uid, "CT", "mpr")
    drain(requests, worker)
    assert workspace.activeLoadState.status == "ready"
    workspace.handleRenderFailure(RenderFailure(request_id=failed.request_id, viewport_id=failed.viewport_id, error=ValueError("旧失败")))
    assert workspace.activeLoadState.status == "ready"
    assert not warnings, warnings


def test_slow_reconstruction_keeps_gui_timer_and_tab_actions_responsive(opening_scene):
    window, workspace, ct, pet, requests, worker, warnings = opening_scene
    entered, release = Event(), Event()

    class SlowVolumes(VolumeManager):
        def get_or_build(self, *args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test did not release the worker")
            return super().get_or_build(*args, **kwargs)

    service = RenderService(workspace._series_catalog, SlowVolumes())
    workspace.renderRequested.connect(service.submit)
    service.rendered.connect(workspace.handleRenderResult)
    service.failed.connect(workspace.handleRenderFailure)
    timer, ticks = QTimer(), []
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(True))
    timer.start()
    try:
        workspace.createTab(pet.series_instance_uid, "PET", "mpr")
        wait_until(entered.is_set)
        QTest.qWait(100)
        assert len(ticks) >= 4
        assert visible(window, "workspaceBusyIndicator")
        waiting = workspace.activeTabId
        workspace.openManual()
        wait_until(lambda: not visible(window, "workspaceLoadingState"))
        assert workspace.activeTabType == "manual"
        workspace.activateTabId(waiting)
        assert workspace.activeLoadState.loading
        release.set()
        wait_until(lambda: workspace.activeLoadState.status == "ready")
        assert not warnings, warnings
    finally:
        release.set()
        timer.stop()
        service.shutdown()


def test_four_d_opening_finishes_after_all_three_planes(qt_app):
    from qt_dicom_viewer.application.series_catalog import SeriesCatalog
    workspace = WorkspaceController(SeriesCatalog(), DicomImageProvider())
    tab = TabController(TabConfig("4d-opening", "4D", TabType.FOUR_D, (_four_d_meta(),)), workspace)
    workspace.connect_signal(tab)
    workspace._tab_dict[tab.tab_config.tab_id] = tab
    workspace.activateTabId(tab.tab_config.tab_id)
    requests = []
    workspace.renderRequested.connect(requests.append)
    tab.init_render()
    frame = MprFrame.standard_lps((0., 0., 0.))
    workspace.handleRenderResult(result_for(tab, requests.pop(0), frame))
    assert workspace.activeLoadState.loading
    while requests:
        workspace.handleRenderResult(result_for(tab, requests.pop(0), frame))
    assert workspace.activeLoadState.status == "ready"
    workspace.shutdown()


@pytest.mark.parametrize("tab_type,modality", [(TabType.TWO_D, "CT"), (TabType.TWO_D, "PT"),
    (TabType.MPR, "CT"), (TabType.MPR, "PT"), (TabType.FOUR_D, "CT"), (TabType.THREE_D, "CT"),
    (TabType.MONTAGE, "CT"), (TabType.PETCT_FUSION, "PT"), (TabType.THREE_D, "PETCT3D")])
def test_common_tools_keep_their_relative_order_and_reset_is_last(qt_app, tab_type, modality):
    tools = [item["toolType"] for item in ToolController(tab_type=tab_type, modality=modality).tools]
    common = ["window", "ct-window", "pet-window", "scroll", "play", "pan", "zoom",
              "rotate", "volume-rotate", "measure", "annotate", "pseudocolor", "viewport-settings"]
    assert [tool for tool in tools if tool in common] == [tool for tool in common if tool in tools]
    assert tools[-1] == "reset"
    if "export" in tools:
        assert tools[-2] == "export"
    for specialist in ("segmentation", "voi", "registration", "service", "volume-crop", "volume-bed"):
        if specialist in tools:
            assert tools.index(specialist) > tools.index("zoom")


def test_tag_loading_failure_and_retry_share_the_workspace_status(opening_scene, monkeypatch):
    from qt_dicom_viewer.model.dicom_tags import TagReadResult
    window, workspace, ct, pet, requests, worker, warnings = opening_scene
    pending = []
    monkeypatch.setattr(workspace._tag_read_service, "submit", pending.append)
    workspace.createTab(ct.series_instance_uid, "Tags", "tag")
    assert workspace.activeLoadState.loading
    wait_until(lambda: visible(window, "workspaceBusyIndicator"))
    workspace._tag_read_service.finished.emit(TagReadResult(pending[-1], error="模拟标签读取失败"))
    assert workspace.activeLoadState.status == "error"
    workspace.retryActiveTab()
    assert workspace.activeLoadState.loading
    workspace._tag_read_service.finished.emit(TagReadResult(pending[-1], ()))
    assert workspace.activeLoadState.status == "ready"
    wait_until(lambda: not visible(window, "workspaceLoadingState"))
    assert not warnings, warnings
