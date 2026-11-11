"""Prepare local inputs in a private session directory; never extract into sources."""
from voxplane.i18n import message as _msg

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import bz2
import gzip
import lzma
import re
import shutil
import stat
import tarfile
import tempfile
import zipfile
import time

from voxplane.core.dicom_scanner import _iter_visible_files


class ImportCancelled(Exception):
    pass


class ImportErrorDetail(ValueError):
    """User-readable import error without patient paths or archive member names."""


@dataclass(frozen=True)
class ImportLimits:
    max_files: int = 100_000
    max_file_bytes: int = 8 * 1024**3
    max_total_bytes: int = 32 * 1024**3
    max_depth: int = 3
    max_rar_dictionary_bytes: int = 512 * 1024**2


def archive_kind(path):
    name = path.name.lower()
    if name.endswith(
        (".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz", ".tar")
    ):
        return "tar"
    if name.endswith(".zip"):
        return "zip"
    if name.endswith(".7z"):
        return "7z"
    if name.endswith((".rar", ".r00")):
        return "rar"
    if name.endswith(".gz"):
        return "gz"
    if name.endswith(".bz2"):
        return "bz2"
    if name.endswith(".xz"):
        return "xz"
    # Archives are sometimes sent without an extension.
    with path.open("rb") as stream:
        header = stream.read(8)
    if header.startswith(b"PK\x03\x04"):
        return "zip"
    if header.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "7z"
    if header.startswith(b"Rar!"):
        return "rar"
    if header.startswith(b"\x1f\x8b"):
        return "gz"
    return ""


def safe_member(name):
    name = str(name).replace("\\", "/")
    parts = PurePosixPath(name).parts
    if (
        not parts
        or name.startswith("/")
        or any(part in ("..", "") for part in parts)
        or any(":" in p or "\0" in p or p.endswith((" ", ".")) for p in parts)
        or any(
            re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", p)
            for p in parts
        )
    ):
        raise ImportErrorDetail(_msg('text.0193'))
    return Path(*parts)


class LocalImportStore:
    """Keep extracted inputs alive until render/export workers have shut down."""

    def __init__(self, root=None, limits=ImportLimits()):
        self._temporary = None
        self._root = Path(root) if root is not None else None
        self.limits = limits
        self._archive_sources = {}

    def source_for(self, path):
        """Resolve extracted instances back to the persistent outer archive."""
        path = Path(path).resolve()
        for folder, source in reversed(tuple(self._archive_sources.items())):
            if path.is_relative_to(folder):
                return source
        return path

    @property
    def root(self):
        if self._root is None:
            self._temporary = tempfile.TemporaryDirectory(prefix="voxplane-import-")
            self._root = Path(self._temporary.name)
        self._root = self._root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        return self._root

    def cleanup(self):
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None
            self._root = None
        self._archive_sources.clear()

    def prepare(self, paths, *, cancelled=lambda: False, progress=lambda message: None):
        preparation = _Preparation(self, cancelled, progress)
        try:
            preparation.report(_msg('text.0194'), force=True)
            result, seen = [], set()
            for value in paths:
                preparation.check()
                path = Path(value).expanduser().resolve()
                if path in seen:
                    continue
                seen.add(path)
                if not path.exists():
                    raise ImportErrorDetail(_msg('text.0195'))
                if path.is_dir():
                    def unreadable(error):
                        raise ImportErrorDetail(_msg('text.0196')) from error
                    def checkpoint():
                        preparation.check()
                        preparation.report(_msg('text.0194'))
                    for file in _iter_visible_files(path, checkpoint=checkpoint, onerror=unreadable):
                        if (
                            self._root is not None
                            and not path.is_relative_to(self._root)
                            and file.resolve().is_relative_to(self._root)
                        ):
                            continue
                        if not file.is_symlink():
                            result.extend(preparation.input(file, 0))
                elif path.is_file():
                    result.extend(preparation.input(path, 0))
                else:
                    raise ImportErrorDetail(_msg('text.0197'))
            preparation.check()
            return tuple(dict.fromkeys(p.resolve() for p in result))
        except BaseException:
            for folder in preparation.created:
                shutil.rmtree(folder, ignore_errors=True)
            raise


