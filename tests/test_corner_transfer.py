from copy import deepcopy
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from qt_dicom_viewer.settings.preferences import CORNER_FIELDS
from test_pacs_qml import scene
from test_dicom_tags import qt_app, wait_until
from test_settings_redesign import open_page, reveal_setting
from test_tag_qml import find, settled_point
from test_favorite_directories_ui import shot


def test_corner_transfer_atomic_persistence_and_rejections(tmp_path, monkeypatch):
    settings = SettingsController(path=tmp_path / 'settings.json')
    source = settings.values['corners']['topLeft']
    field = source[0]
    assert settings.setValue('corners', 'bottomRight', [])
    assert settings.transferCornerField('topLeft', field, 'bottomRight', 0)
    assert field not in settings.values['corners']['topLeft']
    assert settings.values['corners']['bottomRight'] == [field]
    assert SettingsController(path=settings._path).values['corners'] == settings.values['corners']
    assert settings.addCornerField('topLeft', field)
    before = deepcopy(settings.values)
    assert not settings.transferCornerField('topLeft', field, 'bottomRight', 0)
    assert settings.values == before
    others = [k for k in CORNER_FIELDS if k != field][:8]
    assert settings.setValue('corners', 'bottomRight', others)
    before = deepcopy(settings.values)
    assert not settings.transferCornerField('topLeft', field, 'bottomRight', 0)
    assert not settings.transferCornerField('bad', field, 'bottomRight', 0)
    assert not settings.transferCornerField('topLeft', field, 'topLeft', 100)
    assert settings.values == before
    assert settings.setValue('corners', 'bottomRight', [])
    before = deepcopy(settings.values)
    monkeypatch.setattr(settings, '_persist_settings', lambda candidate: False)
    assert not settings.transferCornerField('topLeft', field, 'bottomRight', 0)
    assert settings.values == before


def drag_between(window, source, destination, cancel=False):
    window.requestActivate()
    QTest.qWaitForWindowActive(window)
    a = settled_point(source, QPointF(14, source.height() / 2))
    b = settled_point(destination, QPointF(destination.width() / 2, destination.height() - 12))
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, a)
    for step in range(1, 16):
        QTest.mouseMove(window, a + (b - a) * (step / 15), 15)
    if cancel:
        QTest.keyClick(window, Qt.Key_Escape)
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, b)
    QTest.qWait(80)


def test_cross_corner_drag_empty_duplicate_cancel_and_persist(scene):
    window, app, warnings = open_page(scene, 'corners')
    settings = app.settingsController
    field = settings.values['corners']['topLeft'][0]
    settings.setValue('corners', 'topRight', [])
    source = find(window, 'cornerDrag-topLeft-0')
    reveal_setting(window, source)
    target = find(window, 'cornerPreview-topRight')
    before = settings.values['corners']
    drag_between(window, source, target, cancel=True)
    assert settings.values['corners'] == before
    drag_between(window, source, target)
    assert settings.values['corners']['topRight'] == [field]
    assert field not in settings.values['corners']['topLeft']
    assert SettingsController(path=settings._path).values['corners'] == settings.values['corners']
    # Move vertically between top and bottom as well as horizontally.
    drag_between(window, find(window, 'cornerDrag-topRight-0'), find(window, 'cornerPreview-bottomRight'))
    assert settings.values['corners']['topRight'] == []
    bottom_index = settings.values['corners']['bottomRight'].index(field)
    drag_between(window, find(window, f'cornerDrag-bottomRight-{bottom_index}'), target)
    assert settings.values['corners']['topRight'] == [field]
    settings.addCornerField('topLeft', field)
    last = len(settings.values['corners']['topLeft']) - 1
    before = settings.values['corners']
    drag_between(window, find(window, f'cornerDrag-topLeft-{last}'), target)
    assert settings.values['corners'] == before
    shot(window, 'four-corner-direct-dark')
    app.settingsController.setValue('appearance', 'theme', 'light')
    window.resize(1000, 900)
    QTest.qWait(80)
    shot(window, 'four-corner-direct-light-narrow')
    assert not warnings, warnings
