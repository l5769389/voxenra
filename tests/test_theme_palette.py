"""Guard the shared palette boundary, packaging and standalone QML fallback."""
import json
from pathlib import Path
import runpy
import re

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow  # Register Qt Quick before creating/destroying engines.
from shiboken6 import delete

from qt_dicom_viewer.ui.theme_palette import palette_for
from test_dicom_tags import qt_app

ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / 'src/qt_dicom_viewer/qml/theme'


def test_theme_source_is_valid_complete_and_generated_assets_are_current():
    data = json.loads((THEME / 'palettes.json').read_text())
    for theme in data['themes']:
        palette = palette_for(theme)
        assert all(QColor(value).isValid() for value in palette.values())
        assert all(palette[key] == value for key, value in data['imaging'].items())
        assert palette.keys() == palette_for('dark').keys()
    assert palette_for('unknown') == palette_for('dark')
    changed = palette_for('light'); changed['textPrimary'] = 'red'
    assert palette_for('light')['textPrimary'] != 'red'
    generator = runpy.run_path(str(ROOT / 'scripts/generate_theme_data.py'))
    assert (THEME / 'PaletteData.js').read_text() == generator['generated_text'](THEME / 'palettes.json')
    assets = {Path(source).resolve() for source, _ in runpy.run_path(str(ROOT / 'packaging/hooks/hook-qt_dicom_viewer.py'))['datas']}
    qrc = (ROOT / 'Voxenra.qrc').read_text()
    for name in ('palettes.json', 'PaletteData.js'):
        assert THEME / name in assets
        assert (THEME / name).relative_to(ROOT).as_posix() in qrc


def test_pages_do_not_bypass_theme_with_literal_colors():
    for path in (ROOT / 'src/qt_dicom_viewer/qml').rglob('*.qml'):
        assert not re.search(r'["\']#[0-9a-fA-F]{3,8}["\']', path.read_text()), path


def test_standalone_qml_uses_same_palette_without_controller(qt_app):
    engine = QQmlApplicationEngine()
    engine.loadData(b'import QtQuick\nimport "."\nQtObject {\n'
                      b'property color background: Theme.panelBackground\n'
                      b'property color imageText: Theme.overlayText\n'
                      b'property color preview: Theme.previewColors("light").panelBackground\n'
                      b'}', QUrl.fromLocalFile(str(THEME / 'PaletteProbe.qml')))
    obj = engine.rootObjects()[0] if engine.rootObjects() else None
    try:
        assert obj is not None
        assert obj.property('background').name() == palette_for('dark')['panelBackground']
        assert obj.property('imageText').name() == palette_for('dark')['overlayText']
        assert obj.property('preview').name() == palette_for('light')['panelBackground']
    finally:
        delete(engine)


def test_neutral_theme_surfaces_are_gray_and_image_roles_stay_identical():
    neutral = palette_for('graphite')
    for role in ('appBackground', 'panelBackground', 'cardBackground', 'controlBackground',
                 'controlHover', 'selectionBackground', 'selectionHover', 'textPrimary', 'iconDefault'):
        color = QColor(neutral[role])
        assert color.red() == color.green() == color.blue(), role
    imaging = json.loads((THEME / 'palettes.json').read_text())['imaging']
    assert {key: neutral[key] for key in imaging} == imaging
