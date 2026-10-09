"""Bound transient volume storage without changing source values or cache validity."""
from hashlib import sha256
import os
from pathlib import Path
from threading import Event
import weakref

import numpy as np
import pydicom
import pytest

from qt_dicom_viewer.core.dicom_loader import DicomLoader
from qt_dicom_viewer.core.render_cancellation import render_cancellation
from qt_dicom_viewer.core.volume_manager import VolumeManager, series_fingerprint
from test_enhanced_ct import save_and_scan
from test_mr import write_mr_series
from test_pet_fusion import paired_series


@pytest.mark.parametrize("budget,frame_limit", [(2 * 64 * 64 * 4, 12), (1_000_000, 2)])
def test_decoded_cache_limits_and_lru(tmp_path, budget, frame_limit):
    series = write_mr_series(tmp_path, count=4)
    paths = [i.path for i in series.instances]
    loader = DicomLoader(maximum_cache_bytes=budget, maximum_cache_frames=frame_limit)
    first = loader.read_frame(paths[0])[1]
    second = weakref.ref(loader.read_frame(paths[1])[1])
    assert loader.read_frame(paths[0])[1] is first  # Promote the cache hit.
    third = loader.read_frame(paths[2])[1]
    assert second() is None  # Evict the least recently used, not the oldest inserted.
    assert loader.cache_bytes == first.nbytes + third.nbytes
    assert loader.read_frame(paths[0])[1] is first


def test_oversized_current_decode_remains_cached(tmp_path):
    series = write_mr_series(tmp_path, count=2)
    loader = DicomLoader(maximum_cache_bytes=1)
    first = weakref.ref(loader.read_frame(series.instances[0].path)[1])
    current = loader.read_frame(series.instances[1].path)[1]
    assert first() is None
    assert loader.cache_bytes == current.nbytes
    assert loader.read_frame(series.instances[1].path)[1] is current


def test_replaced_source_invalidates_pixels_and_header(tmp_path):
    series = write_mr_series(tmp_path, count=2)
    path = series.instances[0].path
    loader = DicomLoader()
    original_header, original = loader.read_frame(path)
    previous_stat = path.stat()
    dataset = pydicom.dcmread(path)
    dataset.RescaleIntercept = -100
    dataset.save_as(path, enforce_file_format=True)
    os.utime(path, ns=(previous_stat.st_atime_ns, previous_stat.st_mtime_ns + 1_000_000))
    header, pixels = loader.read_frame(path)
    assert header is not original_header and header.RescaleIntercept == -100
    np.testing.assert_array_equal(pixels, original - 100)


def test_volume_releases_consumed_frames(tmp_path, monkeypatch):
    series = write_mr_series(tmp_path, count=24,
                             change=lambda d, z: setattr(d, "RescaleIntercept", -z / 2))
    read = DicomLoader.read_frame
    references, live = [], []

    def tracked(self, *args, **kwargs):
        result = read(self, *args, **kwargs)
        references.append(weakref.ref(result[1]))
        live.append(sum(ref() is not None for ref in references))
        return result

    monkeypatch.setattr(DicomLoader, "read_frame", tracked)
    volume = VolumeManager().get_or_build(series)
    assert max(live) <= 2  # Current decode plus the preceding loop's local variable.
    assert all(ref() is None for ref in references)
    expected = np.arange(64 * 64, dtype=np.float32).reshape(64, 64)
    for z in range(24):
        np.testing.assert_array_equal(volume.modality_pixels[z], expected - z / 2)
    assert volume.modality_pixels.dtype == np.float32 and volume.modality_pixels.flags.c_contiguous


def test_pet_fallback_shares_source_without_mixing_units(paired_series):
    _, _, series = paired_series
    last = series.instances[-1].path
    dataset = pydicom.dcmread(last)
    del dataset.PatientWeight
    dataset.RescaleSlope = .5
    dataset.save_as(last, enforce_file_format=True)
    manager = VolumeManager()
    volume = manager.get_or_build(series)
    assert volume.modality_pixels is volume.source_pixels
    assert volume.suv_pixels is None
    assert volume.pixel_value_meta.unit_id == "source"
    assert volume.pixel_value_meta.quantification == "unavailable"
    assert manager.cache_bytes == volume.modality_pixels.nbytes
    np.testing.assert_array_equal(volume.modality_pixels[:, 1, 2], [1000, 2000, 1500])
    np.testing.assert_allclose(volume.in_unit("kbqml").modality_pixels[:, 1, 2], [1, 2, 1.5],
                               rtol=1e-6, atol=1e-4)


@pytest.mark.parametrize("stop_at", [2, 6])
@pytest.mark.parametrize("failure", ["cancel", "decode"])
def test_interrupted_rebuild_keeps_last_complete_volume(tmp_path, monkeypatch, stop_at, failure):
    series = write_mr_series(tmp_path, count=6)
    manager = VolumeManager()
    original = manager.get_or_build(series)
    original_fingerprint = original.fingerprint
    path = series.instances[0].path
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    read = DicomLoader.read_frame
    event = Event()
    reads = 0

    def interrupted(self, *args, **kwargs):
        nonlocal reads
        reads += 1
        result = read(self, *args, **kwargs)
        if reads == stop_at:
            if failure == "decode":
                raise ValueError("broken frame")
            event.set()
        return result

    monkeypatch.setattr(DicomLoader, "read_frame", interrupted)
    with render_cancellation(event), pytest.raises(InterruptedError if failure == "cancel" else ValueError):
        manager.get_or_build(series)
    assert manager.get_volume(series.series_instance_uid) is original
    assert original.fingerprint == original_fingerprint
    monkeypatch.setattr(DicomLoader, "read_frame", read)
    restored = manager.get_or_build(series)
    assert restored is not original and restored.fingerprint != original_fingerprint
    np.testing.assert_array_equal(restored.modality_pixels, original.modality_pixels)


def test_enhanced_fingerprint_stats_each_file_once_and_refreshes(tmp_path, monkeypatch):
    path, snapshot = save_and_scan(tmp_path)
    series = snapshot.series[0]
    stat = path.stat()
    entries = [(i.sop_instance_uid, i.frame_index, i.image_position_patient, i.image_orientation_patient,
                i.rows, i.columns, i.pixel_spacing, i.frame_of_reference_uid, str(i.path),
                stat.st_size, stat.st_mtime_ns) for i in series.instances]
    expected = sha256(repr(entries).encode()).hexdigest()
    original_stat, calls = Path.stat, []

    def counted(self, *args, **kwargs):
        if self == path:
            calls.append(self)
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", counted)
    assert series_fingerprint(series) == expected
    assert len(calls) == 1
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert series_fingerprint(series) != expected
    assert len(calls) == 2
