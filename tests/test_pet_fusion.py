from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import pydicom
from pydicom.uid import CTImageStorage, generate_uid

from test_pet_2d import _pet_dataset, _write_dataset
from qt_dicom_viewer.core.dicom_scanner import _read_instance, _build_series_record
from qt_dicom_viewer.core.pet_reconstruction import PetReconstructor
from qt_dicom_viewer.core.pet_fusion import (transformed_volume, blend_pet_ct, rigid_matrix,
    registration_from_parameters, registration_document, load_registration_document)
from qt_dicom_viewer.core.volume_manager import VolumeManager
from qt_dicom_viewer.core.mpr_reslicer import MprReslicer
from qt_dicom_viewer.application.series_catalog import SeriesCatalog
from qt_dicom_viewer.model import DicomFolderScanSnapshot
from qt_dicom_viewer.model import RenderFailure, WindowLevel, MprPlane, MprFrame
from qt_dicom_viewer.model.render_models import PetBatchRenderRequest
from test_measurement_qml import qt_app
from qt_dicom_viewer.ui.controller.workspace_controller import WorkspaceController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider


def test_workspace_batch_lifecycle(qt_app, paired_series, monkeypatch):
    catalog, ct, pet = paired_series
    workspace = WorkspaceController(catalog, DicomImageProvider())
    requests = []
    workspace.renderRequested.connect(requests.append)
    workspace.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
    assert len(requests) == 1
    tab = next(iter(workspace._tab_dict.values()))
    renderer = PetReconstructor(catalog, VolumeManager())
    tab.handleRenderResult(renderer.render(requests[-1]))
    assert tab.ready
    assert len(tab.viewports_by_id) == 4
    assert tab.petController.petActiveUnitId == "suvbw"
    tab.petController.setPetUnit("kbqml")
    assert tab.petController.petUnitPending
    assert tab.petController.petActiveUnitId == "suvbw"
    tab.handleRenderResult(renderer.render(requests[-1]))
    assert tab.petController.petActiveUnitId == "kbqml"
    assert tab.petController.petControlUpper == 15
    tab.activeViewport.apply_zoom(2.)
    tab.activeViewport.applyTransformAction("rotate:cw90")
    linked = [v for v in tab.viewports_by_id.values() if v.viewportRole != "mip"]
    assert {v.zoom for v in linked} == {2.}
    assert len({v.rotationDegrees for v in linked}) == 1
    tab.activeViewport.apply_slice_index(0)
    tab.handleRenderResult(renderer.render(requests[-1]))
    assert len({v._plane_geometry for v in linked}) == 1
    tab.setPlane("coronal")
    tab.handleRenderResult(renderer.render(requests[-1]))
    assert {v.viewportType for v in tab.viewports_by_id.values() if v.viewportRole != "mip"} == {"coronal"}
    tab.setRegistrationActive(True)
    tab.setRegistrationParameter(0, 2.)
    tab.handleRenderResult(renderer.render(requests[-1]))
    assert tab.matrix[0, 3] == 2.
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.Close)
    workspace.closeTab(tab._tab_config.tab_id)


@pytest.fixture
def paired_series(tmp_path):
    study, reference = generate_uid(), generate_uid()
    records = []
    for modality in ("CT", "PT"):
        uid = generate_uid()
        instances = []
        for z in range(3):
            pixels = np.zeros((4, 4), dtype=np.uint16)
            pixels[1, 2] = (z + 1) * 1000
            ds = _pet_dataset(pixels)
            ds.Modality = modality
            ds.StudyInstanceUID = study
            ds.SeriesInstanceUID = uid
            ds.FrameOfReferenceUID = reference
            ds.ImagePositionPatient = [0, 0, z * 2]
            ds.InstanceNumber = z + 1
            if modality == "CT":
                ds.SOPClassUID = CTImageStorage
                ds.file_meta.MediaStorageSOPClassUID = CTImageStorage
            path = _write_dataset(ds, tmp_path / f"{modality}-{z}.dcm")
            instances.append(_read_instance(path))
        records.append(_build_series_record(instances))
    catalog = SeriesCatalog()
    catalog.update(DicomFolderScanSnapshot(tmp_path, 6, 6, 0, records))
    return catalog, records[0], records[1]


