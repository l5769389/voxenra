"""Acceptance must fail closed when input frames or required exchange are missing."""
from dataclasses import replace
import json
import shutil

import numpy as np
import pytest

from spatial_audit.cases import Case, generate
from spatial_audit import real
from spatial_audit.compare import compare
from spatial_audit.verify import verify_case


@pytest.mark.parametrize('enhanced', [False, True])
def test_real_inventory_detects_one_missing_file_or_enhanced_frame(tmp_path, monkeypatch, enhanced):
    source = tmp_path / 'source'
    generate(source, Case('inventory', enhanced=enhanced))
    paths = sorted(source.glob('*.dcm'))
    config = dict(name='inventory', paths=[str(p) for p in paths])
    good = real.verify(config, tmp_path / 'good')
    assert good['status'] == 'pass'
    assert sum(g['frames'] for g in good['groups']) > 1
    original = real.DicomFolderScanner.scan_files
    def omit(self, *args, **kwargs):
        snapshot = list(original(self, *args, **kwargs))[-1]
        first, *others = snapshot.series
        yield replace(snapshot, series=(replace(first, instances=first.instances[:-1]), *others))
    monkeypatch.setattr(real.DicomFolderScanner, 'scan_files', omit)
    result = real.verify(config, tmp_path / 'bad')
    assert result['status'] == 'failure'
    assert len(result['missing_frames']) == 1


@pytest.mark.parametrize('empty', [False, True])
def test_real_audit_cannot_pass_without_recognized_frames(tmp_path, empty):
    path = tmp_path / 'not-dicom.txt'
    path.write_text('not an image')
    result = real.verify(dict(name='empty', paths=[] if empty else [str(path)]), tmp_path / 'out')
    assert result['status'] == 'failure'
    assert result['source_frames_expected'] == 0
    if not empty:
        assert len(result['rejected_files']) == 1


def exchange_case(tmp_path):
    case = tmp_path / 'case'
    generate(case, Case('exchange'))
    verify_case(case)
    group = case / 'group-0'
    with np.load(group / 'voxplane.npz') as source:
        np.savez(case / 'slicer-dicom-0.npz', pixels=source['source_pixels'], affine=source['affine'])
    result = dict(slicer='fixture', dicom=[dict(status='loaded', transform=None)],
                  exchange=[dict(group='group-0', status='pass')])
    shutil.copyfile(group / 'segmentation.seg.nrrd', group / 'slicer-return.seg.nrrd')
    return case, group, result


@pytest.mark.parametrize('defect', ['none', 'missing_return', 'error', 'missing_record', 'partial', 'corrupt_return'])
def test_required_exchange_controls_overall_acceptance(tmp_path, defect):
    case, group, slicer = exchange_case(tmp_path)
    if defect == 'missing_return':
        (group / 'slicer-return.seg.nrrd').unlink()
    elif defect == 'error':
        slicer['exchange_error'] = 'segmentation export failed'
    elif defect == 'missing_record':
        slicer['exchange'] = []
    elif defect == 'corrupt_return':
        (group / 'slicer-return.seg.nrrd').write_text('invalid NRRD')
    elif defect == 'partial':
        other = case / 'group-1'
        other.mkdir()
        shutil.copyfile(group / 'segmentation.seg.nrrd', other / 'segmentation.seg.nrrd')
    (case / 'slicer-result.json').write_text(json.dumps(slicer))
    result, = compare(tmp_path)
    assert result['status'] == ('pass' if defect == 'none' else 'blocked')
    assert result['image_status'] == 'pass'
    assert result['exchange_status'] == ('pass' if defect == 'none' else 'blocked')
    assert result['status'] == ('pass' if defect == 'none' else 'blocked')


def test_summary_counts_only_verified_roundtrips_and_preserves_phase_status(tmp_path):
    from spatial_audit.report import report
    case = tmp_path / 'real' / 'case'
    case.mkdir(parents=True)
    (case / 'voxplane-result.json').write_text(json.dumps(dict(status='failure', groups=[])))
    (case.parent / 'comparison.json').write_text(json.dumps([dict(case='case', status='blocked',
        image_status='pass', exchange_status='blocked', exchange=[
            dict(group='group-0', status='pass'), dict(group='group-1', status='blocked')])]))
    acceptance = tmp_path / 'acceptance'
    acceptance.mkdir()
    (acceptance / 'results.json').write_text(json.dumps(dict(totals={})))
    summary = report(tmp_path)
    item, = summary['cases']
    assert item['product_status'] == 'failure'
    assert item['slicer_status'] == 'blocked'
    assert item['slicer_image_status'] == 'pass'
    assert item['slicer_exchange_status'] == 'blocked'
    assert item['slicer_roundtrip_groups'] == 1


def test_absent_slicer_run_marks_required_exchange_unverified(tmp_path):
    exchange_case(tmp_path)
    result, = compare(tmp_path)
    assert result['status'] == 'blocked'
    assert result['image_status'] == 'blocked'
    assert result['exchange_status'] == 'blocked'
