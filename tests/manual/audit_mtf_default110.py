"""Audit the 110% default, with known background and optional local pixel data.

PYTHONPATH=src .venv/bin/python tests/manual/audit_mtf_default110.py --output build/mtf-default110
Optional --pixels is an NPZ with pixels/spacing; --previous is the saved
three-point 90/100/110 comparison. No patient data is copied to the report.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from qt_dicom_viewer.core import bead_mtf


def background_cases():
    yy, xx = np.mgrid[-128:129, -128:129]
    psf = 2000*np.exp(-(xx*xx+yy*yy)/4.5)
    truth50 = math.sqrt(math.log(2))/(math.sqrt(2)*math.pi*.15)
    rows = []
    for curvature in (0., .001, .01, .05):
        for noise in (0., 2., 20.):
            pixels = (100+.8*xx-1.1*yy+curvature*(xx*xx+yy*yy)+psf
                      +np.random.default_rng(7).normal(0, noise, psf.shape))
            row = dict(curvature=curvature, noise_sigma=noise, center_background=100.,
                       true_mtf50_lp_mm=truth50)
            try:
                result = bead_mtf.compute_point_source_mtf(pixels, .1, .1, analysis_method='tukey_fft')
                row.update(background=result.background, background_bias=result.background-100,
                    mtf50_lp_mm=[result.x.mtf50, result.y.mtf50],
                    mtf50_error_pct=[100*(a.mtf50/truth50-1) for a in (result.x, result.y)],
                    background_inner_half_size=result.sampling.background_inner_half_size,
                    warnings=list(map(str, result.warnings)))
                if curvature == 0 and noise == 0:
                    assert abs(result.background-100) < 1e-9
                    assert max(abs(v) for v in row['mtf50_error_pct']) < .001
            except ValueError as exc:
                row['error'] = str(exc)
            rows.append(row)
    return rows


def real_points(path, previous):
    data = np.load(path)
    image, spacing = data['pixels'], data['spacing']
    old = json.loads(previous.read_text()) if previous else None
    digest = hashlib.sha256(image.tobytes()).hexdigest()
    if old:
        assert digest == old['source_sha256']
    points = []
    for i, (x, y) in enumerate(((600, 432), (636, 525), (600, 617))):
        r0, r1 = math.ceil(y-5/spacing[0]), math.floor(y+5/spacing[0])+1
        c0, c1 = math.ceil(x-5/spacing[1]), math.floor(x+5/spacing[1])+1
        result = bead_mtf.compute_mtf_with_context(image[r0:r1, c0:c1], *spacing,
                                                  context=(image, (r0, c0)))
        row = dict(requested_xy=[x, y], selected_xy=[c0+result.sampling.center[0], r0+result.sampling.center[1]],
                   background=result.background, noise=result.noise, integration_scale=result.integration_scale,
                   integration_half_size_px=result.sampling.half_size,
                   background_inner_half_size_px=result.sampling.background_inner_half_size,
                   background_outer_half_size_px=result.sampling.background_half_size,
                   warnings=list(map(str, result.warnings)), notes=list(map(str, result.notes)), axes={})
        if old:
            assert row['requested_xy'] == old['points'][i]['requested_xy']
            assert result.background == old['points'][i]['background']
            assert result.noise == old['points'][i]['noise']
        for name, axis in (('X', result.x), ('Y', result.y)):
            values = dict(mtf50=axis.mtf50*10, mtf10=axis.mtf10*10)
            if old:
                for key, value in values.items():
                    assert math.isclose(value, old['points'][i]['axes'][name]['110%'][key], rel_tol=1e-12)
            row['axes'][name] = values
        points.append(row)
    return dict(slice_number=26, spacing_mm=list(map(float, spacing)), roi_mm=10,
                unit='lp/cm', source_sha256=digest, equals_previous_110=bool(old), points=points)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pixels', type=Path)
    parser.add_argument('--previous', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = dict(integration_scale=bead_mtf.MTF_INTEGRATION_SCALE,
        code_sha256=hashlib.sha256(Path(bead_mtf.__file__).read_bytes()).hexdigest(),
        background_cases=background_cases())
    if args.pixels:
        report['real_points'] = real_points(args.pixels, args.previous)
    (args.output/'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
