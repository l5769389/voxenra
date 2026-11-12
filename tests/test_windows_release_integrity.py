"""Execute release workflow steps with local packages and a simulated GitHub boundary."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

ROOT = Path(__file__).resolve().parents[1]


def workflow_step(name):
    text = (ROOT / '.github/workflows/build-windows.yml').read_text()
    step = text.split(f'- name: {name}\n', 1)[1].split('\n      - name:', 1)[0]
    run = step.split('        run: |\n', 1)[1]
    return textwrap.dedent(run)


@pytest.fixture
def release_env(tmp_path):
    if os.name == 'nt':
        pytest.skip('Release-job shell harness requires POSIX; direct Python helper tests run on Windows')
    assets = tmp_path / 'release-assets'
    assets.mkdir()
    (assets / 'VoxPlane.exe').write_bytes(b'new package')
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    gh = bin_dir / 'gh'
    gh.write_text(f'#!{sys.executable}\n' + textwrap.dedent('''\
        import json, os, pathlib, sys
        args = sys.argv[1:]
        with open('gh-calls.jsonl', 'a') as out:
            out.write(json.dumps(args) + '\\n')
        if args[:2] == ['release', 'view']:
            print(json.dumps({'isDraft': os.environ['DRAFT'] == 'true', 'tagName': 'v2.6.0',
                              'assets': [] if os.environ['REMOTE'] == 'missing' else
                              [{'name': 'VoxPlane.exe', 'size': 11}]}))
        elif args[:2] == ['release', 'download']:
            folder = pathlib.Path(args[args.index('--dir') + 1])
            folder.mkdir(parents=True, exist_ok=True)
            if os.environ['REMOTE'] != 'missing':
                (folder / 'VoxPlane.exe').write_bytes(b'new package' if os.environ['REMOTE'] == 'same' else b'old package')
        elif args[:2] not in (['release', 'upload'], ['release', 'create']):
            raise SystemExit('Unexpected gh command: ' + repr(args))
    '''))
    gh.chmod(0o755)
    return dict(os.environ, PATH=str(bin_dir) + os.pathsep + str(Path(sys.executable).parent) + os.pathsep + os.environ['PATH'],
                RELEASE_TAG='v2.6.0', RELEASE_APP_NAME='VoxPlane', DRAFT='false', REMOTE='same',
                RELEASE_HELPER=str(ROOT / 'scripts/windows_release.py'))


@pytest.mark.parametrize('remote', ['same', 'different', 'missing'])
def test_public_release_is_never_mutated(tmp_path, release_env, remote):
    release_env['REMOTE'] = remote
    result = subprocess.run(['bash', '-e', '-c', workflow_step('Upload assets to matching Release')],
                            cwd=tmp_path, env=release_env, capture_output=True, text=True)
    calls = [json.loads(line) for line in (tmp_path / 'gh-calls.jsonl').read_text().splitlines()]
    assert not any(call[1] in ('upload', 'create', 'delete', 'edit') for call in calls), calls
    assert (result.returncode == 0) == (remote == 'same'), result.stderr


def test_draft_release_accepts_upload(tmp_path, release_env):
    release_env['DRAFT'] = 'true'
    result = subprocess.run(['bash', '-e', '-c', workflow_step('Upload assets to matching Release')],
                            cwd=tmp_path, env=release_env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in (tmp_path / 'gh-calls.jsonl').read_text().splitlines()]
    assert any(call[:2] == ['release', 'upload'] for call in calls)


@pytest.mark.skipif(os.name == 'nt', reason='Exercises Ubuntu release-job bash and POSIX gh shim')
@pytest.mark.parametrize('source_sha', ['a' * 40, 'b' * 40, None])
def test_prepare_requires_actual_source_manifest(tmp_path, source_sha):
    source = tmp_path / 'windows-packages'
    (source / 'installers').mkdir(parents=True)
    files = {}
    for name in ['VoxPlane.exe', 'installers/VoxPlane-2.6.0-windows-x64-setup.exe']:
        path = source / name
        path.write_bytes(b'package')
        digest = hashlib.sha256(b'package').hexdigest()
        path.with_suffix('.exe.sha256').write_text(f'{digest}  {path.name}\n')
        files[name] = digest
    if source_sha:
        (source / 'windows-provenance.json').write_text(json.dumps({
            'source_sha': source_sha, 'version': '2.6.0', 'run_id': '123',
            'repository': 'owner/repo', 'console': False, 'files': files,
        }))
    env = dict(os.environ, PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ['PATH'], RELEASE_TAG='v2.6.0', RELEASE_APP_NAME='VoxPlane',
               RELEASE_SOURCE_SHA='a' * 40, ARTIFACT_RUN_ID='123', GH_REPO='owner/repo',
               RELEASE_HELPER=str(ROOT / 'scripts/windows_release.py'))
    result = subprocess.run(['bash', '-e', '-c', workflow_step('Prepare and verify Release assets')],
                            cwd=tmp_path, env=env, capture_output=True, text=True)
    assert (result.returncode == 0) == (source_sha == 'a' * 40), result.stderr
    if source_sha != 'a' * 40:
        assert not (tmp_path / 'release-assets').exists()


def test_missing_release_is_created_as_draft(tmp_path, release_env):
    gh = tmp_path / 'bin/gh'
    script = gh.read_text().replace("if args[:2] == ['release', 'view']:\n", "if args[:2] == ['release', 'view'] and not pathlib.Path('created').exists():\n    sys.stderr.write('release not found\\n')\n    raise SystemExit(1)\nif args[:2] == ['release', 'create']:\n    pathlib.Path('created').touch()\nelif args[:2] == ['release', 'view']:\n")
    gh.write_text(script)
    release_env['DRAFT'] = 'true'
    result = subprocess.run(['bash', '-e', '-c', workflow_step('Upload assets to matching Release')],
                            cwd=tmp_path, env=release_env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in (tmp_path / 'gh-calls.jsonl').read_text().splitlines()]
    assert any(call[:2] == ['release', 'create'] and '--draft' in call and '--verify-tag' in call for call in calls)
    assert any(call[:2] == ['release', 'upload'] for call in calls)


def test_release_read_error_cannot_trigger_mutations(tmp_path, release_env):
    gh = tmp_path / 'bin/gh'
    gh.write_text(gh.read_text().replace("if args[:2] == ['release', 'view']:\n", "if args[:2] == ['release', 'view']:\n    sys.stderr.write('authentication failed\\n')\n    raise SystemExit(1)\nif False:\n"))
    result = subprocess.run(['bash', '-e', '-c', workflow_step('Upload assets to matching Release')],
                            cwd=tmp_path, env=release_env, capture_output=True, text=True)
    assert result.returncode != 0
    calls = [json.loads(line) for line in (tmp_path / 'gh-calls.jsonl').read_text().splitlines()]
    assert len(calls) == 1 and calls[0][:2] == ['release', 'view']


@pytest.fixture
def helper():
    import importlib.util
    spec = importlib.util.spec_from_file_location('windows_release', ROOT / 'scripts/windows_release.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_branch_resolution_uses_event_commit_without_reading_branch(helper, tmp_path, monkeypatch):
    monkeypatch.setenv('GITHUB_SHA', 'a' * 40)
    monkeypatch.setenv('GITHUB_OUTPUT', str(tmp_path / 'output'))
    monkeypatch.setenv('RELEASE_TAG', '')
    monkeypatch.setattr(helper, 'gh', lambda *args: pytest.fail('Branch must not be re-resolved'))
    helper.resolve()
    assert (tmp_path / 'output').read_text() == 'source_sha=' + 'a' * 40 + '\n'


def test_annotated_tag_is_peeled_to_commit(helper, tmp_path, monkeypatch):
    monkeypatch.setenv('GITHUB_SHA', 'a' * 40)
    monkeypatch.setenv('GITHUB_OUTPUT', str(tmp_path / 'output'))
    monkeypatch.setenv('GITHUB_REPOSITORY', 'owner/repo')
    monkeypatch.setenv('RELEASE_TAG', 'v2.6.0')
    responses = {
        'repos/owner/repo/git/ref/tags/v2.6.0': {'type': 'tag', 'sha': 'b' * 40},
        'repos/owner/repo/git/tags/' + 'b' * 40: {'type': 'commit', 'sha': 'c' * 40},
    }
    monkeypatch.setattr(helper, 'gh', lambda command, endpoint: json.dumps({'object': responses[endpoint]}))
    helper.resolve()
    assert (tmp_path / 'output').read_text() == 'source_sha=' + 'c' * 40 + '\n'


def test_record_uses_actual_checkout_and_detects_mismatch(helper, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(['git', 'init', '-q'], check=True)
    (tmp_path / 'pyproject.toml').write_text('[project]\nversion = "2.6.0"\n')
    subprocess.run(['git', 'add', 'pyproject.toml'], check=True)
    subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.org',
                    'commit', '-qm', 'source'], check=True)
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    (tmp_path / 'dist').mkdir()
    (tmp_path / 'dist/VoxPlane.exe').write_bytes(b'package')
    monkeypatch.setenv('BUILD_SOURCE_SHA', sha)
    monkeypatch.setenv('GITHUB_RUN_ID', '123')
    monkeypatch.setenv('GITHUB_REPOSITORY', 'owner/repo')
    monkeypatch.setenv('BUILD_CONSOLE', 'false')
    helper.record()
    path = tmp_path / 'dist/windows-provenance.json'
    assert json.loads(path.read_text()) == {
        'source_sha': sha, 'version': '2.6.0', 'run_id': '123', 'repository': 'owner/repo',
        'console': False, 'files': {'VoxPlane.exe': 'bc4a71180870f7945155fbb02f4b0a2e3faa2a62d6d31b7039013055ed19869a'},
    }
    path.unlink()
    monkeypatch.setenv('BUILD_SOURCE_SHA', 'b' * 40)
    with pytest.raises(SystemExit, match='Checkout differs'):
        helper.record()
    assert not path.exists()


@pytest.mark.parametrize('field,value', [
    ('source_sha', 'b' * 40),
    ('version', '2.5.0'), ('run_id', '999'), ('repository', 'other/repo'),
    ('console', True), ('files', {'VoxPlane.exe': '0' * 64}),
])
def test_reuse_rejects_wrong_identity_and_package_hash(helper, tmp_path, monkeypatch, field, value):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / 'windows-packages'
    (source / 'installers').mkdir(parents=True)
    files = {}
    for name, data in [('VoxPlane.exe', b'portable'),
                       ('installers/VoxPlane-2.6.0-windows-x64-setup.exe', b'installer')]:
        (source / name).write_bytes(data)
        files[name] = hashlib.sha256(data).hexdigest()
    manifest = {'source_sha': 'a' * 40, 'version': '2.6.0', 'run_id': '123',
                'repository': 'owner/repo', 'console': False, 'files': files}
    path = source / 'windows-provenance.json'
    path.write_text(json.dumps(manifest))
    for key, setting in {'RELEASE_SOURCE_SHA': 'a' * 40, 'RELEASE_TAG': 'v2.6.0',
                         'ARTIFACT_RUN_ID': '123', 'GH_REPO': 'owner/repo',
                         'RELEASE_APP_NAME': 'VoxPlane'}.items():
        monkeypatch.setenv(key, setting)
    helper.verify()  # Otherwise a missing package/hash could mask a lost identity check.
    manifest[field] = value
    path.write_text(json.dumps(manifest))
    expected = 'Provenance checksum mismatch' if field == 'files' else 'Artifact provenance does not match'
    with pytest.raises(SystemExit, match=expected):
        helper.verify()