def test_fusion_reconstructs_linked_planes_and_mip(paired_series):
    catalog, ct, pet = paired_series
    renderer = PetReconstructor(catalog, VolumeManager())
    result = renderer.render(PetBatchRenderRequest(request_id="r", viewport_id="tab",
        series_uid=pet.series_instance_uid, ct_series_uid=ct.series_instance_uid,
        viewports=(("ct", "ct"), ("pet", "pet"), ("fusion", "fusion"), ("mip", "mip"))))
    assert len(result.frames) == 4
    assert result.frames[2].image.shape[-1] == 3
    assert result.frames[1].frame_meta.pixel_value_meta.unit == "SUVbw"
    assert result.frames[0].plane_geometry == result.frames[1].plane_geometry
    assert np.nanmax(result.frames[3].modality_pixel) == pytest.approx(6)
    assert np.nanmax(result.frames[3].peak_positions[..., 2]) == pytest.approx(4)


def test_padding_zero_weight_neighbour_does_not_poison_exact_sample():
    data = np.full((2, 2, 2), 5, dtype=np.float32)
    data[1, 1, 1] = np.nan
    zero = np.zeros((1, 1))
    assert MprReslicer._trilinear_sample(data, zero, zero, zero)[0, 0] == 5


def test_blending_preserves_ct_for_invalid_and_zero_pet():
    ct = np.array([[100, 150, 200]], dtype=np.uint8)
    pet = np.array([[255, 0, 255]], dtype=np.uint8)
    values = np.array([[np.nan, 0, 10]])
    rgb = blend_pet_ct(ct, pet, values, 1.)
    np.testing.assert_array_equal(rgb, [[[100]*3, [150]*3, [255]*3]])
    np.testing.assert_array_equal(blend_pet_ct(ct, pet, values, 0.), np.repeat(ct[..., None], 3, -1))


def test_mip_preview_is_bounded_and_does_not_replace_full_precision_cache(paired_series, monkeypatch):
    catalog, _, pet = paired_series
    volumes = VolumeManager()
    base = volumes.get_or_build(pet)
    z, y, x = np.indices((72, 140, 152), dtype=np.float32)
    pixels = np.exp(-((z-35)**2 + (y-70)**2 + (x-75)**2) / 30)
    volume = replace(base, modality_pixels=pixels, fingerprint="large-preview",
        geometry=replace(base.geometry, slice_count=72, rows=140, columns=152))
    monkeypatch.setattr(volumes, "get_or_build", lambda series: volume)
    renderer = PetReconstructor(catalog, volumes)
    sample = renderer.reslicer._sample_plane
    calls = []
    def counted(*args, **kwargs):
        calls.append(True)
        return sample(*args, **kwargs)
    monkeypatch.setattr(renderer.reslicer, "_sample_plane", counted)
    request = PetBatchRenderRequest(request_id="preview", viewport_id="t",
        series_uid=pet.series_instance_uid, viewports=(("mip", "mip"),), preview=True)
    preview = renderer.render(request).frames[0]
    assert preview.preview
    assert max(preview.image.shape[:2]) <= 128
    assert len(calls) <= 65  # Initial plane plus at most 64 projection samples.
    preview_count = len(calls)
    calls.clear()
    full = renderer.render(replace(request, request_id="full", preview=False)).frames[0]
    assert not full.preview and len(calls) > preview_count
    assert max(full.image.shape[:2]) > 128
    for field, count in (("row_spacing", "rows"), ("column_spacing", "columns")):
        assert getattr(preview.plane_geometry, field) * getattr(preview.plane_geometry, count) == pytest.approx(
            getattr(full.plane_geometry, field) * getattr(full.plane_geometry, count))
    calls.clear()
    again = renderer.render(replace(request, request_id="full2", preview=False)).frames[0]
    assert not calls
    np.testing.assert_array_equal(again.modality_pixel, full.modality_pixel)


