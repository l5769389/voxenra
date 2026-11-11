import numpy as np
import pytest

from voxplane.application.series_catalog import SeriesCatalog
from voxplane.core.mpr_reslicer import MprReslicer
from voxplane.core.mpr_rotation import (
    move_mpr_state_center,
    rotate_crosshair_state,
    rotate_mpr_state_3d,
)
from voxplane.core.volume_manager import VolumeManager
from voxplane.model import (
    InstanceDisplayMeta,
    MprPlane,
    MprProjectionMode,
    MprRenderRequest,
    RenderResult,
    WindowLevel,
)
from voxplane.model.dicom_core import (
    DicomVolume,
    MprFrame,
    MprImageGeometry,
    MprState,
    MprViewAnchors,
    VolumeGeometry,
)
from voxplane.ui.workers.dicom_render_worker import (
    DicomRenderWorker,
)


def _instance_meta() -> InstanceDisplayMeta:
    return InstanceDisplayMeta(
        instance_number=1,
        sop_instance_uid="sop-1",
        manufacturer=None,
        kvp=None,
        tube_current_ma=None,
        slice_thickness=1.0,
        rows=3,
        columns=4,
        pixel_spacing=(1.0, 1.0),
        image_position=(0.0, 0.0, 0.0),
        slice_location=0.0,
    )


def _volume(
    pixels: np.ndarray,
    *,
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0),
    row_direction: tuple[float, float, float] = (1.0, 0.0, 0.0),
    column_direction: tuple[float, float, float] = (0.0, 1.0, 0.0),
    slice_direction: tuple[float, float, float] = (0.0, 0.0, 1.0),
    slice_spacing: float = 1.0,
    row_spacing: float = 1.0,
    column_spacing: float = 1.0,
) -> DicomVolume:
    return DicomVolume(
        modality_pixels=np.ascontiguousarray(
            pixels,
            dtype=np.float32,
        ),
        geometry=VolumeGeometry(
            slice_count=pixels.shape[0],
            rows=pixels.shape[1],
            columns=pixels.shape[2],
            row_spacing=row_spacing,
            column_spacing=column_spacing,
            slice_spacing=slice_spacing,
            origin_patient=origin,
            slice_index_direction_patient=slice_direction,
            row_index_direction_patient=column_direction,
            column_index_direction_patient=row_direction,
        ),
        series_uid="series-1",
        default_window=WindowLevel(
            center=40.0,
            width=400.0,
        ),
        representative_instance_meta=_instance_meta(),
    )


def test_volume_geometry_round_trips_voxel_and_patient_coordinates() -> None:
    volume = _volume(
        np.zeros((2, 3, 4), dtype=np.float32),
        origin=(10.0, 20.0, 30.0),
        slice_spacing=2.5,
        row_spacing=0.7,
        column_spacing=0.8,
    )
    voxel = np.asarray([1.0, 2.0, 3.0, 1.0])

    patient = volume.geometry.voxel_to_patient @ voxel
    reconstructed = (
        volume.geometry.patient_to_voxel @ patient
    )

    np.testing.assert_allclose(
        patient,
        [12.4, 21.4, 32.5, 1.0],
    )
    np.testing.assert_allclose(reconstructed, voxel)


def test_mpr_frame_maps_physical_coordinates_to_patient_lps() -> None:
    frame = MprFrame.standard_lps((12.0, 22.0, 32.0))
    mpr = np.asarray([2.25, 1.0, 1.25, 1.0])

    patient = frame.mpr_to_patient @ mpr

    np.testing.assert_allclose(
        patient,
        [14.25, 23.0, 33.25, 1.0],
    )
    np.testing.assert_allclose(
        frame.patient_to_mpr @ patient,
        mpr,
    )