class _Preparation:
    def __init__(self, store, cancelled, progress):
        self.store, self.cancelled, self.progress = store, cancelled, progress
        self.created, self.seen = [], set()
        self.count, self.bytes = 0, 0
        self._last_report = 0.0
        self._phase = _msg('text.0194')

    def report(self, phase=None, *, force=False):
        if phase:
            self._phase = phase
        now = time.monotonic()
        if force or now - self._last_report >= 0.15:
            self._last_report = now
            detail = _msg('text.0198', value1=f'{self.count:,}')
            if self.bytes:
                detail += _msg('text.0199', value1=f'{self.bytes / 1024 ** 2:.1f}')
            self.progress(self._phase + detail)

    def check(self):
        if self.cancelled():
            raise ImportCancelled()

    def count_file(self, size=0):
        self.check()
        self.count += 1
        if self.count > self.store.limits.max_files:
            raise ImportErrorDetail(_msg('text.0200', value1=f'{self.store.limits.max_files:,}'))
        if size < 0 or size > self.store.limits.max_file_bytes:
            raise ImportErrorDetail(_msg('text.0201'))

    def account(self, size, file_size):
        self.check()
        self.bytes += size
        self.report()
        limits = self.store.limits
        if file_size > limits.max_file_bytes or self.bytes > limits.max_total_bytes:
            raise ImportErrorDetail(_msg('text.0202'))

    def copy(self, source, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        total = 0
        with target.open("xb") as output:
            while True:
                self.check()
                data = source.read(1024 * 1024)
                if not data:
                    break
                total += len(data)
                self.account(len(data), total)
                output.write(data)
        return target

    def member(self, root, name, used):
        relative = safe_member(name)
        key = relative.as_posix().casefold()
        if key in used:
            raise ImportErrorDetail(_msg('text.0203'))
        used.add(key)
        return root / relative

    def input(self, path, depth):
        self.check()
        path = path.resolve()
        if path in self.seen:
            return []
        self.seen.add(path)
        try:
            kind = archive_kind(path)
        except OSError as error:
            raise ImportErrorDetail(_msg('text.0204')) from error
        if not kind:
            if depth == 0:
                self.count_file()
            return [path]
        if depth >= self.store.limits.max_depth:
            raise ImportErrorDetail(_msg('text.0205'))
        root = Path(tempfile.mkdtemp(prefix="archive-", dir=self.store.root))
        self.store._archive_sources[root] = self.store.source_for(path)
        self.created.append(root)
        self.report(_msg('text.0206'))
        used, extracted = set(), []
        try:
            if kind == "zip":
                with zipfile.ZipFile(path) as archive:
                    for info in archive.infolist():
                        self.check()
                        target = self.member(root, info.filename, used)
                        mode = stat.S_IFMT(info.external_attr >> 16)
                        if mode not in (0, stat.S_IFREG, stat.S_IFDIR):
                            raise ImportErrorDetail(
                                _msg('text.0110')
                            )
                        if info.flag_bits & 1:
                            raise ImportErrorDetail(_msg('text.0207'))
                        if info.is_dir():
                            continue
                        self.count_file(info.file_size)
                        with archive.open(info) as stream:
                            extracted.append(self.copy(stream, target))
            elif kind == "tar":
                with tarfile.open(path, "r:*") as archive:
                    for info in archive:
                        self.check()
                        if info.isdir() and info.name in (".", "./", ""):
                            continue
                        target = self.member(root, info.name, used)
                        if info.isdir():
                            continue
                        if not info.isfile():
                            raise ImportErrorDetail(
                                _msg('text.0110')
                            )
                        self.count_file(info.size)
                        with archive.extractfile(info) as stream:
                            extracted.append(self.copy(stream, target))
            elif kind == "7z":
                extracted = self.seven_zip(path, root, used)
            elif kind == "rar":
                from .rar_archive import extract_rar

                extracted = extract_rar(path, self, root, used)
            else:
                self.count_file()
                target = root / "decompressed.dcm"
                opener = {"gz": gzip.open, "bz2": bz2.open, "xz": lzma.open}[kind]
                with opener(path, "rb") as stream:
                    extracted.append(self.copy(stream, target))
            result = []
            for file in extracted:
                # Ignore resource forks and packaging metadata, as folder imports do.
                if any(
                    p.startswith(".") or p == "__MACOSX"
                    for p in file.relative_to(root).parts
                ):
                    continue
                result.extend(self.input(file, depth + 1))
            return result
        except (ImportCancelled, ImportErrorDetail):
            raise
        except Exception as error:
            raise ImportErrorDetail(
                _msg('text.0208')
            ) from error

    def seven_zip(self, path, root, used):
        import py7zr

        preparation = self
        targets, streams = {}, []

        class Output(py7zr.Py7zIO):
            def __init__(self, target):
                target.parent.mkdir(parents=True, exist_ok=True)
                self.file = target.open("xb+")
                self.length = 0
                streams.append(self)

            def write(self, data):
                length = max(self.length, self.file.tell() + len(data))
                preparation.account(len(data), length)
                self.length = length
                return self.file.write(data)

            def read(self, size=None):
                return self.file.read(-1 if size is None else size)

            def seek(self, offset, whence=0):
                preparation.check()
                return self.file.seek(offset, whence)

            def size(self):
                return self.length

            def flush(self):
                if not self.file.closed:
                    self.file.flush()

            def close(self):
                self.file.close()

        class Factory(py7zr.WriterFactory):
            def create(self, filename):
                preparation.check()
                if filename not in targets:
                    raise ImportErrorDetail(_msg('text.0209'))
                return Output(targets[filename])

        try:
            with py7zr.SevenZipFile(path, "r") as archive:
                if archive.needs_password():
                    raise ImportErrorDetail(_msg('text.0207'))
                for info in archive.list():
                    target = self.member(root, info.filename, used)
                    if info.is_directory:
                        continue
                    if not info.is_file or info.is_symlink:
                        raise ImportErrorDetail(
                            _msg('text.0110')
                        )
                    self.count_file(info.uncompressed)
                    targets[info.filename] = target
                archive.extract(targets=list(targets), factory=Factory())
            return list(targets.values())
        finally:
            for stream in streams:
                stream.close()
