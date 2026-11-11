from dataclasses import replace
from pathlib import Path
from threading import Event
import time

import pydicom
import pytest
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, ImplicitVRLittleEndian
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from voxplane.application.series_catalog import SeriesCatalog
from voxplane.core.dicom_scanner import _read_instance, _build_series_record
from voxplane.core.dicom_tag_reader import read_dicom_tags
from voxplane.model import DicomFolderScanSnapshot
from voxplane.model.dicom_tags import TagReadRequest, TagReadResult
from voxplane.service.tag_read_service import TagReadService
from voxplane.ui.controller.tab.tag_controller import TagController
from voxplane.ui.controller.tab.tag_tree_model import TagTreeModel
from voxplane.ui.controller.workspace_controller import WorkspaceController
from voxplane.ui.dicom_image_provider import DicomImageProvider


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    from i18n_support import install_default_language
    install_default_language(app)
    yield app


def wait_until(predicate, timeout=3000):
    deadline = time.monotonic() + timeout / 1000
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        # Qt test waits may retain the GIL and starve Python render/import workers.
        time.sleep(0.005)
    assert predicate(), "Timed out waiting for Qt state"


def make_dicom(path, index=1, *, implicit=False):
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ImplicitVRLittleEndian if implicit else ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = CTImageStorage
    meta.MediaStorageSOPInstanceUID = f"1.2.826.0.1.3680043.10.999.{index}"
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = CTImageStorage
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = "1.2.826.0.1.3680043.10.999"
    ds.SeriesInstanceUID = "1.2.826.0.1.3680043.10.999.100"
    ds.Modality = "CT"
    ds.SpecificCharacterSet = "ISO_IR 192"
    ds.PatientName = "测试^患者"
    ds.PatientID = f"DEMO-{index:03d}"
    ds.StudyDescription = "Tag browser synthetic data"
    ds.SeriesDescription = "Metadata inspection"
    ds.ImageType = ["ORIGINAL", "PRIMARY", "AXIAL"]
    ds.InstanceNumber = index
    ds.NumberOfFrames = 2
    ds.AccessionNumber = ""
    ds.Rows = 64
    ds.Columns = 64
    ds.BitsAllocated = 16
    ds.BitsStored = 12
    ds.HighBit = 11
    ds.PixelRepresentation = 0
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.PixelSpacing = [0.7, 0.8]
    ds.WindowCenter = 40
    ds.WindowWidth = 400
    ds.RescaleIntercept = -1024
    ds.RescaleSlope = 1
    ds.ImageComments = "<b>Plain text only</b> " + "Long metadata value. " * 100
    ds.PixelData = b"\0" * (64 * 64 * 2 * 2)
    ds.add_new((0x0011, 0x0010), "LO", "TEST CREATOR")
    ds.add_new((0x0011, 0x1010), "LO", "private value")
    ds.add_new((0x0011, 0x1020), "OB", b"x" * 4096)
    ds.add_new((0x7776, 0x1234), "LO", "unknown value")
    item = Dataset()
    item.CodeValue = "NESTED-NEEDLE"
    item.CodingSchemeDesignator = "99TEST"
    item.CodeMeaning = "嵌套标签"
    nested = Dataset()
    nested.PatientID = "INNER-PATIENT"
    item.ReferencedStudySequence = Sequence([nested])
    ds.ConceptNameCodeSequence = Sequence([item])
    ds.save_as(path, enforce_file_format=True)
    return ds


def make_series(tmp_path, count=3):
    instances = []
    for index in range(1, count + 1):
        path = tmp_path / f"instance-{index}.dcm"
        make_dicom(path, index)
        instances.append(_read_instance(path))
    return _build_series_record(instances)


def catalog_for(series, tmp_path):
    catalog = SeriesCatalog()
    catalog.update(DicomFolderScanSnapshot(tmp_path, len(series.instances), len(series.instances), 0, [series]))
    return catalog


def all_nodes(nodes):
    for node in nodes:
        yield node
        yield from all_nodes(node.children)


def rows(model):
    return [
        {name.decode(): model.data(model.index(index), role) for role, name in model.roleNames().items()}
        for index in range(model.rowCount())
    ]


