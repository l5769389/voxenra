"""Audit both header-free phantom patches; writes metrics, sweeps and a plot.

Run: .venv/bin/python tests/manual/validate_mtf_phantoms.py --output build/mtf-final
The explicit Fourier sum is an independent numerical check, not a third-party
MTF implementation or a scanner accuracy certification.
"""
import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
from qt_dicom_viewer.core.bead_mtf import compute_point_source_mtf, _windowed_point_source_mtf
from qt_dicom_viewer.core.mtf_quality import metric_quality


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('build/mtf-final'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    fixture = Path(__file__).resolve().parents[1]/'fixtures/mtf/point_sources.npz'
    result = {'spacing_mm': .1953125, 'frequency_unit': 'lp/cm', 'samples': {}}
    plots = []
    with np.load(fixture) as inputs:
        for name in inputs.files:
            pixels = inputs[name]
            def crop(size, dx=0, dy=0):
                r = size//2
                return pixels[48+dy-r:49+dy+r, 48+dx-r:49+dx+r]
            baseline = compute_point_source_mtf(crop(65), .1953125, .1953125, analysis_method='tukey_fft')
            raw = _windowed_point_source_mtf(crop(65), .1953125, .1953125, check_stability=False)
            rows = []
            start = time.perf_counter()
            for size in (55, 57, 59, 61, 63, 65):
                for dx in range(-2, 3):
                    for dy in range(-2, 3):
                        calculated = compute_point_source_mtf(crop(size, dx, dy), .1953125, .1953125,
                                                              analysis_method='tukey_fft')
                        rows.append({'size': size, 'dx': dx, 'dy': dy,
                            'values': [None if v is None else v*10 for a in (calculated.x, calculated.y)
                                       for v in (a.mtf50, a.mtf10)],
                            'quality': [metric_quality(axis, metric, calculated.sensitivity_threshold, direction)
                                        for direction, axis in (('X', calculated.x), ('Y', calculated.y))
                                        for metric in ('mtf50', 'mtf10')]})
            milliseconds = (time.perf_counter()-start)*1000/len(rows)
            values = np.array([r['values'] for r in rows], dtype=float)
            valid = np.all(np.isfinite(values), axis=0)
            spread = [None]*4
            for col in np.flatnonzero(valid):
                spread[col] = float(100*np.ptp(values[:, col])/np.median(values[:, col]))
            # Explicit complex exponential sum + bisection, no FFT/interp oracle.
            checks = []
            for axis in (raw.x, raw.y):
                lsf = np.array(axis.lsf)
                position = np.arange(len(lsf))*.1953125
                def spectrum(freq):
                    return abs(np.exp(-2j*np.pi*np.asarray(freq)[..., None]*position) @ lsf)/lsf.sum()
                f = np.array(axis.frequency); curve = spectrum(f)
                error = float(np.max(abs(curve-axis.mtf)))
                assert error < 1e-12
                thresholds = []
                for level, reported in ((.5, axis.mtf50), (.1, axis.mtf10)):
                    down = np.flatnonzero((curve[:-1]>level)&(curve[1:]<=level))
                    if len(down):
                        lo, hi = f[down[0]], f[down[0]+1]
                        for _ in range(50):
                            mid = (lo+hi)/2
                            if spectrum(mid)>level: lo=mid
                            else: hi=mid
                        exact = (lo+hi)/2
                        relative_error = float(abs(reported/exact-1))
                        assert relative_error < 1e-4
                        thresholds.append({'level': level, 'explicit_sum_lp_cm': float(exact*10),
                                           'relative_interpolation_error': relative_error})
                checks.append({'max_curve_error': error, 'thresholds': thresholds})
            small_rois = []
            for size in (17, 25, 33, 41, 49):
                try:
                    r = compute_point_source_mtf(crop(size), .1953125, .1953125, analysis_method='tukey_fft')
                    small_rois.append({'size': size, 'accepted': True})
                except ValueError as exc:
                    small_rois.append({'size': size, 'accepted': False, 'error': str(exc)})
            result['samples'][name] = {'result': asdict(baseline), 'raw_thresholds_lp_cm':
                [[a.mtf50*10 if a.mtf50 is not None else None, a.mtf10*10 if a.mtf10 is not None else None]
                 for a in (raw.x, raw.y)],
                'sweep_count': len(rows), 'spread_percent_X50_X10_Y50_Y10': spread,
                'average_compute_ms': milliseconds, 'fourier_checks': checks,
                'small_roi_checks': small_rois, 'rows': rows}
            plots.append((name, baseline))
    (args.output/'final-results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), layout='constrained')
    for ax, (name, calculated) in zip(axes, plots):
        for label, axis, color in [('X', calculated.x, '#007d9c'), ('Y', calculated.y, '#c07b12')]:
            ax.plot(np.array(axis.frequency)*10, axis.mtf, label=label, color=color, lw=1.8)
            for value, level in [(axis.mtf50, .5), (axis.mtf10, .1)]:
                if value is not None: ax.scatter(value*10, level, c=color, s=22, zorder=4)
        ax.axhline(.5, color='gray', lw=.6); ax.axhline(.1, color='gray', lw=.6)
        ax.set(xlabel='Spatial frequency (lp/cm)', ylabel='MTF', xlim=(0, 25.6), ylim=(0, None),
               title='Helical / slice 11' if name.startswith('helical') else 'Head STD-QA / slice 151')
        flagged = [f'{direction} {metric.upper()}'
                   for direction, axis in (('X', calculated.x), ('Y', calculated.y))
                   for metric in ('mtf50', 'mtf10')
                   if metric_quality(axis, metric, calculated.sensitivity_threshold, direction)['message']]
        if flagged:
            ax.text(.98, .94, ', '.join(flagged) + ': review processing sensitivity', ha='right', va='top',
                    transform=ax.transAxes, fontsize=9, color='#986010')
        ax.legend(loc='upper left'); ax.grid(alpha=.15)
    fig.suptitle('Source-scaled support; DC normalization; independently measured thresholds')
    fig.savefig(args.output/'final-curves.png', dpi=160)
    for name, sample in result['samples'].items():
        print(name, json.dumps({k:v for k,v in sample.items() if k not in ('rows', 'result')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
