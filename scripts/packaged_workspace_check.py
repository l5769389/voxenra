"""Verify an installed application's live restoration of a supplied workspace.

Invoked by the frozen entry point; expected JSON contains independent source
hashes and a subset of the live state to compare. No QML or GUI interactions
are claimed by this controller/render diagnostic.
"""
from hashlib import sha256
import json
import math
from pathlib import Path
import time


def _compare(actual, expected, path, errors):
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            errors.append(f'{path}: expected an object')
            return
        for key, value in expected.items():
            if key not in actual:
                errors.append(f'{path}.{key}: missing')
            else:
                _compare(actual[key], value, f'{path}.{key}', errors)
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            errors.append(f'{path}: list length differs')
            return
        for i, value in enumerate(expected):
            _compare(actual[i], value, f'{path}[{i}]', errors)
    elif isinstance(expected, (float, int)) and not isinstance(expected, bool):
        if (not isinstance(actual, (float, int)) or isinstance(actual, bool)
                or not math.isclose(actual, expected, rel_tol=1e-7, abs_tol=1e-7)):
            errors.append(f'{path}: expected {expected!r}, got {actual!r}')
    elif actual != expected:
        errors.append(f'{path}: expected {expected!r}, got {actual!r}')


def _wait(qapp, condition, timeout=30):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() >= deadline:
            raise RuntimeError('Timed out waiting for workspace rendering')
        qapp.processEvents()
        time.sleep(.005)
    qapp.processEvents()


def _tab_state(tab):
    kind = tab.tab_config.tab_type.value
    if kind == 'cpr':
        pixels = tab._result.curve.modality_pixels
        return dict(type=kind, ready=bool(tab.ready), paths=len(tab.paths),
                    points=[list(point) for point in tab.current_path.control_points] if tab.current_path else [],
                    step_mm=tab.current_settings.step_mm, total_length_mm=tab.totalLength,
                    source_mismatch=bool(tab.sourceMismatch),
                    curve_center_hu=float(pixels[pixels.shape[0]//2, pixels.shape[1]//2]))
    if kind != '2d':
        raise ValueError(f'Unsupported diagnostic tab type: {kind}')
    view = tab.activeViewport
    qa = view.qaController.currentResult
    return dict(type=kind, ready=view.loadState == 'ready' and bool(view.imageSource),
                center_hu=float(view._modality_pixel[view._modality_pixel.shape[0]//2, view._modality_pixel.shape[1]//2]),
                image_shape=list(view._modality_pixel.shape),
                view={key: getattr(view._state, key) for key in ('zoom', 'pan_x', 'rotation_degrees')},
                measurements=[dict(length_mm=item.length_mm) for item in view._measure_controller._measurements.values()],
                qa=dict(water_ct_hu=qa.get('water_ct_hu'), noise_hu=qa.get('noise_hu'),
                        roi_count=len(qa.get('rois', [])), roi_diameter_mm=view.qaController.roiDiameterMm,
                        edge_clearance_mm=view.qaController.edgeClearanceMm))


def verify_workspace(workspace_path, expected_path, report_path, *, settings_path=None):
    """Return 0 only when real sources, restoration, results and preferences match.

    Default preferences use the installed brand's normal location and migration;
    callers may supply an isolated settings path for automated testing.
    """
    from voxplane import __version__
    report = dict(passed=False, version=__version__, errors=[])
    app = None
    try:
        workspace_path = Path(workspace_path).resolve()
        expected = json.loads(Path(expected_path).read_text(encoding='utf-8'))
        if not isinstance(expected, dict) or not expected.get('sources') or not expected.get('tabs'):
            raise ValueError('Expected manifest requires nonempty sources and tabs')
        for source in expected['sources']:
            relative = Path(source['path'])
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('Source paths must stay relative to the workspace')
            path = workspace_path.parent / relative
            if not path.is_file() or sha256(path.read_bytes()).hexdigest() != source['sha256']:
                raise ValueError(f'Missing or changed source image: {relative}')
        from PySide6.QtWidgets import QApplication
        from voxplane.ui.app_controller import AppController
        from voxplane.ui.dicom_image_provider import DicomImageProvider
        if settings_path is None:
            from voxplane.infrastructure.brand_settings import configure_storage_identity
            configure_storage_identity()
        qapp = QApplication.instance() or QApplication([])
        app = AppController(DicomImageProvider(), settings_path=settings_path)
        manager = app.workspaceDocumentController
        manager._autosave.stop()
        if not manager.restore_from(workspace_path):
            raise RuntimeError(str(manager.message))
        _wait(qapp, lambda: not manager.busy)
        if manager.isError or manager.hasMissingSources:
            raise RuntimeError(f'Workspace restore incomplete: {manager.message}')
        tabs = list(app.workspaceController._tab_dict.values())
        for tab in tabs:
            if tab.tab_config.tab_type.value == 'cpr':
                _wait(qapp, lambda: tab.ready or tab.hasError or tab.sourceMismatch)
                if not tab.ready:
                    raise RuntimeError(f'CPR restore failed: {tab.message}')
        report.update(series_count=len(app.panelController._scan_series_record),
                      tabs=[_tab_state(tab) for tab in tabs],
                      settings={name: app.settingsController.section(name)
                                for name in sorted({'appearance', 'updates'} | set(expected.get('settings', {})))})
        _compare(report, {key: value for key, value in expected.items() if key != 'sources'},
                 'workspace', report['errors'])
        report['passed'] = not report['errors']
    except Exception as error:
        report['errors'].append(f'{type(error).__name__}: {error}')
    finally:
        if app is not None:
            app.shutdown()
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if report['passed'] else 1
