"""Windows build provenance and immutable published-release checks (stdlib only)."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def gh(*args):
    return subprocess.check_output(['gh', *args], text=True, stderr=subprocess.PIPE)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def resolve():
    tag = os.environ.get('RELEASE_TAG', '')
    sha = os.environ['GITHUB_SHA']
    if tag:
        if not re.fullmatch(r'v[0-9][A-Za-z0-9.+-]*', tag):
            raise SystemExit('Invalid release tag')
        repo = os.environ['GITHUB_REPOSITORY']
        target = json.loads(gh('api', f'repos/{repo}/git/ref/tags/{tag}'))['object']
        while target['type'] == 'tag':
            target = json.loads(gh('api', f"repos/{repo}/git/tags/{target['sha']}"))['object']
        if target['type'] != 'commit':
            raise SystemExit('Release tag must resolve to a commit')
        sha = target['sha']
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise SystemExit('Expected immutable source commit')
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
        output.write(f'source_sha={sha}\n')


def record():
    import tomllib
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    if actual != os.environ['BUILD_SOURCE_SHA']:
        raise SystemExit('Checkout differs from resolved build source')
    root = Path('dist')
    files = sorted([*root.glob('*.exe'), *root.glob('installers/*.exe')])
    if not files:
        raise SystemExit('No Windows packages to record')
    manifest = {
        'source_sha': actual,
        'version': tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))['project']['version'],
        'run_id': os.environ['GITHUB_RUN_ID'],
        'repository': os.environ['GITHUB_REPOSITORY'],
        'console': os.environ.get('BUILD_CONSOLE') == 'true',
        'files': {p.relative_to(root).as_posix(): digest(p) for p in files},
    }
    (root / 'windows-provenance.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


def verify():
    root = Path('windows-packages')
    manifest = json.loads((root / 'windows-provenance.json').read_text(encoding='utf-8'))
    expected = {
        'source_sha': os.environ['RELEASE_SOURCE_SHA'],
        'version': os.environ['RELEASE_TAG'][1:],
        'run_id': os.environ['ARTIFACT_RUN_ID'],
        'repository': os.environ['GH_REPO'],
        'console': False,
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise SystemExit('Artifact provenance does not match this release commit and build')
    app, version = os.environ['RELEASE_APP_NAME'], expected['version']
    for name in (f'{app}.exe', f'installers/{app}-{version}-windows-x64-setup.exe'):
        if manifest.get('files', {}).get(name) != digest(root / name):
            raise SystemExit(f'Provenance checksum mismatch: {name}')


def publish():
    tag = os.environ['RELEASE_TAG']
    def view():
        return json.loads(gh('release', 'view', tag, '--json', 'tagName,isDraft,assets'))

    try:
        release = view()
    except subprocess.CalledProcessError as error:
        # Authentication/network failures must never be mistaken for absence.
        if error.stderr.strip() != 'release not found':
            raise
        gh('release', 'create', tag, '--verify-tag', '--draft', '--title',
           f"{os.environ['RELEASE_APP_NAME']} {tag}", '--generate-notes')
        release = view()
    files = sorted(Path('release-assets').iterdir())
    if not files:
        raise SystemExit('No verified release assets')
    if release['isDraft'] is True:
        gh('release', 'upload', tag, *(str(p) for p in files), '--clobber')
        return
    assets = {asset['name']: asset for asset in release['assets']}
    with tempfile.TemporaryDirectory() as folder:
        for path in files:
            if path.name not in assets or assets[path.name]['size'] != path.stat().st_size:
                raise SystemExit(f'Published release is immutable; missing or changed asset: {path.name}')
            gh('release', 'download', tag, '--pattern', path.name, '--dir', folder)
            if digest(Path(folder) / path.name) != digest(path):
                raise SystemExit(f'Published release is immutable; changed asset: {path.name}')
    print('Published Windows assets are identical; no changes made')


if __name__ == '__main__':
    {'resolve': resolve, 'record': record, 'verify': verify, 'publish': publish}[sys.argv[1]]()
