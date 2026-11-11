"""Verify actual decoded pixels in a frozen application without starting Qt."""
import hashlib
import json
from pathlib import Path

import numpy as np

from voxplane.core.pixel_codecs import PLUGINS, decode_pixels, get_decoder


def pixel_digest(pixels):
    # Canonical byte order also makes reports reproducible across hosts.
    return hashlib.sha256(np.asarray(pixels, dtype='<i4').tobytes()).hexdigest()


def verify(directory, output):
    directory, output = Path(directory), Path(output)
    report = {'plugins': {}, 'cases': [], 'passed': False}
    try:
        for uid, plugin in PLUGINS.items():
            if plugin not in get_decoder(uid).available_plugins:
                raise RuntimeError(f'Missing bundled decoder: {uid} / {plugin}')
            report['plugins'][uid] = plugin
        manifest = json.loads((directory / 'manifest.json').read_text())
        if not manifest:
            raise ValueError('Empty codec fixture manifest')
        for case in manifest:
            pixels = decode_pixels(directory / case['file'])
            passed = list(pixels.shape) == case['shape'] and pixel_digest(pixels) == case['sha256']
            report['cases'].append({'file': case['file'], 'passed': passed})
            if not passed:
                raise ValueError(f"Pixel mismatch: {case['file']}")
        report['passed'] = True
    except Exception as error:
        report['error'] = str(error)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + '\n')
    return 0 if report['passed'] else 1