@pytest.mark.parametrize("implicit", [False, True])
def test_reader_complete_tree_unicode_binary_and_no_pixel_access(tmp_path, monkeypatch, implicit):
    path = tmp_path / "sample.dcm"
    make_dicom(path, implicit=implicit)
    original = pydicom.filereader.read_deferred_data_element
    deferred = []

    def read_deferred(fileobj_type, filename_or_obj, timestamp, raw_data_elem):
        deferred.append(raw_data_elem.tag)
        assert raw_data_elem.tag not in (0x7FE00010, 0x00111020)
        return original(fileobj_type, filename_or_obj, timestamp, raw_data_elem)

    monkeypatch.setattr(pydicom.filereader, "read_deferred_data_element", read_deferred)
    monkeypatch.setattr(Dataset, "pixel_array", property(lambda _: pytest.fail("pixel decoding requested")))
    nodes = list(all_nodes(read_dicom_tags(path)))
    by_tag = {node.tag: node for node in nodes if not node.is_item}
    assert by_tag["(0002,0010)"].keyword == "TransferSyntaxUID"
    assert by_tag["(0010,0010)"].value == "测试^患者"
    assert by_tag["(0008,0008)"].value == "ORIGINAL\\PRIMARY\\AXIAL"
    assert by_tag["(0008,0050)"].value == "（空）"
    assert by_tag["(0028,0008)"].value == "2"
    assert by_tag["(7FE0,0010)"].value == "像素数据 · 16,384 字节"
    assert by_tag["(0011,1020)"].value == "二进制数据 · 4,096 字节"
    assert "(7776,1234)" in by_tag
    assert by_tag["(0008,0100)"].value == "NESTED-NEEDLE"
    assert by_tag["(0008,0104)"].value == "嵌套标签"
    assert by_tag["(0020,4000)"].value.endswith(("Long metadata value. " * 100).rstrip())
    assert 0x00204000 in deferred
    assert len({node.node_id for node in nodes}) == len(nodes)
    assert sum(node.is_item for node in nodes) == 2


def test_tree_filter_finds_collapsed_children_restores_expansion_and_counts(tmp_path):
    path = tmp_path / "sample.dcm"
    make_dicom(path)
    nodes = read_dicom_tags(path)
    model = TagTreeModel()
    model.set_nodes(nodes)
    total = sum(not node.is_item for node in all_nodes(nodes))
    assert model.totalCount == total == model.matchCount
    assert model.rowCount() < total
    seq = next(row for row in rows(model) if row["vr"] == "SQ")
    model.toggle(seq["nodeId"])
    before = rows(model)
    model.set_query("nested-needle")
    found = rows(model)
    assert model.matchCount == 1
    assert [row["depth"] for row in found] == [0, 1, 2]
    assert found[-1]["valueText"] == "NESTED-NEEDLE"
    assert all(row["expanded"] for row in found[:-1])
    model.toggle(seq["nodeId"])
    model.set_query("")
    assert rows(model) == before
    model.set_query("00100010")
    assert model.matchCount == 1
    model.set_query("(0010,0010)")
    assert model.matchCount == 1
    model.set_query("PaTiEnTnAmE")
    assert model.matchCount == 1
    model.set_query("没有匹配")
    assert model.rowCount() == model.matchCount == 0
    assert model.totalCount == total


def test_controller_navigation_search_stale_result_retry_and_empty(qt_app, tmp_path):
    from PySide6.QtCore import QObject, Signal

    class FakeService(QObject):
        finished = Signal(object)

        def __init__(self):
            super().__init__()
            self.requests = []
            self.cancelled = []

        def submit(self, request):
            self.requests.append(request)

        def cancel(self, tab_id):
            self.cancelled.append(tab_id)

    service = FakeService()
    series = make_series(tmp_path, 8)
    controller = TagController("test", series, service)
    controller.start()
    first = service.requests[-1]
    assert controller.loading and controller.currentPage == 1
    for invalid in ["0", "9", "-1", "1.2", "abc", "", "9999999999999"]:
        controller.jumpToPage(invalid)
        assert controller.currentPage == 1 and controller.pageError
    controller.setSearchText("PatientID")
    controller.jumpToPage(" 8 ")
    last = service.requests[-1]
    assert not controller.pageError
    assert controller.pageItems == [1, 0, 4, 5, 6, 7, 8]
    service.finished.emit(TagReadResult(first, read_dicom_tags(first.path)))
    assert controller.loading and controller.tagModel.rowCount() == 0
    service.finished.emit(TagReadResult(last, error="FileNotFoundError"))
    assert not controller.loading and controller.errorMessage
    controller.retry()
    retry = service.requests[-1]
    assert retry.request_id != last.request_id and controller.loading
    service.finished.emit(TagReadResult(retry, read_dicom_tags(retry.path)))
    assert not controller.errorMessage and not controller.loading
    assert controller.tagModel.matchCount == 2  # root and nested PatientID
    controller.saveScrollPosition(110)
    controller.selectNode("selected")
    controller.setPage(7)
    assert controller.searchText == "PatientID"
    assert controller.scrollPosition == 0 and controller.selectedNodeId == ""
    assert controller.tagModel.rowCount() == 0
    controller.dispose()
    service.finished.emit(TagReadResult(service.requests[-1], read_dicom_tags(last.path)))
    assert service.cancelled == ["test"]
    assert controller.tagModel.rowCount() == 0
    empty = TagController("empty", replace(series, instances=()), service)
    empty.start()
    assert empty.currentPage == empty.pageCount == 0
    assert empty.pageItems == [] and not empty.loading
    empty.dispose()


