"""Read a complete metadata tree without decoding or displaying pixel payloads."""
from voxplane.i18n import message as _msg

from pathlib import Path

import pydicom
from pydicom.datadict import dictionary_description, dictionary_VR, keyword_for_tag
from pydicom.dataelem import RawDataElement
from pydicom.dataset import Dataset
from pydicom.multival import MultiValue

from voxplane.model.dicom_tags import TagNode

_BINARY_VRS = {"OB", "OD", "OF", "OL", "OV", "OW", "UN", "OB or OW", "US or OW", "US or SS or OW"}
_PIXEL_TAGS = {0x7FE00008, 0x7FE00009, 0x7FE00010}


def _text(value) -> str:
    if value is None or isinstance(value, str) and not value:
        return _msg('text.0132')
    if isinstance(value, (MultiValue, list, tuple)):
        return "\\".join(str(item) for item in value) or _msg('text.0132')
    return str(value)


def _read_dataset(dataset: Dataset, prefix: str) -> tuple[TagNode, ...]:
    nodes = []
    for tag in sorted(dataset.keys()):
        node_id = f"{prefix}/{int(tag):08X}"
        number = f"({tag.group:04X},{tag.element:04X})"
        keyword = keyword_for_tag(tag)
        try:
            name = dictionary_description(tag)
        except KeyError:
            name = "Private Tag" if tag.is_private else "Unknown Tag"
        vr = "UN"
        children = ()
        try:
            # Do not iterate DataElements: that would materialize deferred binary values.
            raw = dataset.get_item(tag, keep_deferred=True)
            vr = raw.VR
            if vr is None:
                try:
                    vr = dictionary_VR(tag)
                except KeyError:
                    vr = "UN"
            if vr in _BINARY_VRS or int(tag) in _PIXEL_TAGS:
                if isinstance(raw, RawDataElement):
                    length = raw.length
                else:
                    length = len(raw.value) if raw.value is not None else 0
                size = _msg('text.0133') if length == 0xFFFFFFFF else _msg('text.0134', value1=f'{length:,}')
                label = _msg('text.0135') if int(tag) in _PIXEL_TAGS else _msg('text.0136')
                value = _msg('tags.binaryValue', label=label, size=size)
            else:
                element = dataset[tag]
                name = element.name
                vr = element.VR
                if vr == "SQ":
                    items = element.value or []
                    children = tuple(
                        TagNode(
                            f"{node_id}/item-{index}", "", f"Item {index + 1}", "", "", "",
                            _read_dataset(item, f"{node_id}/item-{index}"), is_item=True,
                        )
                        for index, item in enumerate(items)
                    )
                    value = _msg('text.0137', value1=len(items))
                else:
                    value = _text(element.value)
        except Exception as error:
            # A malformed element must not hide the rest of an otherwise readable file.
            value = _msg('text.0138', value1=error)
        nodes.append(TagNode(node_id, number, name, keyword, str(vr), value, children))
    return tuple(nodes)


def read_dicom_tags(path: Path) -> tuple[TagNode, ...]:
    dataset = pydicom.dcmread(path, defer_size=1024)
    # Separate IDs preserve provenance; both sections appear in ascending tag order.
    return _read_dataset(dataset.file_meta, "meta") + _read_dataset(dataset, "dataset")
