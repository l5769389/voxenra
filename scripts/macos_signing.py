"""Developer ID preflight and fail-closed notarization; credentials stay in Keychain."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory


def resolve_identity(identity: str) -> str:
    """Resolve an exact valid Developer ID name or SHA-1, never a fuzzy match."""
    result = subprocess.run(['security', 'find-identity', '-v', '-p', 'codesigning'],
                            check=True, capture_output=True, text=True)
    matches = []
    for fingerprint, name in re.findall(r'^\s*\d+\) ([A-Fa-f0-9]{40}) "([^"]+)"\s*$', result.stdout, re.M):
        if name.startswith('Developer ID Application: ') and (identity == name or identity.upper() == fingerprint.upper()):
            matches.append(fingerprint.upper())
    if len(matches) != 1:
        raise ValueError('未找到唯一、有效且带私钥的 Developer ID Application 身份；请检查钥匙串证书，使用完整名称或 SHA-1。')
    return matches[0]


def preflight(identity: str, profile: str | None) -> str:
    fingerprint = resolve_identity(identity)
    if profile:
        for tool in ('notarytool', 'stapler'):
            subprocess.run(['xcrun', '--find', tool], check=True, capture_output=True, text=True)
        # Read-only authentication check before the expensive build; never uploads a file.
        subprocess.run(['xcrun', 'notarytool', 'history', '--keychain-profile', profile,
                        '--output-format', 'json'], check=True, capture_output=True, text=True)
    return fingerprint


def notarize(archive: Path, profile: str, logs: Path, label: str) -> None:
    logs.mkdir(parents=True, exist_ok=True)
    command = ['xcrun', 'notarytool', 'submit', str(archive), '--keychain-profile', profile,
               '--wait', '--output-format', 'json']
    print(f'提交 Apple 公证：{archive.name}；等待结果…', flush=True)
    result = subprocess.run(command, capture_output=True, text=True)
    report = logs / f'{label}-submit.json'
    report.write_text(result.stdout, encoding='utf-8')
    (logs / f'{label}-stderr.log').write_text(result.stderr, encoding='utf-8')
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    submission = payload.get('id')
    if isinstance(submission, str) and submission:
        # Preserve Apple's diagnostics even if the submission was rejected.
        subprocess.run(['xcrun', 'notarytool', 'log', submission, '--keychain-profile', profile,
                        str(logs / f'{label}-notary-log.json')], capture_output=True, text=True)
    if result.returncode:
        raise subprocess.CalledProcessError(result.returncode, command)
    if payload.get('status') != 'Accepted':
        raise ValueError(f'Apple 公证未通过（{payload.get("status", "未知状态")}）；查看 {report}')


def staple(target: Path) -> None:
    subprocess.run(['xcrun', 'stapler', 'staple', str(target)], check=True)
    subprocess.run(['xcrun', 'stapler', 'validate', str(target)], check=True)


def notarize_app(application: Path, profile: str, logs: Path) -> None:
    # Staple the app before putting it inside the final read-only DMG.
    with TemporaryDirectory(prefix='voxenra-notary-') as temporary:
        archive = Path(temporary) / f'{application.stem}.zip'
        subprocess.run(['ditto', '-c', '-k', '--keepParent', str(application), str(archive)], check=True)
        notarize(archive, profile, logs, 'app')
    staple(application)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(application)], check=True)
    subprocess.run(['spctl', '--assess', '--type', 'execute', '--verbose=2', str(application)], check=True)


def notarize_dmg(output: Path, identity: str, profile: str, logs: Path) -> None:
    subprocess.run(['codesign', '--force', '--sign', identity, '--timestamp', str(output)], check=True)
    subprocess.run(['codesign', '--verify', '--strict', str(output)], check=True)
    notarize(output, profile, logs, 'dmg')
    staple(output)
    subprocess.run(['spctl', '--assess', '--type', 'open', '--context',
                    'context:primary-signature', '--verbose=2', str(output)], check=True)
