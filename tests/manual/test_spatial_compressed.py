"""Exact lossless decoded-pixel comparison with unchanged public references."""
import hashlib
import json
import os
from pathlib import Path
import numpy as np
import pydicom
import pytest
from qt_dicom_viewer.core.dicom_loader import DicomLoader
from qt_dicom_viewer.core.dicom_scanner import DicomFolderScanner
from qt_dicom_viewer.core.pixel_codecs import decode_pixels

PAIRS=[
 ('01_RLE/MR_single/MR_small_RLE.dcm','_references/MR_single/MR_small.dcm'),
 ('02_JPEG_LS_lossless/MR_single/MR_small_jpeg_ls_lossless.dcm','_references/MR_single/MR_small.dcm'),
 ('03_JPEG2000_lossless/MR_single/MR_small_jp2klossless.dcm','_references/MR_single/MR_small.dcm'),
 ('03_JPEG2000_lossless/MR_large/MR2_J2KR.dcm','_references/MR_large_lossless/MR2_UNCR.dcm'),
 ('03_JPEG2000_lossless/CT_693/693_J2KR.dcm','_references/CT_693/693_UNCR.dcm'),
]

@pytest.mark.parametrize('encoded,reference',PAIRS,ids=[Path(a).stem for a,b in PAIRS])
def test_lossless_original_scan_decode_matches_reference(tmp_path,encoded,reference):
    path=os.environ.get('VOXENRA_COMPRESSED_SAMPLE_DIR')
    if not path:pytest.skip('Set VOXENRA_COMPRESSED_SAMPLE_DIR to fixed public fixture directory')
    root=Path(path);manifest={x['file']:x for x in json.loads((root/'manifest.json').read_text())}
    for name in (encoded,reference):
        assert hashlib.sha256((root/name).read_bytes()).hexdigest()==manifest[name]['sha256']
    original=pydicom.dcmread(root/reference)
    compressed=pydicom.dcmread(root/encoded)
    np.testing.assert_array_equal(decode_pixels(compressed),original.pixel_array)
    scan=list(DicomFolderScanner().scan_files([root/encoded],folder=root))[-1]
    assert len(scan.series)==1 and len(scan.series[0].instances)==1
    meta,values=DicomLoader().read_frame(scan.series[0].instances[0].path)
    expected=original.pixel_array.astype(float)*float(getattr(original,'RescaleSlope',1))+float(getattr(original,'RescaleIntercept',0))
    if 'PixelPaddingValue' in original:expected[original.pixel_array==original.PixelPaddingValue]=np.nan
    np.testing.assert_allclose(values,expected,rtol=1e-6,atol=1e-4,equal_nan=True)
    output=os.environ.get('VOXENRA_SPATIAL_COMPRESSED_OUTPUT')
    if output:
        dest=Path(output);dest.mkdir(parents=True,exist_ok=True)
        (dest/(Path(encoded).stem+'.json')).write_text(json.dumps(dict(status='pass',source=manifest[encoded],
            reference=manifest[reference],shape=list(values.shape),stored_pixels_equal=True),indent=2))