def test_registration_rigid_direction_and_file_round_trip(paired_series):
    _, ct_series, pet_series = paired_series
    volumes = VolumeManager()
    ct, pet = volumes.get_or_build(ct_series), volumes.get_or_build(pet_series)
    pivot = np.array([2., 3., 4.])
    matrix = registration_from_parameters([10, -2, 3], [0, 0, 90], pivot)
    moved = transformed_volume(pet, matrix)
    np.testing.assert_allclose(moved.geometry.voxel_to_patient, matrix @ pet.geometry.voxel_to_patient, atol=1e-7)
    doc = registration_document(ct, pet, "ct-for", "pet-for", matrix, pivot)
    actual, actual_pivot = load_registration_document(doc, doc)
    np.testing.assert_array_equal(actual, matrix)
    np.testing.assert_array_equal(actual_pivot, pivot)
    with pytest.raises(ValueError, match="不匹配"):
        load_registration_document(dict(doc, petSeriesUID="wrong"), doc)
    with pytest.raises(ValueError, match="刚性"):
        rigid_matrix(np.diag([2, 1, 1, 1]))
    for invalid in (dict(doc, direction="CT_LPS_TO_PET_LPS"), dict(doc, ctGeometry="wrong"),
                    dict(doc, ctFrameOfReferenceUID="wrong"), dict(doc, version=2),
                    dict(doc, pivot=[float("nan"), 0, 0]), dict(doc, matrix=np.diag([-1, 1, 1, 1]).tolist()),
                    dict(doc, matrix=np.diag([1.00001, 1, 1, 1]).tolist()), [], None):
        with pytest.raises(ValueError):
            load_registration_document(invalid, doc)


def test_per_slice_quantification_and_global_fallback(paired_series):
    catalog, _, pet = paired_series
    ds = pydicom.dcmread(pet.instances[1].path)
    ds.RescaleSlope = 2
    ds.PatientWeight = 35
    ds.PixelPaddingValue = 0
    ds[0x00280120].VR = "US"
    _write_dataset(ds, pet.instances[1].path)
    volumes = VolumeManager()
    volume = volumes.get_or_build(pet)
    np.testing.assert_allclose(volume.modality_pixels[:, 1, 2], [2, 4, 6])
    np.testing.assert_allclose(volume.in_unit("kbqml").modality_pixels[:, 1, 2], [1, 4, 3])
    np.testing.assert_allclose(volume.in_unit("kbqml").in_unit("suvbw").modality_pixels,
                               volume.modality_pixels)
    assert np.isnan(volume.modality_pixels[1, 0, 0])
    assert "比例不同" in volume.pixel_value_meta.warning
    del ds.PatientWeight
    _write_dataset(ds, pet.instances[1].path)
    downgraded = volumes.get_or_build(pet)  # file changes invalidate decoded cache
    assert downgraded.pixel_value_meta.unit_id == "source"
    assert not next(o for o in downgraded.pixel_value_meta.unit_options if o.unit_id == "suvbw").available
    np.testing.assert_allclose(downgraded.modality_pixels[:, 1, 2], [1000, 4000, 3000])


@pytest.mark.parametrize("change", ["duplicate", "unequal", "offset", "orientation", "matrix", "reference", "nan"])
def test_reconstruction_rejects_nonregular_geometry(paired_series, change):
    from qt_dicom_viewer.core.pet_fusion import fusion_series_error
    _, _, pet = paired_series
    i = pet.instances[1]
    edits = {
        "duplicate": dict(image_position_patient=(0., 0., 0.)),
        "unequal": dict(image_position_patient=(0., 0., 3.)),
        "offset": dict(image_position_patient=(1., 0., 2.)),
        "orientation": dict(image_orientation_patient=(0., 1., 0., 1., 0., 0.)),
        "matrix": dict(columns=5),
        "reference": dict(frame_of_reference_uid="another"),
        "nan": dict(image_position_patient=(float("nan"), 0., 2.)),
    }
    invalid = replace(pet, instances=(pet.instances[0], replace(i, **edits[change]), pet.instances[2]))
    assert fusion_series_error(invalid)
    with pytest.raises((ValueError, RuntimeError)):
        VolumeManager().get_or_build(invalid)


def test_padding_normalized_interpolation_and_empty_support():
    a = np.full((2, 2, 2), np.nan, dtype=np.float32)
    a[0, 0, 0] = 7.
    p = np.full((1, 1), .5)
    assert MprReslicer._trilinear_sample(a, p, p, p)[0, 0] == 7
    a[:] = np.nan
    assert np.isnan(MprReslicer._trilinear_sample(a, p, p, p)).all()