def test_mpr_image_geometry_uses_the_full_coordinate_chain() -> None:
    volume = _volume(
        np.zeros((4, 5, 6), dtype=np.float32),
        origin=(10.0, 20.0, 30.0),
        slice_spacing=2.5,
        row_spacing=0.7,
        column_spacing=0.8,
    )
    frame = MprFrame.standard_lps((12.0, 22.0, 32.0))
    geometry = MprImageGeometry(
        rows=5,
        columns=6,
        row_spacing=0.5,
        column_spacing=0.75,
        navigation_spacing=1.25,
        frame=frame,
        image_origin_mpr=(0.0, 0.0, 0.0),
        row_direction_mpr=(0.0, 1.0, 0.0),
        column_direction_mpr=(1.0, 0.0, 0.0),
        navigation_direction_mpr=(0.0, 0.0, 1.0),
    )
    image_index = np.asarray([1.0, 2.0, 3.0, 1.0])

    mpr = geometry.image_index_to_mpr @ image_index
    patient = geometry.image_index_to_patient @ image_index
    voxel = geometry.image_index_to_voxel(
        volume.geometry
    ) @ image_index

    np.testing.assert_allclose(
        mpr,
        [2.25, 1.0, 1.25, 1.0],
    )
    np.testing.assert_allclose(
        patient,
        [14.25, 23.0, 33.25, 1.0],
    )
    np.testing.assert_allclose(
        geometry.patient_to_image_index @ patient,
        image_index,
    )
    np.testing.assert_allclose(
        voxel,
        volume.geometry.patient_to_voxel @ patient,
    )
    np.testing.assert_allclose(
        geometry.voxel_to_image_index(volume.geometry) @ voxel,
        image_index,
    )


def test_standard_planes_follow_lps_display_directions() -> None:
    pixels = np.arange(
        2 * 3 * 4,
        dtype=np.float32,
    ).reshape(2, 3, 4)
    volume = _volume(pixels)
    reslicer = MprReslicer()

    axial = reslicer.reslice(
        volume,
        MprPlane.AXIAL,
    )
    coronal = reslicer.reslice(
        volume,
        MprPlane.CORONAL,
    )
    sagittal = reslicer.reslice(
        volume,
        MprPlane.SAGITTAL,
    )

    np.testing.assert_allclose(
        axial.modality_pixels,
        (pixels[0, :, :] + pixels[1, :, :]) / 2.0,
    )
    np.testing.assert_allclose(
        coronal.modality_pixels,
        np.stack(
            [pixels[1, 1, :], pixels[0, 1, :]],
        ),
    )
    np.testing.assert_allclose(
        sagittal.modality_pixels,
        np.stack(
            [
                (
                    pixels[1, :, 1]
                    + pixels[1, :, 2]
                ) / 2.0,
                (
                    pixels[0, :, 1]
                    + pixels[0, :, 2]
                ) / 2.0,
            ],
        ),
    )

    for result in (axial, coronal, sagittal):
        assert result.geometry.plane_offset_mpr == 0.0
        origin_image_index = (
            result.geometry.mpr_to_image_index
            @ np.asarray([0.0, 0.0, 0.0, 1.0])
        )
        np.testing.assert_allclose(
            origin_image_index[0],
            0.0,
            atol=1e-8,
        )

    assert axial.slice_count == 2
    assert coronal.slice_count == 3
    assert sagittal.slice_count == 4

    assert axial.geometry.image_orientation_patient == (
        1.0, 0.0, 0.0,
        0.0, 1.0, 0.0,
    )
    assert coronal.geometry.image_orientation_patient == (
        1.0, 0.0, 0.0,
        0.0, 0.0, -1.0,
    )
    assert sagittal.geometry.image_orientation_patient == (
        0.0, 1.0, 0.0,
        0.0, 0.0, -1.0,
    )

    # Sagittal 视图沿 +U 翻页，而 IOP 两个方向的叉乘为 -U。
    # 两者均垂直于平面，但其有向语义不同，不能混用。
    np.testing.assert_allclose(
        sagittal.geometry.navigation_direction_patient,
        [1.0, 0.0, 0.0],
    )
    np.testing.assert_allclose(
        sagittal.geometry.iop_normal_direction_patient,
        [-1.0, 0.0, 0.0],
    )
    np.testing.assert_allclose(
        sagittal.geometry.navigation_position_patient,
        np.dot(
            sagittal.geometry.image_origin_patient,
            sagittal.geometry.navigation_direction_patient,
        ),
    )


@pytest.mark.parametrize(
    ("mode", "expected"),
    (
        (MprProjectionMode.MIN_IP, 1.0),
        (MprProjectionMode.MIP, 7.0),
        (MprProjectionMode.MEAN, 3.6),
        (MprProjectionMode.SUM, 18.0),
    ),
)
def test_mpr_slab_projection_aggregates_symmetric_samples(
    mode: MprProjectionMode,
    expected: float,
) -> None:
    pixels = np.asarray([1.0, 5.0, 3.0, 7.0, 2.0])[:, None, None]
    volume = _volume(pixels)

    result = MprReslicer().reslice(
        volume,
        MprPlane.AXIAL,
        projection_mode=mode,
        slab_thickness_mm=4.0,
    )

    np.testing.assert_allclose(result.modality_pixels, [[expected]])


