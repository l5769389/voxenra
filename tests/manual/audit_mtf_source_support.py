"""Audit source-scaled support against known two-Gaussian PSFs.

Run with PYTHONPATH=src .venv/bin/python tests/manual/audit_mtf_source_support.py.
This is a numerical bias experiment, not a pass/fail accuracy certification.
No clinical image or optional SciPy dependency is required.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from voxplane.core.bead_mtf import (
    _source_support, _source_window, compute_point_source_mtf, MTF_INTEGRATION_SCALE,
)
from voxplane.core.mtf_quality import metric_quality


def crossings(spectrum, nyquist):
    """First downward crossing, independent explicit sum and bisection."""
    frequencies = np.linspace(0, nyquist, 513)
    responses = np.array([spectrum(f) for f in frequencies])
    values = []
    for level in (.5, .1):
        indices = np.flatnonzero((responses[:-1] > level) & (responses[1:] <= level))
        if not len(indices):
            values.append(None)
            continue
        lo, hi = frequencies[indices[0]:indices[0]+2]
        for _ in range(60):
            mid = (lo+hi)/2
            if spectrum(mid) > level:
                lo = mid
            else:
                hi = mid
        values.append(float((lo+hi)*5))  # lp/mm -> lp/cm
    return values


def explicit_spectrum(lsf, spacing):
    positions = np.arange(len(lsf))*spacing
    dc = np.sum(lsf)
    assert dc > 0
    return lambda frequency: float(abs(np.exp(-2j*np.pi*frequency*positions) @ lsf)/dc)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('build/mtf-roi-audit-20261109'))
    parser.add_argument('--noise-seeds', type=int, default=0,
                        help='Also audit noise levels 0/1/2/5/10/20 with this many fixed seeds.')
    args = parser.parse_args()
    if not 0 <= args.noise_seeds <= 100:
        parser.error('--noise-seeds must be between 0 and 100')
    args.output.mkdir(parents=True, exist_ok=True)
    yy, xx = np.mgrid[-128:129, -128:129]
    sigma, tail_sigma, spacing = 1.5, 8., .1
    rows, illustration = [], None
    for amplitude in (0., .002, .005, .01, .02, .04):
        psf = (np.exp(-(xx*xx+yy*yy)/(2*sigma*sigma))
               + amplitude*np.exp(-(xx*xx+yy*yy)/(2*tail_sigma*tail_sigma)))
        pixels = 100. + 2000.*psf

        def analytical(frequency):
            return ((sigma*sigma*np.exp(-2*np.pi*np.pi*(sigma*spacing*frequency)**2)
                     + amplitude*tail_sigma*tail_sigma
                     * np.exp(-2*np.pi*np.pi*(tail_sigma*spacing*frequency)**2))
                    / (sigma*sigma+amplitude*tail_sigma*tail_sigma))

        full_spectrum = explicit_spectrum(psf.sum(0), spacing)
        true_values = crossings(analytical, .5/spacing)
        discrete_values = crossings(full_spectrum, .5/spacing)
        # Validate the analytical continuous reference against the complete
        # discretely sampled PSF, without production FFT/interpolation code.
        assert np.allclose(discrete_values, true_values, rtol=1e-8, atol=1e-8)
        result = compute_point_source_mtf(pixels, spacing, spacing, analysis_method='tukey_fft', check_stability=True)
        estimated_psf, background, noise, widths, cx, cy = _source_support(pixels, spacing, spacing)
        window = _source_window(cx, cy, widths, MTF_INTEGRATION_SCALE)
        window_only_spectrum = explicit_spectrum((psf*window).sum(0), spacing)
        processed_spectrum = explicit_spectrum((estimated_psf*window).sum(0), spacing)
        window_only_values = crossings(window_only_spectrum, .5/spacing)
        processed_values = crossings(processed_spectrum, .5/spacing)
        measured = [result.x.mtf50*10, result.x.mtf10*10]
        # Verify the frequency samples themselves independently. Thresholds use
        # linear interpolation in production; require the exact crossing to lie
        # within one sampled frequency step, and report the observed error.
        curve_error = max(abs(processed_spectrum(f)-value)
                          for f, value in zip(result.x.frequency, result.x.mtf))
        assert curve_error < 1e-12
        assert np.max(np.abs(np.array(measured)-processed_values)) < 10*(
            result.x.frequency[1]-result.x.frequency[0])
        row = dict(tail_peak_fraction=amplitude,
                   tail_integral_fraction=amplitude*tail_sigma**2/(sigma**2+amplitude*tail_sigma**2),
                   analytic_lp_cm=true_values, complete_discrete_lp_cm=discrete_values,
                   known_background_current_window_lp_cm=window_only_values,
                   estimated_background_current_window_lp_cm=processed_values,
                   production_lp_cm=measured,
                   max_frequency_sample_error=curve_error,
                   interpolation_relative_error_pct=[100*(v/t-1) for v, t in zip(measured, processed_values)],
                   relative_error_pct=[100*(v/t-1) for v, t in zip(measured, true_values)],
                   estimated_background=background, true_background=100., noise=noise,
                   support_unit_pixels=widths.tolist(), support_half_extent_mm=(widths*4*spacing).tolist(),
                   quality=[metric_quality(result.x, key, result.sensitivity_threshold, 'X')
                            for key in ('mtf50', 'mtf10')],
                   warnings=list(result.warnings),
                   comparisons=[dict(variant=s.variant, lp_cm=[s.mtf50*10, s.mtf10*10])
                                for s in result.x.sensitivity])
        rows.append(row)
        if amplitude == .02:
            frequencies = np.linspace(0, .5/spacing, 1001)
            illustration = dict(position=xx[128]*spacing, profile=psf[128],
                                background=(background-100)/2000,
                                extent=widths[0]*4*spacing,
                                frequencies=frequencies*10,
                                true=np.array([analytical(f) for f in frequencies]),
                                window=np.array([window_only_spectrum(f) for f in frequencies]),
                                processed=np.array([processed_spectrum(f) for f in frequencies]))
    output = dict(description='Noiseless, positive two-Gaussian PSF; X and Y are symmetric.',
                  columns=['MTF50', 'MTF10'], spacing_mm=spacing, shape=[257, 257],
                  narrow_sigma_pixels=sigma, broad_sigma_pixels=tail_sigma, rows=rows)
    (args.output/'known-truth.json').write_text(json.dumps(output, ensure_ascii=False, indent=2))
    for row in rows:
        print(f"tail peak {row['tail_peak_fraction']:.3f}: true {row['analytic_lp_cm']}, "
              f"current {row['production_lp_cm']}, error % {row['relative_error_pct']}")
    print('Independent discrete Fourier reference and production-spectrum checks passed.')

    if args.noise_seeds:
        pixels = 100+2000*(np.exp(-(xx*xx+yy*yy)/(2*sigma*sigma))
                           +.02*np.exp(-(xx*xx+yy*yy)/(2*tail_sigma*tail_sigma)))
        truth = next(row['analytic_lp_cm'] for row in rows if row['tail_peak_fraction'] == .02)
        noise_rows = []
        for noise in (0., 1., 2., 5., 10., 20.):
            errors = []
            for seed in range(args.noise_seeds):
                image = pixels+np.random.default_rng(seed).normal(0, noise, pixels.shape)
                result = compute_point_source_mtf(image, spacing, spacing, analysis_method='tukey_fft', check_stability=True)
                errors.append(100*(np.array([result.x.mtf50, result.x.mtf10])*10/truth-1))
            noise_rows.append(dict(noise=noise, seeds=args.noise_seeds,
                median_error_pct=np.median(errors, axis=0).tolist(),
                p95_abs_error_pct=np.percentile(np.abs(errors), 95, axis=0).tolist()))
        (args.output/'noise.json').write_text(json.dumps(noise_rows, indent=2))

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, (profile_ax, mtf_ax) = plt.subplots(1, 2, figsize=(11, 4.2), layout='constrained')
    d = illustration
    profile_ax.semilogy(d['position'], d['profile'], color='#007d9c', label='True source profile')
    profile_ax.axvspan(-d['extent'], d['extent'], color='#007d9c', alpha=.1,
                       label='Nonzero integration support')
    profile_ax.axhline(d['background'], color='#c45d23', ls='--', label='Estimated excess background')
    extent = max(3., d['extent']*1.2)
    profile_ax.set(xlim=(-extent, extent), ylim=(1e-5, 2), xlabel='Distance from peak (mm)',
                   ylabel='Relative intensity (log)', title='Narrow peak + 2% broad tail')
    profile_ax.legend(fontsize=8)
    for values, label, color, style in [
        (d['true'], 'Complete known PSF', '#222222', '-'),
        (d['window'], 'True background + current window', '#007d9c', '--'),
        (d['processed'], 'Current background + current window', '#c45d23', '-'),
    ]:
        mtf_ax.plot(d['frequencies'], values, label=label, color=color, ls=style)
    for level in (.5, .1):
        mtf_ax.axhline(level, color='#999999', lw=.6)
    mtf_ax.set(xlim=(0, 30), ylim=(0, 1.02), xlabel='Spatial frequency (lp/cm)', ylabel='MTF',
               title='Measured MTF versus complete known PSF')
    mtf_ax.legend(fontsize=8)
    fig.savefig(args.output/'known-truth.png', dpi=160)
    plt.close(fig)


if __name__ == '__main__':
    main()