@pytest.mark.parametrize("angles", [(0, 0, 90), (20, -30, 17)])
def test_different_grid_and_rigid_rotation_align_physical_marker(paired_series, angles):
    catalog, ct_record, pet_record = paired_series
    volumes = VolumeManager()
    ct, pet = volumes.get_or_build(ct_record), volumes.get_or_build(pet_record)
    ct_data = np.zeros((9, 9, 9), np.float32)
    ct_data[4, 6, 2] = 1000
    pet_data = np.zeros((5, 5, 5), np.float32)
    pet_data[2, 3, 1] = 10
    ct = replace(ct, modality_pixels=ct_data, fingerprint="ct-grid",
        geometry=replace(ct.geometry, slice_count=9, rows=9, columns=9, slice_spacing=1,
                         row_spacing=1, column_spacing=1, origin_patient=(-4., -4., -4.)))
    pet = replace(pet, modality_pixels=pet_data, fingerprint="pet-grid",
        geometry=replace(pet.geometry, slice_count=5, rows=5, columns=5, origin_patient=(-4., -4., -4.)))
    matrix = registration_from_parameters([10, -4, 3], angles, np.array([2., -1., 4.]))
    pet = transformed_volume(pet, np.linalg.inv(matrix))
    class Volumes:
        def get_or_build(self, record):
            return ct if record.modality == "CT" else pet
    renderer = PetReconstructor(catalog, Volumes())
    result = renderer.render(PetBatchRenderRequest(request_id="aligned", viewport_id="tab",
        series_uid=pet.series_uid, ct_series_uid=ct.series_uid,
        transform=tuple(matrix.ravel()), viewports=(("ct", "ct"), ("pet", "pet"))))
    fixed, moved = result.frames
    assert np.unravel_index(np.nanargmax(fixed.modality_pixel), fixed.modality_pixel.shape) == np.unravel_index(
        np.nanargmax(moved.modality_pixel), moved.modality_pixel.shape)
    assert np.nanmax(moved.modality_pixel) == pytest.approx(10.)


def test_mip_peak_and_intensity_reuses_samples(paired_series, monkeypatch):
    catalog, _, pet = paired_series
    # Peaks at two depths of the coronal projection; SUV changes their order.
    for z, instance in enumerate(pet.instances):
        ds = pydicom.dcmread(instance.path)
        values = np.zeros((4, 4), np.uint16)
        values[0, 2], values[3, 2] = (1000, 2000) if z == 1 else (0, 0)
        ds.PixelData = values.tobytes()
        _write_dataset(ds, instance.path)
    renderer = PetReconstructor(catalog, VolumeManager())
    request = PetBatchRenderRequest(request_id="mip", viewport_id="tab", series_uid=pet.series_instance_uid,
                                    viewports=(("axial", "a"), ("mip", "m")))
    result = renderer.render(request)
    assert np.nanmax(result.frames[1].modality_pixel) == pytest.approx(4)
    idx = np.unravel_index(np.nanargmax(result.frames[1].modality_pixel), result.frames[1].modality_pixel.shape)
    np.testing.assert_allclose(result.frames[1].peak_positions[idx], [4, 6, 2])
    def no_sample(*args, **kwargs):
        raise AssertionError("Display-only changes must reuse sampling")
    monkeypatch.setattr(renderer.reslicer, "_sample_plane", no_sample)
    display = renderer.render(replace(request, pet_window=WindowLevel(1, 2), pet_color_map="hotIron"))
    assert display.frames[1].image.shape[-1] == 3
    assert display.frames[1].modality_pixel is result.frames[1].modality_pixel


