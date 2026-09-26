"""Attachment validation, portable MIME export, and OS mail composition.

No SMTP credentials or silent send path. Windows always uses MAPI_DIALOG;
macOS uses the Compose Email sharing service on the GUI thread.
"""
import ctypes as C
from email.message import EmailMessage
from email.policy import SMTP
import mimetypes
from pathlib import Path
import stat

MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_ATTACHMENTS = 32


def validate_attachments(paths):
    files = []
    total = 0
    for value in paths:
        path = Path(value).resolve(strict=True)
        if path in files:
            continue
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('feedback.attachmentInvalid')
        total += info.st_size
        files.append(path)
        if total > MAX_ATTACHMENT_BYTES or len(files) > MAX_ATTACHMENTS:
            raise ValueError('feedback.attachmentLimit')
    return files


def email_bytes(recipient, subject, body, paths):
    paths = validate_attachments(paths)
    msg = EmailMessage(policy=SMTP)
    msg['To'] = recipient
    msg['Subject'] = subject.replace('\r', ' ').replace('\n', ' ')
    msg['X-Unsent'] = '1'
    msg.set_content(body)
    remaining = MAX_ATTACHMENT_BYTES
    for path in paths:
        with path.open('rb') as stream:
            data = stream.read(remaining + 1)
        remaining -= len(data)
        if remaining < 0:
            raise ValueError('feedback.attachmentLimit')
        mime = ('application/dicom' if path.suffix.lower() in ('.dcm', '.dicom') else
                mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        main, sub = mime.split('/', 1)
        name = path.name.replace('\r', '_').replace('\n', '_')
        msg.add_attachment(data, maintype=main, subtype=sub, filename=name)
    return msg.as_bytes()


class MacMailComposer:
    """Small ctypes bridge; reuse AppKit already loaded by Qt, no PyObjC bundle."""
    def __init__(self):
        self.objc = C.CDLL('/usr/lib/libobjc.A.dylib')
        self.appkit = C.CDLL('/System/Library/Frameworks/AppKit.framework/AppKit')
        self.objc.objc_getClass.argtypes = [C.c_char_p]
        self.objc.objc_getClass.restype = C.c_void_p
        self.objc.sel_registerName.argtypes = [C.c_char_p]
        self.objc.sel_registerName.restype = C.c_void_p
        self._retained = []

    def call(self, obj, selector, *args, result=C.c_void_p, types=None):
        types = types or [C.c_void_p] * len(args)
        fn = C.CFUNCTYPE(result, C.c_void_p, C.c_void_p, *types)(('objc_msgSend', self.objc))
        return fn(obj, self.objc.sel_registerName(selector.encode()), *args)

    def cls(self, name):
        return self.objc.objc_getClass(name.encode())

    def string(self, value):
        return self.call(self.cls('NSString'), 'stringWithUTF8String:', value.encode('utf-8'), types=[C.c_char_p])

    def array(self, items):
        array = self.call(self.cls('NSMutableArray'), 'array')
        for item in items:
            self.call(array, 'addObject:', item, result=None)
        return array

    def compose(self, recipient, subject, body, paths):
        name = C.c_void_p.in_dll(self.appkit, 'NSSharingServiceNameComposeEmail').value
        service = self.call(self.cls('NSSharingService'), 'sharingServiceNamed:', name)
        if not service:
            return False
        items = self.array([self.string(body)] + [self.call(self.cls('NSURL'), 'fileURLWithPath:', self.string(str(p))) for p in paths])
        if not self.call(service, 'canPerformWithItems:', items, result=C.c_bool):
            return False
        self.call(service, 'setRecipients:', self.array([self.string(recipient)]), result=None)
        self.call(service, 'setSubject:', self.string(subject), result=None)
        # The service is asynchronous; keep service and items alive for this app
        # session. No attachment bytes are loaded into Python or persisted here.
        for obj in (service, items):
            self.call(obj, 'retain')
            self._retained.append(obj)
        self.call(service, 'performWithItems:', items, result=None)
        return True

    def close(self):
        for obj in self._retained:
            self.call(obj, 'release', result=None)
        self._retained.clear()


class MapiRecipient(C.Structure):
    _fields_ = [('reserved', C.c_uint32), ('kind', C.c_uint32), ('name', C.c_wchar_p),
                ('address', C.c_wchar_p), ('entrySize', C.c_uint32), ('entry', C.c_void_p)]


class MapiFile(C.Structure):
    _fields_ = [('reserved', C.c_uint32), ('flags', C.c_uint32), ('position', C.c_uint32),
                ('path', C.c_wchar_p), ('name', C.c_wchar_p), ('type', C.c_void_p)]


class MapiMessage(C.Structure):
    _fields_ = [('reserved', C.c_uint32), ('subject', C.c_wchar_p), ('body', C.c_wchar_p),
                ('type', C.c_wchar_p), ('date', C.c_wchar_p), ('conversation', C.c_wchar_p),
                ('flags', C.c_uint32), ('originator', C.POINTER(MapiRecipient)),
                ('recipientCount', C.c_uint32), ('recipients', C.POINTER(MapiRecipient)),
                ('fileCount', C.c_uint32), ('files', C.POINTER(MapiFile))]


def windows_compose(recipient, subject, body, paths, *, library=None):
    library = library if library is not None else C.WinDLL('mapi32.dll')
    send = library.MAPISendMailW
    send.argtypes = [C.c_size_t, C.c_size_t, C.POINTER(MapiMessage), C.c_uint32, C.c_uint32]
    send.restype = C.c_uint32
    to = MapiRecipient(kind=1, name=recipient, address='SMTP:' + recipient)
    files = (MapiFile * len(paths))(*(MapiFile(position=0xffffffff, path=str(p), name=p.name) for p in paths))
    msg = MapiMessage(subject=subject, body=body, recipientCount=1, recipients=C.pointer(to), fileCount=len(files), files=files)
    # Force an editable compose dialog even though all fields are populated.
    # FORCE_UNICODE avoids corrupting non-ASCII filenames on older providers.
    code = send(0, 0, C.byref(msg), 0x8 | 0x1 | 0x40000, 0)
    return 'done' if code == 0 else 'cancelled' if code == 1 else 'unavailable'
