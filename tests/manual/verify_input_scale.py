"""Fresh-process native UI size check. Run separately for 100 / 115 / 130."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tests')]
from qt_dicom_viewer.settings.interface_scale import apply_interface_scale
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QUrl, QPointF
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtTest import QTest
from shiboken6 import delete
from qt_dicom_viewer.app import configure_application_identity
from qt_dicom_viewer.ui.app_controller import AppController
from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
from test_tag_qml import find, descendants
scale = int(sys.argv[1])
out = ROOT/'build/input-settings/scale'
out.mkdir(parents=True, exist_ok=True)
with TemporaryDirectory(prefix='voxenra-scale-qa-') as directory:
    directory = Path(directory)
    path = directory/'display-settings.json'
    path.write_text(json.dumps({'appearance': {'interfaceScale': scale}}))
    assert apply_interface_scale(path) == scale
    app = QApplication([])
    configure_application_identity(app)
    provider = DicomImageProvider()
    controller = AppController(provider, settings_path=path, pacs_config_path=directory/'pacs.json')
    engine = QQmlApplicationEngine()
    engine.addImageProvider('dicom', provider)
    engine.addImageProvider('navigation', SvgIconProvider())
    engine.rootContext().setContextProperty('appController', controller)
    warnings = []
    engine.warnings.connect(lambda rows: warnings.extend(r.toString() for r in rows))
    engine.load(QUrl.fromLocalFile(str(ROOT/'src/qt_dicom_viewer/qml/Main.qml')))
    window = engine.rootObjects()[0]
    controller.workspaceController.openSettings()
    results = []
    for theme, locale in [('graphite', 'zh-CN'), ('light', 'en-US')]:
        controller.settingsController.setValue('appearance', 'theme', theme)
        controller.languageController.selectLanguage(locale)
        window.resize(min(1280, window.screen().availableGeometry().width()), min(720, window.screen().availableGeometry().height()))
        for category in ('appearance', 'input', 'privacy'):
            controller.settingsController.selectCategory(category)
            QTest.qWait(150)
            form = find(window, 'displaySettingsScroll')
            for item in descendants(form):
                if item.isVisible() and item.metaObject().indexOfProperty('checkable') >= 0:
                    p = item.mapToItem(form, QPointF())
                    assert p.x() >= -1 and p.x() + item.width() <= form.width() + 1, (category, item.objectName(), p.x(), item.width(), form.width())
            image = window.grabWindow()
            assert image.save(str(out/f'{scale}-{locale}-{category}.png'))
            results.append(dict(category=category, locale=locale, width=window.width(), height=window.height(), dpr=window.devicePixelRatio(), pixels=[image.width(), image.height()]))
    assert not warnings, warnings
    (out/f'{scale}.json').write_text(json.dumps(results, indent=2))
    print(json.dumps(results))
    window.hide()
    controller.shutdown()
    delete(engine)