def test_mip_selects_maximum_in_requested_quantitative_domain(paired_series):
    catalog, _, pet = paired_series
    for z, instance in enumerate(pet.instances):
        ds = pydicom.dcmread(instance.path)
        ds.ImageOrientationPatient = [1, 0, 0, 0, 0, 1]
        ds.ImagePositionPatient = [0, -z*2, 0]
        ds.PatientWeight = 7 if z == 2 else 70
        _write_dataset(ds, instance.path)
    pet = _build_series_record([_read_instance(i.path) for i in pet.instances])
    catalog.update(DicomFolderScanSnapshot(pet.first_file.parent, 3, 3, 0, [pet]))
    renderer = PetReconstructor(catalog, VolumeManager())
    request = PetBatchRenderRequest(request_id="m", viewport_id="t", series_uid=pet.series_instance_uid,
                                    viewports=(("mip", "m"),))
    suv = renderer.render(request).frames[0]
    source = renderer.render(replace(request, value_unit="source")).frames[0]
    peak = lambda f: f.peak_positions[np.unravel_index(np.nanargmax(f.modality_pixel), f.modality_pixel.shape)]
    np.testing.assert_allclose(peak(suv), [4, -2, 2])
    np.testing.assert_allclose(peak(source), [4, -4, 2])


def test_fusion_roi_stats_recomputed_after_registration(qt_app, paired_series):
    catalog, ct, pet = paired_series
    workspace = WorkspaceController(catalog, DicomImageProvider())
    renderer = PetReconstructor(catalog, VolumeManager())
    workspace.renderRequested.connect(lambda r: workspace.handleRenderResult(renderer.render(r)))
    workspace.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
    tab = next(iter(workspace._tab_dict.values()))
    viewport = tab.activeViewport
    tab.toolController.selectInteraction("measure:rect")
    viewport.beginInteraction(0, 0, 1, True, 1.7, .1, .01, .01)
    viewport.endInteraction(20, 20, True, 2.3, 1.4)
    item = viewport.measurementController.measurementItems[0]
    assert item["metrics"]["mean"] == pytest.approx(4.)
    assert item["secondaryMetrics"]["mean"] == pytest.approx(2000.)
    viewport.setPetUnit("kbqml")
    converted = viewport.measurementController.measurementItems[0]
    assert converted["metrics"]["mean"] == pytest.approx(2.)
    assert converted["secondaryMetrics"] == item["secondaryMetrics"]
    tab.setRegistrationParameter(0, 2.)
    moved = viewport.measurementController.measurementItems[0]
    assert moved["metrics"]["mean"] == 0
    assert moved["secondaryMetrics"] == item["secondaryMetrics"]
    mip = next(v for v in tab.viewports_by_id.values() if v.viewportRole == "mip")
    assert mip._measurement_context(0, 0) is None
    workspace.shutdown()


def test_stale_batches_failure_rollback_and_registration_files(qt_app, paired_series, tmp_path):
    catalog, ct, pet = paired_series
    workspace = WorkspaceController(catalog, DicomImageProvider())
    requests = []
    workspace.renderRequested.connect(requests.append)
    workspace.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
    tab = next(iter(workspace._tab_dict.values()))
    renderer = PetReconstructor(catalog, VolumeManager())
    first = renderer.render(requests[-1])
    tab.handleRenderResult(first)
    tab.petController.setPetUnit("kbqml")
    stale = renderer.render(requests[-1])
    tab.petController.setPetUnit("source")
    tab.handleRenderResult(stale)
    tab.handleRenderFailure(RenderFailure(request_id=stale.response_id, viewport_id=stale.viewport_id, error=ValueError("old")))
    assert tab.petController.petUnitPending
    assert tab.petController.petActiveUnitId == "suvbw"
    tab.handleRenderFailure(RenderFailure(request_id=requests[-1].request_id, viewport_id=first.viewport_id, error=ValueError("new")))
    assert not tab.petController.petUnitPending
    assert tab.petController.petActiveUnitId == "suvbw"
    tab.setRegistrationActive(True)
    tab.setRegistrationParameter(3, 30)
    tab.finishRegistrationPreview()
    tab.handleRenderResult(renderer.render(requests[-1]))
    matrix, pivot = tab.matrix.copy(), tab.pivot.copy()
    path = tmp_path / "registration.json"
    tab.save_registration_to(path)
    tab.resetRegistration()
    tab.load_registration_from(path)
    np.testing.assert_array_equal(tab.matrix, matrix)
    np.testing.assert_array_equal(tab.pivot, pivot)
    tab.setRegistrationParameter(0, 100)
    tab.handleRenderFailure(RenderFailure(request_id=requests[-1].request_id, viewport_id=first.viewport_id, error=ValueError("failed")))
    np.testing.assert_array_equal(tab.matrix, matrix)
    workspace.shutdown()


