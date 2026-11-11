"""Real compressed RAR4/5 and stream cancellation/rollback regressions."""

from pathlib import Path
import stat
import struct
import sys
from threading import Event
import zipfile

import pytest

from voxplane.core.local_import import (
    ImportCancelled,
    ImportErrorDetail,
    ImportLimits,
    LocalImportStore,
    _Preparation,
)
from rar_fixture import stored_rar

FIXTURES = Path(__file__).parent / "fixtures" / "rar"


def reference_data(size, magic=0):
    # libarchive's independently specified generate_testdata(), not decoder output.
    return b"".join(
        struct.pack("<I", max(0, k * k - 3 * k + 1 + magic))
        for k in range(1, size // 4 + 1)
    )


@pytest.mark.parametrize(
    "archive, expected",
    [
        (
            "test_rar.rar",
            {
                "test_file.txt": b"This is for test.",
                "test_file2.txt": b"This is another test!\n",
                "testfile": b"",
            },
        ),
        ("rar5-compressed.rar", {"test.bin": reference_data(1200)}),
        (
            "rar5-solid.rar",
            {f"test{i}.bin": reference_data(4096, i) for i in range(1, 5)},
        ),
    ],
)
def test_real_compressed_rar4_and_rar5_solid(tmp_path, archive, expected):
    source = FIXTURES / archive
    original = source.read_bytes()
    store = LocalImportStore(tmp_path / "cache")
    files = store.prepare([source])
    assert {p.name: p.read_bytes() for p in files} == expected
    assert all(p.is_relative_to(store.root) for p in files)
    assert source.read_bytes() == original


@pytest.mark.parametrize(
    "archive, message",
    [
        ("test_corrupted.rar", "RAR"),
        ("test_rar_pwd.rar", "加密"),
    ],
)
def test_bad_rar_and_password_errors_roll_back(tmp_path, archive, message):
    store = LocalImportStore(tmp_path / "cache")
    with pytest.raises(ImportErrorDetail, match=message):
        store.prepare([FIXTURES / archive])
    assert not list(store.root.iterdir())


def test_truncated_rar_data_cannot_be_imported_as_partial_file(tmp_path):
    source = stored_rar(
        tmp_path / "broken.rar", [("valid", b"first"), ("broken", b"x" * 200)]
    )
    source.write_bytes(source.read_bytes()[:-100])
    store = LocalImportStore(tmp_path / "cache")
    with pytest.raises(ImportErrorDetail):
        store.prepare([source])
    assert not list(store.root.iterdir())


@pytest.mark.parametrize(
    "name",
    [
        "../outside",
        "/absolute",
        "C:\\outside",
        "..\\outside",
        "folder/file:ads",
        "NUL.dcm",
    ],
)
def test_rar_paths_cannot_escape_cache(tmp_path, name):
    source = stored_rar(tmp_path / "bad.rar", [("valid", b"first"), (name, b"bad")])
    store = LocalImportStore(tmp_path / "cache")
    original = source.read_bytes()
    try:
        files = store.prepare([source])
    except ImportErrorDetail as error:
        assert "路径" in str(error)
        assert not list(store.root.iterdir())
    else:
        # Windows UnRAR can canonicalize invalid ':' characters in a header.
        # Accept that only when the returned names are safe ordinary cache files.
        assert sys.platform == "win32" and ":" in name, files
        assert len(files) == 2
        assert all(path.is_relative_to(store.root) and path.is_file() for path in files)
        assert all(":" not in path.relative_to(store.root).as_posix() for path in files)
        assert sorted(path.read_bytes() for path in files) == [b"bad", b"first"]
    assert source.read_bytes() == original
    assert not (tmp_path / "outside").exists()


@pytest.mark.parametrize("mode", [stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR])
def test_rar_links_and_special_files_are_rejected(tmp_path, mode):
    source = stored_rar(tmp_path / "link.rar", [("link", b"../outside", mode | 0o777)])
    store = LocalImportStore(tmp_path / "cache")
    with pytest.raises(ImportErrorDetail, match="链接|特殊"):
        store.prepare([source])
    assert not list(store.root.iterdir())


def test_rar_duplicate_case_and_volume_rejected(tmp_path):
    source = stored_rar(
        tmp_path / "duplicate.rar", [("Image", b"one"), ("image", b"two")]
    )
    store = LocalImportStore(tmp_path / "cache")
    with pytest.raises(ImportErrorDetail, match="冲突"):
        store.prepare([source])
    assert not list(store.root.iterdir())
    stored_rar(source, [("image", b"one")], volume=True)
    with pytest.raises(ImportErrorDetail, match="分卷"):
        store.prepare([source])
    assert not list(store.root.iterdir())


@pytest.mark.parametrize(
    "limits, message",
    [
        (ImportLimits(max_total_bytes=200), "体积"),
        (ImportLimits(max_file_bytes=200), "单个文件"),
        (ImportLimits(max_files=1), "数量"),
        (ImportLimits(max_rar_dictionary_bytes=1), "内存"),
    ],
)
def test_rar_decoded_stream_and_dictionary_limits(tmp_path, limits, message):
    store = LocalImportStore(tmp_path / "cache", limits=limits)
    with pytest.raises(ImportErrorDetail, match=message):
        store.prepare([FIXTURES / "rar5-solid.rar"])
    assert not list(store.root.iterdir())


def test_cancel_from_native_data_callback_rolls_back_only_new_cache(
    tmp_path, monkeypatch
):
    store = LocalImportStore(tmp_path / "cache")
    previous = store.prepare([FIXTURES / "test_rar.rar"])
    existing = set(store.root.iterdir())
    cancelled = Event()
    original = _Preparation.account
    chunks = []

    def account(self, size, file_size):
        original(self, size, file_size)
        chunks.append(size)
        cancelled.set()

    monkeypatch.setattr(_Preparation, "account", account)
    with pytest.raises(ImportCancelled):
        store.prepare([FIXTURES / "rar5-solid.rar"], cancelled=cancelled.is_set)
    assert chunks and chunks[0] > 0
    assert set(store.root.iterdir()) == existing
    assert all(p.exists() for p in previous)


def test_extensionless_rar_inside_zip_and_empty_unicode_member(tmp_path):
    inner = stored_rar(
        tmp_path / "without-extension",
        [("影像/空文件.dcm", b""), ("影像/文件.dcm", b"dicom")],
    )
    outer = tmp_path / "outer.zip"
    with zipfile.ZipFile(outer, "w") as out:
        out.write(inner, "无后缀压缩包")
    files = LocalImportStore(tmp_path / "cache").prepare([outer])
    assert {p.name: p.read_bytes() for p in files} == {
        "空文件.dcm": b"",
        "文件.dcm": b"dicom",
    }