def test_mpr_slab_ignores_samples_outside_volume() -> None:
    pixels = np.asarray([1.0, 5.0, 3.0, 7.0, 2.0])[:, None, None]
    volume = _volume(pixels)
    frame = MprFrame.standard_lps((0.0, 0.0, 0.0))

    result = MprReslicer().reslice(
        volume,
        MprPlane.AXIAL,
        frame=frame,
        projection_mode=MprProjectionMode.MEAN,
        slab_thickness_mm=4.0,
    )

    np.testing.assert_allclose(result.modality_pixels, [[3.0]])


def test_mpr_slab_preserves_nan_when_every_sample_is_outside_volume() -> None:
    volume = _volume(np.ones((3, 2, 2), dtype=np.float32))
    frame = MprFrame.standard_lps((0.0, 0.0, 100.0))

    result = MprReslicer().reslice(
        volume,
        MprPlane.AXIAL,
        frame=frame,
        projection_mode=MprProjectionMode.MIP,
        slab_thickness_mm=2.0,
    )

    assert np.isnan(result.modality_pixels).all()


def test_zero_thickness_projection_matches_single_plane_path() -> None:
    volume = _volume(
        np.arange(3 * 4 * 5, dtype=np.float32).reshape(3, 4, 5)
    )
    reslicer = MprReslicer()

    single = reslicer.reslice(volume, MprPlane.CORONAL)
    zero_slab = reslicer.reslice(
        volume,
        MprPlane.CORONAL,
        projection_mode=MprProjectionMode.MIP,
        slab_thickness_mm=0.0,
    )

    np.testing.assert_array_equal(
        zero_slab.modality_pixels,
        single.modality_pixels,
    )


@pytest.mark.parametrize("thickness", [-1.0, 100.1, float("nan")])
def test_mpr_slab_rejects_invalid_thickness(thickness: float) -> None:
    volume = _volume(np.ones((3, 2, 2), dtype=np.float32))

    with pytest.raises(RuntimeError, match="Slab thickness"):
        MprReslicer().reslice(
            volume,
            MprPlane.AXIAL,
            projection_mode=MprProjectionMode.MIP,
            slab_thickness_mm=thickness,
        )


def test_reslice_uses_the_supplied_mpr_frame_axes() -> None:
    volume = _volume(
        np.arange(
            2 * 3 * 4,
            dtype=np.float32,
        ).reshape(2, 3, 4)
    )
    frame = MprFrame(
        center_patient=volume.geometry.center_patient,
        u_direction_patient=(0.0, 1.0, 0.0),
        v_direction_patient=(-1.0, 0.0, 0.0),
        w_direction_patient=(0.0, 0.0, 1.0),
    )

    axial = MprReslicer().reslice(
        volume,
        MprPlane.AXIAL,
        frame=frame,
    )

    assert axial.geometry.frame == frame
    assert axial.geometry.image_orientation_patient == (
        0.0, 1.0, 0.0,
        -1.0, 0.0, 0.0,
    )


def test_crosshair_rotation_keeps_source_reslice_unchanged() -> None:
    """这是 view roll 补偿最重要的端到端数学契约。"""
    volume = _volume(
        np.arange(5 * 6 * 7, dtype=np.float32).reshape(5, 6, 7),
        slice_spacing=1.4,
        row_spacing=0.8,
        column_spacing=1.1,
    )
    state = MprState(
        MprFrame.standard_lps(volume.geometry.center_patient)
    )
    reslicer = MprReslicer()
    grids = reslicer.create_view_grids(volume, state.frame)
    state = MprState(state.frame, view_grids=grids)
    rotated = rotate_crosshair_state(
        state,
        MprPlane.AXIAL,
        0.37,
    )
    assert rotated.view_grids is grids

    before = reslicer.reslice(
        volume,
        MprPlane.AXIAL,
        frame=state.frame,
        grid_spec=grids.axial,
    )
    after = reslicer.reslice(
        volume,
        MprPlane.AXIAL,
        frame=rotated.frame,
        view_roll_radians=rotated.view_rolls.axial_radians,
        grid_spec=grids.axial,
    )

    np.testing.assert_allclose(
        after.geometry.image_index_to_patient,
        before.geometry.image_index_to_patient,
        atol=1e-10,
    )
    np.testing.assert_allclose(
        after.modality_pixels,
        before.modality_pixels,
        atol=1e-5,
    )


