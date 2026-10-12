from pathlib import Path
import importlib.util
import pytest


def module():
    from qt_dicom_viewer.infrastructure import local_segmentation_environment
    return local_segmentation_environment


def installed(root, windows=False):
    python = root / ('Scripts/python.exe' if windows else 'bin/python')
    python.parent.mkdir(parents=True, exist_ok=True)
    python.touch()
    package = root / ('Lib/site-packages/totalsegmentator' if windows else 'lib/python3.12/site-packages/totalsegmentator')
    package.mkdir(parents=True)
    (package / '__init__.py').touch()
    return python


def test_windows_discovers_dedicated_environment(tmp_path):
    python = installed(tmp_path/'Applications/TotalSegmentator-Local/venv', True)
    assert module().discover_python(home=tmp_path, platform='win32', environ={}, path_python=None) == str(python)


def test_windows_conda_registry_and_no_unrelated_python_fallback(tmp_path):
    root = tmp_path/'中文 环境'
    python = installed(root, True)
    # Conda Python lives at the environment root, unlike venv.
    actual = root/'python.exe'; python.rename(actual)
    registry = tmp_path/'.conda/environments.txt'
    registry.parent.mkdir();registry.write_text(str(root)+'\n', encoding='utf-8')
    assert module().discover_python(home=tmp_path, platform='win32', environ={}, path_python=None) == str(actual)
    (root/'Lib/site-packages/totalsegmentator/__init__.py').unlink()
    assert module().discover_python(home=tmp_path, platform='win32', environ={}, path_python=str(actual)) == ''


def test_mac_discovery_preserves_venv_symlink(tmp_path):
    python = installed(tmp_path/'Applications/TotalSegmentator-Local/venv')
    # Use an existing, isolated target on every host, including Windows CI.
    # A macOS system path would make the link dangling on other platforms.
    target = tmp_path/'system-python'
    target.touch()
    python.unlink(); python.symlink_to(target)
    # Do not resolve the symlink: that would escape the virtual environment.
    assert module().discover_python(home=tmp_path, platform='darwin', environ={}, path_python=None) == str(python)


def test_model_directory_accepts_dataset_or_trainer_and_rejects_arbitrary_folder(tmp_path):
    model = tmp_path/'results/Dataset297_TotalSegmentator_total_3mm_1559subj'
    trainer = model/'nnUNetTrainer_4000epochs_NoMirroring__nnUNetPlans__3d_fullres'
    trainer.mkdir(parents=True)
    assert module().normalize_weights(model) == model.parent
    assert module().normalize_weights(trainer) == model.parent
    assert module().normalize_weights(trainer/'fold_0') == model.parent
    assert module().normalize_weights(tmp_path) == tmp_path


def bridge():
    path=Path(__file__).resolve().parents[1]/'src/qt_dicom_viewer/infrastructure/totalsegmentator_bridge.py'
    spec=importlib.util.spec_from_file_location('isolated_totalseg_bridge',path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def test_model_validation_rejects_corrupt_nonempty_configuration(tmp_path):
    b=bridge()
    folder=tmp_path/b.MODEL/b.TRAINER
    (folder/'fold_0').mkdir(parents=True)
    (folder/'fold_0/checkpoint_final.pth').write_bytes(b'weights')
    (folder/'plans.json').write_text('broken json')
    (folder/'dataset.json').write_text('{}')
    assert not b.model_status(tmp_path)['ready']
    assert len(b.model_status(tmp_path)['issues'])==2
    (folder/'plans.json').write_text('{"plans_name":"nnUNetPlans"}')
    (folder/'dataset.json').write_text('{"labels":{"background":0}}')
    assert b.model_status(tmp_path)['ready']


def test_model_validation_reports_missing_weight(tmp_path):
    b=bridge()
    status=b.model_status(tmp_path)
    assert not status['ready'] and any('checkpoint_final.pth' in issue for issue in status['issues'])
