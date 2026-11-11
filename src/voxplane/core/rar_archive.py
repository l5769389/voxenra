"""Stream RAR4/5 through bundled UnRAR without letting it write source paths.

Use the pinned wrapper's C API: its high-level open() buffers entire files,
while iterate_headers() discards header read errors. TEST mode provides chunks
and validates checksums, including consecutive members of solid archives.
"""
from voxplane.i18n import message as _msg

import stat

from unrar.cffi import unrarlib  # Registers the CFFI callback trampoline.
from unrar.cffi._unrarlib import ffi, lib

from .local_import import ImportErrorDetail

# UnRAR 7.x dll.hpp constants not exposed by the wrapper.
_END_ARCHIVE = 10
_VOLUME = 0x0001
_ENCRYPTED_HEADERS = 0x0080
_SPLIT_MEMBER = 0x03
_ENCRYPTED_MEMBER = 0x04


def extract_rar(path, preparation, root, used):
    output = None
    written = 0
    expected_size = 0
    callback_error = None
    extracted = []

    def callback(message, pointer, size):
        nonlocal written, callback_error
        if callback_error is not None:
            return -1
        try:
            preparation.check()
            if message in (lib.UCM_NEEDPASSWORD, lib.UCM_NEEDPASSWORDW):
                raise ImportErrorDetail(_msg('text.0103'))
            if message in (lib.UCM_CHANGEVOLUME, lib.UCM_CHANGEVOLUMEW):
                raise ImportErrorDetail(_msg('text.0104'))
            if message == lib.UCM_LARGEDICT:
                raise ImportErrorDetail(_msg('text.0105'))
            if message == lib.UCM_PROCESSDATA and output is not None:
                written += size
                if size < 0 or written > expected_size:
                    raise ImportErrorDetail(_msg('text.0106'))
                preparation.account(size, written)
                output.write(ffi.buffer(ffi.cast("char *", pointer), size))
            return 1
        except BaseException as error:
            # Exceptions must not escape a C callback: abort, then raise in Python.
            callback_error = error
            return -1

    def checked(code):
        if callback_error is not None:
            raise callback_error
        preparation.check()
        if code in (lib.C_ERAR_MISSING_PASSWORD, lib.C_ERAR_BAD_PASSWORD):
            raise ImportErrorDetail(_msg('text.0103'))
        if code != lib.C_ERAR_SUCCESS:
            raise ImportErrorDetail(_msg('text.0107'))

    context = ffi.new_handle(callback)
    archive_data = unrarlib.RAROpenArchiveDataEx(path, lib.C_RAR_OM_EXTRACT)
    # The wrapper uses void* for callback context; the DLL uses pointer-sized LPARAM.
    archive_data.value.Callback = ffi.cast(
        ffi.typeof(archive_data.value.Callback), lib.PyUNRARCALLBACKStub
    )
    archive_data.value.UserData = ffi.cast(
        dict(ffi.typeof(archive_data.value[0]).fields)["UserData"].type, context
    )
    handle = lib.RAROpenArchiveEx(archive_data.value)
    try:
        checked(archive_data.value.OpenResult)
        if handle == ffi.NULL:
            raise ImportErrorDetail(_msg('text.0108'))
        if archive_data.value.Flags & _VOLUME:
            raise ImportErrorDetail(_msg('text.0104'))
        if archive_data.value.Flags & _ENCRYPTED_HEADERS:
            raise ImportErrorDetail(_msg('text.0103'))
        while True:
            preparation.check()
            header = ffi.new("struct RARHeaderDataEx *")
            code = lib.RARReadHeaderEx(handle, header)
            if code == _END_ARCHIVE and callback_error is None:
                break
            checked(code)
            name = ffi.string(header.FileNameW)
            if len(name) >= 1023:
                raise ImportErrorDetail(_msg('text.0109'))
            directory = bool(header.Flags & lib.C_RHDF_DIRECTORY)
            if header.Flags & _SPLIT_MEMBER:
                raise ImportErrorDetail(_msg('text.0104'))
            if header.Flags & _ENCRYPTED_MEMBER:
                raise ImportErrorDetail(_msg('text.0103'))
            mode = stat.S_IFMT(header.FileAttr) if header.HostOS == 3 else 0
            if (
                header.RedirType
                or mode not in (0, stat.S_IFREG, stat.S_IFDIR)
                or (header.HostOS != 3 and header.FileAttr & 0x400)
            ):
                raise ImportErrorDetail(_msg('text.0110'))
            if directory and name in (".", "./", ".\\"):
                checked(lib.RARProcessFileW(handle, lib.C_RAR_SKIP, ffi.NULL, ffi.NULL))
                continue
            target = preparation.member(root, name, used)
            if directory:
                checked(lib.RARProcessFileW(handle, lib.C_RAR_SKIP, ffi.NULL, ffi.NULL))
                continue
            expected_size = header.UnpSize + (header.UnpSizeHigh << 32)
            preparation.count_file(expected_size)
            if (
                header.DictSize * 1024
                > preparation.store.limits.max_rar_dictionary_bytes
            ):
                raise ImportErrorDetail(_msg('text.0105'))
            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with target.open("xb") as stream:
                output = stream
                try:
                    checked(
                        lib.RARProcessFileW(handle, lib.C_RAR_TEST, ffi.NULL, ffi.NULL)
                    )
                finally:
                    output = None
            if written != expected_size:
                raise ImportErrorDetail(_msg('text.0111'))
            extracted.append(target)
        return extracted
    finally:
        if handle != ffi.NULL:
            lib.RARSetCallbackPtr(handle, ffi.NULL, ffi.NULL)
            lib.RARCloseArchive(handle)