def test_fixed_grid_keeps_size_spacing_and_center_during_3d_rotation() -> None:
    volume = _volume(
        np.arange(5 * 6 * 7, dtype=np.float32).reshape(5, 6, 7),
        slice_spacing=1.4,
        row_spacing=0.8,
        column_spacing=1.1,
    )
    reslicer = MprReslicer()
    frame = MprFrame.standard_lps(volume.geometry.center_patient)
    grids = reslicer.create_view_grids(volume, frame)
    state = MprState(frame, view_grids=grids)
    rotated = rotate_mpr_state_3d(
        state,
        (1.0, 2.0, -0.5),
        0.61,
    )
    assert rotated.view_grids is grids

    before = reslicer.reslice(
        volume,
        MprPlane.CORONAL,
        frame=state.frame,
        grid_spec=grids.coronal,
    )
    after = reslicer.reslice(
        volume,
        MprPlane.CORONAL,
        frame=rotated.frame,
        grid_spec=grids.coronal,
    )

    assert before.modality_pixels.shape == after.modality_pixels.shape
    assert after.geometry.rows == grids.coronal.rows
    assert after.geometry.columns == grids.coronal.columns
    assert after.geometry.row_spacing == grids.coronal.row_spacing
    assert (
        after.geometry.column_spacing
        == grids.coronal.column_spacing
    )
    center_index = after.geometry.patient_to_image_index @ np.asarray(
        [*rotated.frame.center_patient, 1.0],
        dtype=np.float64,
    )
    np.testing.assert_allclose(
        center_index,
        (
            0.0,
            (grids.coronal.rows - 1) / 2.0,
            (grids.coronal.columns - 1) / 2.0,
            1.0,
        ),
        atol=1e-10,
    )
    assert not np.allclose(
        before.geometry.image_orientation_patient,
        after.geometry.image_orientation_patient,
    )


def test_moving_crosshair_updates_anchor_without_reversing_source_image() -> None:
    volume = _volume(
        np.arange(5 * 6 * 7, dtype=np.float32).reshape(5, 6, 7),
        slice_spacing=1.4,
        row_spacing=0.8,
        column_spacing=1.1,
    )
    reslicer = MprReslicer()
    frame = MprFrame.standard_lps(volume.geometry.center_patient)
    grids = reslicer.create_view_grids(volume, frame)
    anchors = MprViewAnchors.centered(grids)
    state = MprState(
        frame,
        view_grids=grids,
        view_anchors=anchors,
    )
    next_center = (
        frame.center_patient[0] + 2.0 * grids.axial.column_spacing,
        frame.center_patient[1] + grids.axial.row_spacing,
        frame.center_patient[2],
    )
    moved = move_mpr_state_center(state, next_center)

    before = reslicer.reslice(
        volume,
        MprPlane.AXIAL,
        frame=state.frame,
        grid_spec=grids.axial,
        grid_anchor=anchors.axial,
    )
    after = reslicer.reslice(
        volume,
        MprPlane.AXIAL,
        frame=moved.frame,
        grid_spec=grids.axial,
        grid_anchor=moved.view_anchors.axial,
    )

    assert moved.view_anchors is not None
    assert moved.view_anchors.axial.column == pytest.approx(
        anchors.axial.column + 2.0
    )
    assert moved.view_anchors.axial.row == pytest.approx(
        anchors.axial.row + 1.0
    )
    np.testing.assert_allclose(
        after.geometry.image_index_to_patient,
        before.geometry.image_index_to_patient,
        atol=1e-10,
    )
    np.testing.assert_allclose(
        after.modality_pixels,
        before.modality_pixels,
        atol=1e-5,
    )