def test_selection_flows_and_identity_confirmation(qt_app, paired_series):
    from qt_dicom_viewer.ui.controller.panel_controller import PanelController
    catalog, ct, pet = paired_series
    panel = PanelController(series_catalog=catalog)
    panel._scan_series_record = {r.series_instance_uid: r for r in (ct, pet)}
    opened = []
    panel.fusionCreateRequested.connect(lambda *args: opened.append(args))
    panel.selectSeries(pet.series_instance_uid)
    panel.selectSeriesWithModifiers(ct.series_instance_uid, True)
    panel.selectContextSeries(pet.series_instance_uid)
    assert len(panel.selectedSeriesUids) == 2
    panel.requestFusionView()
    assert opened == [(ct.series_instance_uid, pet.series_instance_uid)]
    assert not panel.fusionDialogOpen
    panel.selectSeries(ct.series_instance_uid)
    panel.requestFusionView()
    assert panel.fusionDialogOpen
    assert panel.fusionCandidates[0]["seriesUid"] == pet.series_instance_uid
    panel.cancelFusion()
    assert len(opened) == 1
    panel._scan_series_record[pet.series_instance_uid] = replace(pet, patient_id="")
    panel.requestFusionView()
    assert not panel.fusionCandidates
    panel.setFusionShowAllPatients(True)
    panel.selectFusionPartner(pet.series_instance_uid)
    panel.confirmFusion(False)
    assert panel.fusionDialogOpen and panel.fusionIdentityWarning
    assert len(opened) == 1
    panel.confirmFusion(True)
    assert len(opened) == 2
    panel._scan_series_record[pet.series_instance_uid] = replace(pet, study_instance_uid="different-study")
    panel.requestFusionView()
    panel.selectFusionPartner(pet.series_instance_uid)
    panel.confirmFusion(False)
    assert "不同检查" in panel.fusionIdentityWarning
    assert len(opened) == 2
    panel.requestFusionView()
    panel.selectFusionPartner(ct.series_instance_uid)
    assert "一个 CT" in panel.fusionError
    assert not panel.fusionCanConfirm
    panel.confirmFusion(True)
    assert len(opened) == 2
    panel.selectFusionPartner(pet.series_instance_uid)
    panel.removeSeries(pet.series_instance_uid)
    panel.confirmFusion(True)
    assert panel.fusionError
    panel.shutdown()


def test_pair_candidates_only_offer_complementary_patient_series(qt_app, paired_series):
    from qt_dicom_viewer.ui.controller.panel_controller import PanelController
    catalog, ct, pet = paired_series
    other = replace(ct, series_instance_uid="unrelated", patient_id="other-patient")
    old = replace(ct, series_instance_uid="prior", study_instance_uid="prior-study")
    invalid = replace(ct, series_instance_uid="localizer", instances=ct.instances[:1])
    panel = PanelController(series_catalog=catalog)
    panel._scan_series_record = {r.series_instance_uid: r for r in (other, old, ct, invalid, pet)}
    panel.selectSeries(pet.series_instance_uid)
    panel.requestFusionView()
    assert panel.fusionTargetModality == "CT"
    assert panel.fusionAnchor["seriesUid"] == pet.series_instance_uid
    assert {r["seriesUid"] for r in panel.fusionCandidates} == {ct.series_instance_uid, "prior", "localizer"}
    assert panel.fusionPartnerUid == ct.series_instance_uid
    assert panel.fusionCanConfirm
    panel.selectFusionPartner("localizer")
    assert not panel.fusionCanConfirm
    panel.setFusionShowAllPatients(True)
    panel.selectFusionPartner("unrelated")
    assert panel.fusionIdentityWarning
    panel.setFusionShowAllPatients(False)
    assert not panel.fusionPartnerUid
    assert not panel.fusionCanConfirm
    panel.selectSeries(ct.series_instance_uid)
    panel.requestFusionView()
    assert panel.fusionTargetModality == "PET"
    assert [r["seriesUid"] for r in panel.fusionCandidates] == [pet.series_instance_uid]
    panel.shutdown()