def test_service_coalesces_pending_and_discards_closed_results(qt_app, tmp_path):
    started, release = Event(), Event()
    reads = []

    def reader(path):
        reads.append(path.name)
        if path.name == "first":
            started.set()
            assert release.wait(3)
        return ()

    service = TagReadService(reader=reader)
    results = []
    service.finished.connect(results.append)

    def request(name, tab="tab"):
        return TagReadRequest(name, tab, name, tmp_path / name)

    try:
        service.submit(request("first"))
        wait_until(started.is_set)
        service.submit(request("skip"))
        service.submit(request("last"))
        service.submit(request("closed", "closed-tab"))
        service.cancel("closed-tab")
        release.set()
        wait_until(lambda: len(results) == 1)
        assert reads == ["first", "last"]
        assert results[0].request.request_id == "last"
    finally:
        release.set()
        service.shutdown()
    assert not service._thread.isRunning()
    service.shutdown()  # idempotent


def test_workspace_tag_reuse_explicit_sessions_and_no_render(qt_app, tmp_path):
    series = make_series(tmp_path)
    catalog = catalog_for(series, tmp_path)
    other = replace(series, series_instance_uid=series.series_instance_uid + ".2")
    catalog.update(DicomFolderScanSnapshot(tmp_path, 0, 0, 0, [other]))
    workspace = WorkspaceController(catalog, DicomImageProvider())
    render_requests = []
    workspace.renderRequested.connect(render_requests.append)
    try:
        workspace.activeWorkspace(series.series_instance_uid, "tag")
        first = workspace.activeTab
        controller = first.tagController
        wait_until(lambda: not controller.loading)
        assert workspace.activeViewport is None and workspace.currentTabAllViewports == []
        assert render_requests == []
        controller.setPage(2)
        controller.setSearchText("PatientName")
        wait_until(lambda: not controller.loading)
        workspace.activeWorkspace(other.series_instance_uid, "tag")
        assert workspace.activeTab.tagController.currentPage == 1
        workspace.activeWorkspace(series.series_instance_uid, "tag")
        assert workspace.activeTab is first and len(workspace.tabs) == 2
        assert controller.currentPage == 2 and controller.searchText == "PatientName"
        workspace.createTab(series.series_instance_uid, "Independent tags", "tag", new_session=True)
        assert workspace.activeTab is not first and len(workspace.tabs) == 3
        assert workspace.activeTab.tagController.currentPage == 1
        assert workspace.activeTab.tagController.searchText == ""
        workspace.activateTabId(first.tab_config.tab_id)
        assert controller.currentPage == 2 and controller.searchText == "PatientName"
        controller.setPage(3)
        workspace.closeTab(first.tab_config.tab_id)
        assert len(workspace.tabs) == 2
        QTest.qWait(30)
        workspace.activeWorkspace(series.series_instance_uid, "tag")
        wait_until(lambda: not workspace.activeTab.tagController.loading)
        assert workspace.activeTab.tagController.currentPage == 1
        assert render_requests == []
    finally:
        workspace.shutdown()


def test_unreadable_instance_can_retry_and_then_navigate(qt_app, tmp_path):
    series = make_series(tmp_path)
    missing = series.instances[0].path
    original = missing.read_bytes()
    missing.unlink()
    service = TagReadService()
    controller = TagController("tab", series, service)
    try:
        controller.start()
        wait_until(lambda: not controller.loading)
        assert "FileNotFoundError" in controller.errorMessage
        missing.write_bytes(original)
        controller.retry()
        wait_until(lambda: not controller.loading)
        assert not controller.errorMessage and controller.tagModel.totalCount > 0
        controller.setPage(2)
        wait_until(lambda: not controller.loading)
        assert controller.currentPage == 2 and not controller.errorMessage
    finally:
        controller.dispose()
        service.shutdown()
