"""Image metadata de-identification; never claims to clean burned-in pixels.

The Basic Profile table is applied recursively, with conservative removal of
private/unknown attributes, free text, overlays, original attributes and icons.
Ambiguous actions use a dummy (D), empty value (Z), or UID mapping (U) to retain
required attributes where possible. This is not an IOD conformance validator.
"""
from voxplane.i18n import message as _msg

from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import UID, PYDICOM_IMPLEMENTATION_UID, generate_uid

from voxplane.core.confidentiality_profile import BASIC_PROFILE_ACTIONS


def check_pixel_identity(dataset):
    if str(getattr(dataset, "BurnedInAnnotation", "")).upper() == "YES":
        raise ValueError(_msg('text.0155'))
    if str(getattr(dataset, "RecognizableVisualFeatures", "")).upper() == "YES":
        raise ValueError(_msg('text.0156'))
    for group in range(0x6000, 0x6020, 2):
        if (group, 0x0100) in dataset and int(dataset[group, 0x0100].value) != 1:
            raise ValueError(_msg('text.0157'))
    sop_class = UID(str(getattr(dataset, "SOPClassUID", "")))
    if "Image Storage" not in sop_class.name:
        raise ValueError(_msg('text.0158'))


_REMOVE = {
    "OriginalAttributesSequence", "EncryptedAttributesSequence", "DigitalSignaturesSequence",
    "MACParametersSequence", "IconImageSequence", "DataSetTrailingPadding",
    "ReferencedPatientPhotoSequence", "DeidentificationMethodCodeSequence",
}
_FREE_TEXT_VRS = {"LO", "LT", "SH", "ST", "UC", "UR", "UT"}
_TECHNICAL_TEXT = {"RescaleType", "CodingSchemeDesignator", "CodingSchemeVersion", "CodeValue",
                   "LongCodeValue", "URNCodeValue", "LUTLabel"}


class Anonymizer:
    """One mapping per export preserves all in-series instance references."""

    def __init__(self):
        self._uids = {}
        self.patient_id = "ANON-" + generate_uid().split(".")[-1][-16:]

    def uid(self, value):
        value = str(value)
        if not value:
            return ""
        if value not in self._uids:
            self._uids[value] = generate_uid()
        return self._uids[value]

    def _dummy(self, element):
        vr = element.VR
        if vr == "SQ":
            # Keep item structure and apply the same rules to every nested tag.
            for item in element.value:
                self._clean(item)
            return element.value or [Dataset()]
        if vr == "UI":
            return self.uid(element.value) or generate_uid()
        if vr == "DA":
            return "19000101"
        if vr == "DT":
            return "19000101000000"
        if vr == "TM":
            return "000000"
        if vr == "AS":
            return "000Y"
        if vr in {"DS", "IS"}:
            return "0"
        if vr in {"US", "SS", "UL", "SL", "UV", "SV", "FL", "FD", "AT"}:
            return 0
        if vr in {"OB", "OW", "OF", "OD", "OL", "OV", "UN"}:
            return b"\0\0"
        return "ANONYMIZED"

    def _clean(self, dataset):
        for element in list(dataset):
            tag, keyword = element.tag, element.keyword
            if (tag.is_private or not keyword or tag.element == 0x0000
                    or 0x5000 <= tag.group <= 0x50FF or 0x6000 <= tag.group <= 0x60FF
                    or keyword in _REMOVE):
                del dataset[tag]
                continue
            action = BASIC_PROFILE_ACTIONS.get(int(tag), "")
            if action == "X":
                del dataset[tag]
            elif "U" in action:
                if element.VR == "SQ":
                    for item in element.value:
                        self._clean(item)
                elif element.VR == "UI":
                    element.value = ([self.uid(value) for value in element.value]
                                     if element.VM > 1 else self.uid(element.value))
            elif "D" in action:
                element.value = self._dummy(element)
            elif "Z" in action:
                element.value = [] if element.VR == "SQ" else ""
            elif element.VR == "SQ":
                for item in element.value:
                    self._clean(item)
            elif element.VR == "UI":
                # Preserve semantic UIDs; remap every identity/reference UID,
                # including tags newer than the bundled profile table.
                if not (keyword.endswith("SOPClassUID") or keyword in {"TransferSyntaxUID", "CodingSchemeUID"}):
                    element.value = ([self.uid(value) for value in element.value]
                                     if element.VM > 1 else self.uid(element.value))
            elif element.VR in {"PN", "DA", "DT", "TM", "AS", "AE"}:
                element.value = ""
            elif element.VR in _FREE_TEXT_VRS and keyword not in _TECHNICAL_TEXT:
                element.value = "ANONYMIZED"

    def apply(self, dataset):
        check_pixel_identity(dataset)
        transfer_syntax = dataset.file_meta.TransferSyntaxUID
        self._clean(dataset)
        dataset.PatientName = "ANONYMOUS"
        dataset.PatientID = self.patient_id
        dataset.PatientIdentityRemoved = "YES"
        dataset.DeidentificationMethod = "VoxPlane metadata de-identification; pixels unchanged"
        dataset.preamble = b"\0" * 128
        dataset.file_meta = FileMetaDataset()
        dataset.file_meta.TransferSyntaxUID = transfer_syntax
        dataset.file_meta.MediaStorageSOPClassUID = dataset.SOPClassUID
        dataset.file_meta.MediaStorageSOPInstanceUID = dataset.SOPInstanceUID
        dataset.file_meta.ImplementationClassUID = PYDICOM_IMPLEMENTATION_UID
        dataset.file_meta.ImplementationVersionName = "QTDICOM_EXPORT"
        return dataset