def test_standard_planes_preserve_directional_source_spacing() -> None:
    volume = _volume(
        np.zeros((4, 5, 6), dtype=np.float32),
        slice_spacing=0.6,
        row_spacing=0.9,
        column_spacing=1.2,
    )
    reslicer = MprReslicer()

    axial = reslicer.reslice(volume, MprPlane.AXIAL)
    coronal = reslicer.reslice(volume, MprPlane.CORONAL)
    sagittal = reslicer.reslice(volume, MprPlane.SAGITTAL)

    assert axial.modality_pixels.shape == (5, 6)
    assert axial.slice_count == 4
    np.testing.assert_allclose(
        [
            axial.geometry.row_spacing,
            axial.geometry.column_spacing,
            axial.geometry.navigation_spacing,
        ],
        [0.9, 1.2, 0.6],
    )

    assert coronal.modality_pixels.shape == (4, 6)
    assert coronal.slice_count == 5
    np.testing.assert_allclose(
        [
            coronal.geometry.row_spacing,
            coronal.geometry.column_spacing,
            coronal.geometry.navigation_spacing,
        ],
        [0.6, 1.2, 0.9],
    )

    assert sagittal.modality_pixels.shape == (4, 5)
    assert sagittal.slice_count == 6
    np.testing.assert_allclose(
        [
            sagittal.geometry.row_spacing,
            sagittal.geometry.column_spacing,
            sagittal.geometry.navigation_spacing,
        ],
        [0.6, 0.9, 1.2],
    )


def test_axial_reslice_reorients_a_rotated_source_volume() -> None:
    pixels = np.arange(
        2 * 3 * 4,
        dtype=np.float32,
    ).reshape(2, 3, 4)
    volume = _volume(
        pixels,
        origin=(2.0, 0.0, 0.0),
        row_direction=(0.0, 1.0, 0.0),
        column_direction=(-1.0, 0.0, 0.0),
        slice_direction=(0.0, 0.0, 1.0),
    )

    axial = MprReslicer().reslice(
        volume,
        MprPlane.AXIAL,
    )
    center_slice = (pixels[0] + pixels[1]) / 2.0
    expected = np.asarray(
        [
            [center_slice[2, 0], center_slice[1, 0], center_slice[0, 0]],
            [center_slice[2, 1], center_slice[1, 1], center_slice[0, 1]],
            [center_slice[2, 2], center_slice[1, 2], center_slice[0, 2]],
            [center_slice[2, 3], center_slice[1, 3], center_slice[0, 3]],
        ],
        dtype=np.float32,
    )

    np.testing.assert_allclose(
        axial.modality_pixels,
        expected,
    )


def test_trilinear_interpolation_samples_between_voxels() -> None:
    pixels = np.zeros((2, 2, 2), dtype=np.float32)
    for slice_index in range(2):
        for row_index in range(2):
            for column_index in range(2):
                pixels[slice_index, row_index, column_index] = (
                    slice_index + row_index + column_index
                )

    coordinate = np.asarray([[0.5]], dtype=np.float64)
    sampled = MprReslicer._trilinear_sample(
        pixels,
        coordinate,
        coordinate,
        coordinate,
    )

    np.testing.assert_allclose(sampled, [[1.5]])


def test_sample_count_ignores_floating_point_noise_near_integer() -> None:
    spacing = 0.24
    extent = np.nextafter(
        319 * spacing,
        np.inf,
    )

    assert MprReslicer._sample_count(extent, spacing) == 320


def test_render_worker_returns_patient_space_mpr_result(
    monkeypatch,
) -> None:
    volume = _volume(
        np.arange(
            2 * 3 * 4,
            dtype=np.float32,
        ).reshape(2, 3, 4)
    )

    catalog = SeriesCatalog()
    monkeypatch.setattr(
        catalog,
        "get_series",
        lambda series_uid: (
            __import__("types").SimpleNamespace(modality="CT") if series_uid == "series-1" else None
        ),
    )
    volume_manager = VolumeManager()
    monkeypatch.setattr(
        volume_manager,
        "get_or_build",
        lambda series: volume,
    )
    worker = DicomRenderWorker(
        catalog,
        volume_manager,
    )
    results: list[RenderResult] = []
    worker.render_finished.connect(results.append)

    worker.handleRenderRequest(
        MprRenderRequest(
            request_id="request-1",
            viewport_id="viewport-coronal",
            series_uid="series-1",
            plane=MprPlane.CORONAL,
            window=None,
            inverted=False,
            mpr_frame=None,
        )
    )

    assert len(results) == 1
    result = results[0]
    assert result.image is not None
    assert result.image.shape == (2, 4)
    assert result.modality_pixel is not None
    assert result.frame_meta.slice_index == 1
    assert result.frame_meta.slice_count == 3
    assert result.frame_meta.geometry.image_orientation_patient == (
        1.0, 0.0, 0.0,
        0.0, 0.0, -1.0,
    )
    assert result.mpr_view_grids is not None
    assert result.mpr_view_grids.coronal.rows == result.image.shape[0]
    assert result.mpr_view_grids.coronal.columns == result.image.shape[1]
