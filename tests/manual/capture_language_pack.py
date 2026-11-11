"""Record the real settings UI while a local language pack is installed.

QT_QPA_PLATFORM=cocoa QT_QUICK_BACKEND=software PYTHONPATH=src:tests \
  .venv/bin/python tests/manual/capture_language_pack.py OUTPUT.gif [--english]

The demonstration uses isolated preferences and never edits a user's language folder.
"""
from io import BytesIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time

from PIL import Image, ImageDraw, ImageFont
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, Qt, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import delete

from voxplane.ui.app_controller import AppController
from voxplane.ui.dicom_image_provider import DicomImageProvider
from voxplane.ui.svg_icon_provider import SvgIconProvider
from voxplane.ui.controller import language_controller as language_module
from test_tag_qml import find

ROOT = Path(__file__).resolve().parents[2]


def pump(app, milliseconds=350):
    end = time.monotonic() + milliseconds / 1000
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(.01)


def launch(qt, settings_path, english=False):
    provider = DicomImageProvider()
    app = AppController(provider, settings_path=settings_path,
                        pacs_config_path=settings_path.with_name('pacs.json'),
                        pacs_import_root=settings_path.with_name('imports'))
    app.workspaceDocumentController.setAutomaticRecovery(False)
    if english:
        app.languageController.selectLanguage('en-US')
    engine = QQmlApplicationEngine()
    engine.addImageProvider('dicom', provider)
    engine.addImageProvider('navigation', SvgIconProvider())
    engine.rootContext().setContextProperty('appController', app)
    warnings = []
    engine.warnings.connect(lambda items: warnings.extend(item.toString() for item in items))
    engine.load(QUrl.fromLocalFile(str(ROOT / 'src/voxplane/qml/Main.qml')))
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]
    window.resize(1300, 780)
    window.requestActivate()
    app.workspaceController.openSettings()
    app.settingsController.selectCategory('appearance')
    find(window, 'languageChoice')
    pump(qt, 400)
    assert not warnings, warnings
    return app, engine, window


def shot(window, title):
    picture = window.grabWindow()
    assert not picture.isNull()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    picture.save(buffer, 'PNG')
    image = Image.open(BytesIO(data.data())).convert('RGB')
    image.thumbnail((1080, 720), Image.Resampling.LANCZOS)
    canvas = Image.new('RGB', (1080, image.height + 58), '#101b23')
    canvas.paste(image, ((1080 - image.width) // 2, 0))
    font = ImageFont.truetype('/System/Library/Fonts/STHeiti Medium.ttc', 26)
    ImageDraw.Draw(canvas).text((24, image.height + 13), title, fill='#e7f6fc', font=font)
    return canvas


def close(app, engine, window):
    window.hide()
    app.shutdown()
    delete(engine)


def capture(destination, english=False):
    qt = QApplication.instance() or QApplication([])
    qt.setQuitOnLastWindowClosed(False)
    # Recording the folder action must not open Finder or touch the real profile.
    language_module.reveal_path = lambda path: True
    frames = []
    captions = ([
        '1  Settings → Theme and language',
        '2  Open the folder to export editable language files',
        '3  Add es-ES.json, then restart the app',
        '4  Español appears automatically after restart',
        '5  Select the new language to apply it immediately',
    ] if english else [
        '1  设置 → 外观与语言',
        '2  打开目录：内置语言已导出为可编辑副本',
        '3  放入 es-ES.json，然后重启软件',
        '4  重启后，Español 自动出现在语言列表',
        '5  选择新语言，即时生效',
    ])
    with TemporaryDirectory(prefix='voxplane-language-demo-') as temp:
        settings_path = Path(temp) / 'settings.json'
        app, engine, window = launch(qt, settings_path, english)
        try:
            frames.append(shot(window, captions[0]))
            button = find(window, 'openLanguageDirectory')
            point = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
            pump(qt)
            folder = Path(app.languageController.directory)
            assert {path.name for path in folder.glob('*.json')} == {'zh-CN.json', 'en-US.json', 'pt-BR.json'}
            frames.append(shot(window, captions[1]))
            (folder / 'es-ES.json').write_text(json.dumps({
                'formatVersion': 1, 'locale': 'es-ES', 'name': 'Español',
                'messages': {
                    'appearance.title': 'Aspecto e idioma',
                    'appearance.language': 'Idioma',
                    'appearance.openPacks': 'Abrir carpeta de idiomas',
                    'appearance.reloadPacks': 'Recargar idiomas',
                },
            }, ensure_ascii=False, indent=2), encoding='utf-8')
            frames.append(shot(window, captions[2]))
        finally:
            close(app, engine, window)
        app, engine, window = launch(qt, settings_path, english)
        try:
            assert 'es-ES' in [item['locale'] for item in app.languageController.languages]
            combo = find(window, 'languageChoice')
            point = combo.mapToScene(QPointF(combo.width() / 2, combo.height() / 2)).toPoint()
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
            pump(qt)
            frames.append(shot(window, captions[3]))
            app.languageController.selectLanguage('es-ES')
            QTest.keyClick(window, Qt.Key_Escape)
            pump(qt)
            frames.append(shot(window, captions[4]))
        finally:
            close(app, engine, window)
    palette = frames[0].quantize(colors=224)
    indexed = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
    destination.parent.mkdir(parents=True, exist_ok=True)
    indexed[0].save(destination, save_all=True, append_images=indexed[1:],
                    duration=[1150, 1450, 1450, 1700, 1900], loop=0, disposal=2)
    print(destination, len(frames), 'frames')


if __name__ == '__main__':
    capture(Path(sys.argv[1]).resolve(), english='--english' in sys.argv)