def test_registration_tool_and_window_are_independent(qt_app, paired_series):
    from qt_dicom_viewer.model import ToolType, PointerPosition, ImagePoint, Point
    from qt_dicom_viewer.utils.utils import _display_number
    catalog, ct, pet = paired_series
    workspace = WorkspaceController(catalog, DicomImageProvider())
    renderer = PetReconstructor(catalog, VolumeManager())
    workspace.renderRequested.connect(lambda r: workspace.handleRenderResult(renderer.render(r)))
    workspace.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
    tab = next(iter(workspace._tab_dict.values()))
    fusion = next(v for v in tab.viewports_by_id.values() if v.viewportRole == "fusion")
    ct_view = next(v for v in tab.viewports_by_id.values() if v.viewportRole == "ct")
    mip = next(v for v in tab.viewports_by_id.values() if v.viewportRole == "mip")
    assert tab.petColorMap == "grayscale-inverted"
    assert mip.canvasBackgroundColor == "#ffffff"
    assert fusion.canvasBackgroundColor != "#ffffff"
    assert fusion.crosshairStyle["armLength"] == mip.crosshairStyle["armLength"] == 8
    center = fusion._crosshair_image_position
    distant_line = PointerPosition(Point(0, 0), ImagePoint(center.column + 100, center.row))
    assert fusion._crosshair_hit_test(distant_line, 1, 1) is None
    tab.setCompactCrosshair(False)
    assert fusion._crosshair_hit_test(distant_line, 1, 1) is not None
    tab.setCompactCrosshair(True)
    tab.toolController.activateTool("registration")
    assert tab.registrationActive
    assert tab.toolController.activePanel == "registration"
    tab.setRegistrationParameter(0, 1)
    transform = tab.matrix.copy()
    tab.toolController.activateTool("ct-window")
    assert not tab.registrationActive
    assert tab.toolController.activePanel == "ct-window"
    tab.setCtWindow(1999.72, 1589.13)
    np.testing.assert_array_equal(tab.matrix, transform)
    assert ct_view.overlayInfo["windowCenter"] == "2000"
    assert _display_number(29.9, 0) == "30"
    pet_window = tab.pet_display.target
    ct_view.applyColorMap("cardiac")
    assert ct_view.activeColorMap == "grayscale"
    assert tab.petColorMap == "grayscale-inverted"
    tab.setPetColorMap("cardiac")
    tab.setFusionColorMap("hotMetal")
    tab.setOpacity(.75)
    tab.toolController.activateTool("pseudocolor")
    tab.toolController.resetActiveTool()
    assert tab.petColorMap == "grayscale-inverted" and tab.fusionColorMap == "hotIron"
    assert tab.opacity == .75 and tab.pet_display.target == pet_window
    assert tab.ctCenter == 1999.72
    np.testing.assert_array_equal(tab.matrix, transform)
    tab.toolController.activateTool("fusion-blend")
    tab.toolController.resetActiveTool()
    assert tab.opacity == .5 and tab.pet_display.target == pet_window
    np.testing.assert_array_equal(tab.matrix, transform)
    assert [item["toolType"] for item in tab.toolController.tools][:5] == [
        "ct-window", "pet-window", "scroll", "pan", "zoom"]
    tab.toolController.activateTool("registration")
    tab.toolController.resetActiveTool()
    np.testing.assert_array_equal(tab.matrix, np.eye(4))
    assert tab.pet_display.target == pet_window
    assert tab.ctCenter == 1999.72
    tab.toolController.activateTool("pan")
    assert not tab.registrationActive
    assert ToolType.REGISTRATION.value in {t["toolType"] for t in tab.toolController.tools}
    tab.setCompactCrosshair(False)
    assert "armLength" not in fusion.crosshairStyle
    workspace.shutdown()


@pytest.mark.parametrize("missing_weight", [False, True])
def test_pet_volume_window_accounts_for_later_slice_uptake(paired_series, missing_weight):
    _, _, pet = paired_series
    for instance, upper in zip(pet.instances, (1000., 14000., 3000.)):
        ds = pydicom.dcmread(instance.path)
        ds.WindowCenter = upper / 2
        ds.WindowWidth = upper
        if missing_weight and upper == 14000:
            del ds.PatientWeight
        ds.save_as(instance.path, enforce_file_format=True)
    volume = VolumeManager().get_or_build(pet)
    scale = volume.pixel_value_meta.scale_from_source
    assert volume.default_window.width == pytest.approx(14000 * scale)
