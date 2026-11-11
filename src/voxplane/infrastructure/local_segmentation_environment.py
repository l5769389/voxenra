"""Bounded local discovery; never launches, installs or modifies candidate environments."""
import os
from pathlib import Path
import shutil
import sys


def discover_python(*, home=None, platform=None, environ=None, path_python=False):
    home = Path(home or Path.home())
    windows = (platform or sys.platform) == 'win32'
    env = os.environ if environ is None else environ
    roots = [home/'Applications/TotalSegmentator-Local/venv',
             home/'TotalSegmentator-Local/venv']
    if env.get('LOCALAPPDATA'):
        roots.append(Path(env['LOCALAPPDATA'])/'TotalSegmentator-Local/venv')
    roots.extend(Path(env[key]) for key in ('VIRTUAL_ENV', 'CONDA_PREFIX') if env.get(key))
    try:
        roots.extend(Path(line.strip()) for line in
                     (home/'.conda/environments.txt').read_text(encoding='utf-8').splitlines()
                     if line.strip() and not line.lstrip().startswith('#'))
    except OSError:
        pass
    for name in ('miniconda3', 'anaconda3', 'miniforge3', 'mambaforge'):
        base = home/name
        roots.append(base)
        roots.extend(sorted((base/'envs').glob('*')))
    candidates = []
    for root in roots:
        candidates.extend([root/'Scripts/python.exe', root/'python.exe'] if windows else [root/'bin/python'])
    if path_python is False:
        path_python = shutil.which('python' if windows else 'python3')
    if path_python:
        candidates.append(Path(path_python))
    for python in dict.fromkeys(candidates):
        if not python.is_file():
            continue
        root = python.parent.parent if python.parent.name.lower() in ('scripts', 'bin') else python.parent
        packages = [root/'Lib/site-packages/totalsegmentator/__init__.py'] if windows else list(
            (root/'lib').glob('python*/site-packages/totalsegmentator/__init__.py'))
        if any(p.is_file() for p in packages):
            return str(python)  # Resolving symlinks can escape a venv.
    return ''


def normalize_weights(path):
    """Accept the results, Dataset297, trainer or fold folder without recursive search."""
    path = Path(path).expanduser()
    for candidate in (path, *list(path.parents)[:3]):
        if candidate.name == 'Dataset297_TotalSegmentator_total_3mm_1559subj':
            return candidate.parent
    return path


def discover_weights(python):
    env = Path(python).parent
    if env.name.lower() in ('scripts', 'bin'):
        env = env.parent
    local = env.parent/'models/nnunet/results'
    for path in (local, Path.home()/'Applications/TotalSegmentator-Local/models/nnunet/results',
                 Path.home()/'.totalsegmentator/nnunet/results'):
        if path.is_dir():
            return str(path)
    return str(Path.home()/'.totalsegmentator/nnunet/results')
