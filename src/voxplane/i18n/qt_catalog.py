"""Build an ID-based Qt catalog in memory from validated JSON messages.

Qt performs lookup natively, including calls from the QML loader thread. A
Python translate() override can deadlock that thread against a GUI load call.
No lrelease executable or user-visible binary language pack is required.

Wire format: Qt Linguist's qm.cpp (Hashes and Messages sections, full records).
https://github.com/qt/qttools/blob/6.11/src/linguist/shared/qm.cpp
"""
from struct import pack

_MAGIC = bytes.fromhex('3cb86418caef9c95cd211cbf60a1bddd')


def _hash(source):
    value = 0
    for byte in source:
        value = ((value << 4) + byte) & 0xffffffff
        high = value & 0xf0000000
        value = (value ^ (high >> 24)) & ~high
    return value or 1


def _field(tag, data):
    return bytes((tag,)) + pack('>I', len(data)) + data


def encode_catalog(messages):
    records = bytearray()
    offsets = []
    for key, value in sorted(messages.items()):
        source = key.encode('utf-8')
        offsets.append((_hash(source), len(records)))
        records.extend(_field(3, value.encode('utf-16-be')))
        records.extend(_field(8, b''))  # Empty disambiguation.
        records.extend(_field(6, source))
        records.extend(_field(7, b''))  # qsTrId uses an empty context.
        records.append(1)
    hashes = b''.join(pack('>II', *entry) for entry in sorted(offsets))
    return _MAGIC + _field(0x42, hashes) + _field(0x69, records)
