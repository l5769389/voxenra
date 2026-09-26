"""Live chrome/text changes must leave loaded image and editing state intact."""
import json
import re
from pathlib import Path
from copy import deepcopy

from PySide6.QtCore import QObject, QCoreApplication
from PySide6.QtTest import QTest
import pytest

from qt_dicom_viewer.i18n.messages import builtin, bundled_locales, parameters, message, localize, snapshot
from qt_dicom_viewer.ui.controller.language_controller import LanguageController
from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from qt_dicom_viewer.ui.controller.appearance_controller import LIGHT, DARK, AppearanceController
from qt_dicom_viewer.core.measurement_report import csv_bytes, pdf_bytes
from qt_dicom_viewer.ui.dialogs.local_import_dialog import LocalImportDialog
from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_tag_qml import find, click
from test_workspace_persistence import draw_length
from test_pet_fusion import paired_series


def test_builtin_languages_are_complete_and_parameters_match():
    zh, en = builtin()['messages'], builtin('en-US')['messages']
    assert zh.keys() == en.keys()
    assert len(zh) > 1500
    for key in zh:
        assert parameters(zh[key]) == parameters(en[key]), key
        assert not re.search('[\u4e00-\u9fff]', en[key]), key
    for locale in bundled_locales():
        pack = builtin(locale)
        assert pack['locale'] == locale and pack['formatVersion'] == 1 and pack['name']
        for key, value in pack['messages'].items():
            assert key in en and parameters(value) == parameters(en[key]), (locale, key)
    from PySide6.QtCore import QTranslator
    from qt_dicom_viewer.i18n.qt_catalog import encode_catalog
    translator = QTranslator()
    for catalog in (zh, en):
        data = encode_catalog(catalog)
        assert translator.load(data)
        for key, value in catalog.items(): assert translator.translate('', key) == value, key
    for path in Path('src/qt_dicom_viewer/qml').rglob('*.qml'):
        for key in re.findall(r'qsTrId\("([^"]+)"\)', path.read_text()): assert key in zh, (path, key)


def test_portuguese_pack_is_selectable_and_new_strings_fall_back_to_english(qt_app, tmp_path):
    settings = SettingsController(path=tmp_path / 'settings.json')
    language = LanguageController(settings, root=tmp_path / 'languages')
    try:
        assert 'pt-BR' in [item['locale'] for item in language.languages]
        assert language.selectLanguage('pt-BR')
        assert language.locale == 'pt-BR'
        assert localize(message('text.0414')) == builtin('pt-BR')['messages']['text.0414']
        assert localize(message('workspace.exit.updateQuestion')) == builtin('en-US')['messages']['workspace.exit.updateQuestion']
        assert settings.section('appearance')['language'] == 'pt-BR'
    finally:
        language.shutdown()
    restarted = SettingsController(path=tmp_path / 'settings.json')
    language = LanguageController(restarted, root=tmp_path / 'languages')
    try:
        assert language.locale == 'pt-BR'
        assert language.messages['text.0414'] == builtin('pt-BR')['messages']['text.0414']
    finally:
        language.shutdown()


def test_new_bundled_json_is_discovered_without_code_registration(qt_app, tmp_path, monkeypatch):
    from qt_dicom_viewer.i18n import messages as catalog
    bundled = tmp_path / 'qml/assets/languages'
    bundled.mkdir(parents=True)
    source = Path('src/qt_dicom_viewer/qml/assets/languages')
    for locale in ('zh-CN', 'en-US'):
        (bundled / f'{locale}.json').write_bytes((source / f'{locale}.json').read_bytes())
    (bundled / 'es-ES.json').write_text(json.dumps(dict(
        formatVersion=1, locale='es-ES', name='Español',
        messages={'text.0539': 'Cancelar'})), encoding='utf-8')
    monkeypatch.setattr(catalog, 'files', lambda package: tmp_path)
    catalog.builtin.cache_clear()
    catalog.bundled_locales.cache_clear()
    language = None
    try:
        language = LanguageController(SettingsController(path=False), root=tmp_path / 'user-languages')
        assert catalog.bundled_locales() == ('zh-CN', 'en-US', 'es-ES')
        assert {'locale': 'es-ES', 'name': 'Español'} in language.languages
        assert language.selectLanguage('es-ES')
        assert localize(message('text.0539')) == 'Cancelar'
        assert localize(message('text.0532')) == 'Open images'
    finally:
        if language is not None: language.shutdown()
        catalog.builtin.cache_clear()
        catalog.bundled_locales.cache_clear()


def test_language_pack_is_discovered_after_restart(qt_app, tmp_path, monkeypatch):
    folder = tmp_path / 'languages'
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.language_controller.reveal_path', lambda path: True)
    settings = SettingsController(path=tmp_path / 'settings.json')
    language = LanguageController(settings, root=folder)
    try:
        assert 'pt-BR' in [item['locale'] for item in language.languages]
        assert not folder.exists()
        assert language.openDirectory()
        assert {path.name for path in folder.iterdir()} == {'zh-CN.json', 'en-US.json', 'pt-BR.json'}
        template = json.loads((folder / 'pt-BR.json').read_text(encoding='utf-8'))
        assert len(template.pop('_builtinTemplateDigest')) == 64
        assert template == builtin('pt-BR')
        (folder / 'fr-FR.json').write_text(json.dumps(dict(
            formatVersion=1, locale='fr-FR', name='Français',
            messages={'text.0539': 'Annuler'})), encoding='utf-8')
        assert 'fr-FR' not in [item['locale'] for item in language.languages]
    finally:
        language.shutdown()
    language = LanguageController(settings, root=folder)
    try:
        assert {'locale': 'fr-FR', 'name': 'Français'} in language.languages
        assert language.selectLanguage('fr-FR')
        assert localize(message('text.0539')) == 'Annuler'
        assert localize(message('text.0532')) == 'Open images'
    finally:
        language.shutdown()


def test_exported_builtin_copy_does_not_mask_updated_bundled_translation(qt_app, tmp_path, monkeypatch):
    from qt_dicom_viewer.i18n import messages as catalog
    folder = tmp_path / 'languages'
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.language_controller.reveal_path', lambda path: True)
    settings = SettingsController(path=tmp_path / 'settings.json')
    language = LanguageController(settings, root=folder)
    try:
        assert language.openDirectory()
    finally:
        language.shutdown()

    current_builtin = catalog.builtin
    def upgraded_builtin(locale='zh-CN'):
        pack = current_builtin(locale)
        if locale == 'pt-BR':
            return dict(pack, messages={**pack['messages'], 'text.0539': 'Cancelar atualizado'})
        return pack
    monkeypatch.setattr(catalog, 'builtin', upgraded_builtin)

    language = LanguageController(settings, root=folder)
    try:
        assert language.selectLanguage('pt-BR')
        assert localize(message('text.0539')) == 'Cancelar atualizado'
        exported = json.loads((folder / 'pt-BR.json').read_text(encoding='utf-8'))
        exported['messages']['text.0539'] = 'Minha tradução'
        (folder / 'pt-BR.json').write_text(json.dumps(exported), encoding='utf-8')
        assert language.reload()
        assert localize(message('text.0539')) == 'Minha tradução'
    finally:
        language.shutdown()


def test_pack_overrides_new_languages_reload_and_invalid_edits(qt_app, tmp_path, monkeypatch):
    settings = SettingsController(path=tmp_path/'settings.json')
    language = LanguageController(settings, root=tmp_path/'languages')
    monkeypatch.setattr('qt_dicom_viewer.ui.controller.language_controller.reveal_path', lambda path: True)
    try:
        assert language.locale == 'zh-CN'
        assert language.openDirectory()
        template = language.root/'en-US.json'
        pack = dict(builtin('en-US'), messages={'text.0532': 'Browse images'})
        template.write_text(json.dumps(pack))
        assert language.reload() and language.selectLanguage('en-US')
        assert localize(message('text.0532')) == 'Browse images'
        assert localize(message('text.0539')) == 'Cancel'
        original = template.read_bytes(); language.openDirectory(); assert template.read_bytes() == original
        custom = dict(pack, locale='fr-FR', name='Français', messages={'text.0539': 'Annuler'})
        (language.root/'fr-FR.json').write_text(json.dumps(custom))
        assert language.reload() and language.selectLanguage('fr-FR')
        assert localize(message('text.0539')) == 'Annuler'
        assert localize(message('text.0532')) == 'Open images'
        (language.root/'fr-FR.json').write_text('{broken')
        assert not language.reload() and localize(message('text.0539')) == 'Annuler'
        custom['messages']['text.0541'] = '{wrong}'
        (language.root/'fr-FR.json').write_text(json.dumps(custom))
        assert not language.reload() and localize(message('text.0539')) == 'Annuler'
        assert settings.section('appearance')['language'] == 'fr-FR'
        assert localize('患者自己起的名字') == '患者自己起的名字'
    finally: language.shutdown()


def test_preferences_restart_defaults_and_widget_translations(qt_app, tmp_path):
    path=tmp_path/'settings.json'
    path.write_text('{"layout":{"rightPanelWidth":300}}')
    settings=SettingsController(path=path)
    assert settings.section('appearance') == {'theme':'dark','language':'zh-CN'}
    appearance=AppearanceController(settings); language=LanguageController(settings, root=tmp_path/'languages')
    dialog=LocalImportDialog(str(tmp_path))
    try:
        settings.setValue('appearance','theme','light'); language.selectLanguage('en-US'); QTest.qWait(30)
        assert appearance.colors['panelBackground'] == LIGHT['panelBackground']
        assert dialog.windowTitle() == 'Open images' and dialog.cancel_button.text() == 'Cancel'
        assert LIGHT['panelBackground'] in dialog.styleSheet()
        restarted=SettingsController(path=path)
        assert restarted.section('appearance') == {'theme':'light','language':'en-US'}
        settings.resetSection('appearance')
        assert language.locale == 'zh-CN' and appearance.theme == 'dark'
        assert dialog.cancel_button.text() == '取消'
    finally: dialog.deleteLater(); language.shutdown()


def test_report_uses_snapshot_and_keeps_patient_data(qt_app, tmp_path):
    settings=SettingsController(path=False); language=LanguageController(settings, root=tmp_path)
    try:
        language.selectLanguage('en-US'); frozen=snapshot()
        rows=[dict(patient='患者原名', patient_id='ID123', series='患者自定义',kind=message('text.0321'),id='M001',modality='CT',view='2D',length_mm=1.234)]
        language.selectLanguage('zh-CN')
        english=csv_bytes(rows,translations=frozen).decode('utf-8-sig')
        assert 'Length' in english and '患者原名' in english and '1.23' in english
        assert '长度' in csv_bytes(rows).decode('utf-8-sig')
        assert pdf_bytes(rows,translations=frozen).startswith(b'%PDF')
    finally:language.shutdown()


def test_four_combinations_preserve_loaded_view_measurements_and_workspace(sidebar_scene, tmp_path):
    window, app, records, warnings=sidebar_scene
    window.resize(1000,600)
    ws=app.workspaceController; manager=app.workspaceDocumentController
    manager._autosave.stop()
    ws.createTab(records[0].series_instance_uid, '患者自定义页签', '2d')
    wait_until(lambda:ws.activeLoadState.status=='ready')
    tab,view=ws.activeTab,ws.activeViewport
    draw_length(view)
    before=deepcopy(view._state),deepcopy(view._measure_controller._measurements)
    manager._dirty=False
    renders=[]; view.displayStyleChanged.connect(lambda:renders.append('display'))
    ws.openSettings(); app.settingsController.selectCategory('appearance')
    QTest.qWait(80)
    manager._dirty=False
    for theme,locale in [('light','en-US'),('dark','en-US'),('light','zh-CN'),('dark','zh-CN')]:
        app.settingsController.setValue('appearance','theme',theme)
        app.languageController.selectLanguage(locale); QTest.qWait(120)
        assert view._state==before[0] and view._measure_controller._measurements==before[1]
        assert not manager.dirty and not renders
        assert app.settingsController.activeCategory=='appearance'
        expected='Reload language packs' if locale=='en-US' else '重新加载语言包'
        assert find(window,'reloadLanguagePacks').property('text')==expected
        assert window.grabWindow().save(str(tmp_path/(theme+'-'+locale+'.png')))
    assert not warnings,warnings


def test_light_palette_text_contrast_and_image_color_independence():
    def luminance(color):
        values=[int(color[i:i+2],16)/255 for i in (1,3,5)]
        linear=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in values]
        return sum(v*w for v,w in zip(linear,(.2126,.7152,.0722)))
    from qt_dicom_viewer.ui.theme_palette import palette_for
    for palette in (DARK, LIGHT, palette_for("graphite")):
        for fg,bg in [('textPrimary','panelBackground'),('textSecondary','controlBackground'),
                      ('textMuted','panelBackgroundStrong'),('textSubtle','panelBackground'),
                      ('textOnPrimary','primaryButtonBackground'),('textOnPrimary','primaryButtonHover'),
                      ('textOnPrimary','primaryButtonPressed'),('textPrimary','selectionHover'),
                      ('dangerColor','dangerSurface')]:
            high,low=sorted((luminance(palette[fg]),luminance(palette[bg])),reverse=True)
            assert (high+.05)/(low+.05)>=4.5,(fg,bg)
    for key in ('canvasBackground','overlayText','overlayOutline','measurementPrimary','measurementSelected','measurementHandle'):
        assert LIGHT[key]==DARK[key]


@pytest.mark.parametrize('kind', ['montage', 'mpr', '3d', 'pet', 'pet3d', 'fusion'])
def test_live_switch_keeps_all_view_state_and_history(qt_app, paired_series, tmp_path, kind):
    from qt_dicom_viewer.ui.app_controller import AppController
    from qt_dicom_viewer.ui.dicom_image_provider import DicomImageProvider
    from qt_dicom_viewer.model import DicomFolderScanSnapshot
    from qt_dicom_viewer.ui.workspace_snapshot import tab_snapshot
    from qt_dicom_viewer.core.workspace_state import dumps
    _, ct, pet = paired_series
    app = AppController(DicomImageProvider(), settings_path=False)
    try:
        scan = DicomFolderScanSnapshot(tmp_path, 6, 6, 0, [ct, pet])
        app.panelController.update_series_session(scan)
        app.panelController._update_series_record(scan)
        ws = app.workspaceController
        if kind == 'fusion': ws.createFusionTab(ct.series_instance_uid, pet.series_instance_uid)
        else:
            series = pet if kind.startswith('pet') else ct
            ws.createTab(series.series_instance_uid, 'My own tab', {'pet':'mpr','pet3d':'3d'}.get(kind,kind))
        wait_until(lambda: ws.activeLoadState.status in ('ready','error'), timeout=20000)
        assert ws.activeLoadState.status == 'ready', ws.activeLoadState.message
        QTest.qWait(60)
        tab = ws.activeTab
        history = tab.historyController
        saved = dumps(tab_snapshot(tab)), list(history._undo), list(history._redo)
        renders = []
        ws.renderRequested.connect(lambda request: renders.append(request))
        app.workspaceDocumentController._autosave.stop()
        app.workspaceDocumentController._dirty = False
        for theme, locale in [('light','en-US'),('dark','zh-CN'),('graphite','en-US')]*2:
            app.settingsController.setValue('appearance','theme',theme)
            app.languageController.selectLanguage(locale)
            QTest.qWait(50)
            assert ws.activeTab is tab
            assert (dumps(tab_snapshot(tab)), history._undo, history._redo) == saved
            assert not app.workspaceDocumentController.dirty and not renders
    finally: app.shutdown()


def test_manual_retranslation_preserves_chapter_scroll_and_search(qt_app, tmp_path):
    from qt_dicom_viewer.ui.controller.manual_tab_controller import ManualTabController
    language = LanguageController(SettingsController(path=False), root=tmp_path)
    manual = ManualTabController()
    try:
        manual.selectChapter('export'); manual.setScrollPosition(123)
        assert manual.currentChapter['title']
        language.selectLanguage('en-US')
        assert manual.chapterId == 'export' and manual.scrollPosition == 123
        assert 'Export' in manual.currentChapter['title']
        assert manual.currentChapter['example'].startswith('en/')
        manual.setSearch('language packs')
        assert any(ch['id']=='settings' for group in manual.navigation for ch in group['chapters'])
        language.selectLanguage('zh-CN')
        assert manual.chapterId == 'export' and manual.scrollPosition == 123
        assert not manual.navigation
    finally: language.shutdown()


def test_in_flight_report_freezes_language_and_status_updates(qt_app, tmp_path, monkeypatch):
    from threading import Event
    from test_workspace_persistence import populated_app
    from qt_dicom_viewer.ui.controller import measurement_report_controller as reports
    app, record = populated_app(tmp_path)
    entered, release = Event(), Event()
    original = reports.csv_bytes
    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(reports, 'csv_bytes', delayed)
    try:
        draw_length(app.workspaceController.activeViewport)
        app.settingsController.setValue('measurement', 'decimalPlaces', 3)
        app.languageController.selectLanguage('en-US')
        report = app.exportController.measurementReport
        path = tmp_path/'report.csv'
        assert report.export_to(path)
        wait_until(entered.is_set)
        english_status = report.message
        app.settingsController.setValue('measurement', 'decimalPlaces', 0)
        app.languageController.selectLanguage('zh-CN')
        assert report.busy and report.message != english_status
        release.set(); wait_until(lambda:not report.busy)
        text = path.read_text('utf-8-sig')
        assert 'Patient 1' in text and 'Length' in text and '患者' not in text
        assert record.patient_id not in text
        import csv, io
        result_rows = list(csv.reader(io.StringIO(text)))
        length = app.workspaceController.activeViewport.measurementController.committed_measurements[0].length_mm
        assert result_rows[1][9] == f'{length:.3f}'
        app.languageController.selectLanguage('en-US')
        frozen = snapshot()
        app.languageController.selectLanguage('zh-CN')
        pdf = tmp_path/'report.pdf'
        rows, _, _ = reports.capture_results(app.workspaceController, app.panelController._series_catalog)
        pdf.write_bytes(pdf_bytes(rows, translations=frozen))
        from PySide6.QtPdf import QPdfDocument
        document = QPdfDocument()
        assert document.load(str(pdf)) == QPdfDocument.Error.None_
        wait_until(lambda: document.status() == QPdfDocument.Status.Ready)
        assert document.pageCount() > 0
        contents = '\n'.join(document.getAllText(page).text() for page in range(document.pageCount()))
        assert 'Patient 1' in contents and 'Length' in contents and '患者' not in contents
        document.close()
    finally: release.set(); app.shutdown()


def test_loading_error_keeps_message_id_across_language_changes(qt_app, tmp_path):
    from types import SimpleNamespace
    from test_workspace_persistence import populated_app
    app, record = populated_app(tmp_path)
    try:
        state = app.workspaceController.activeLoadState
        state.restart()
        initial = state.message
        app.languageController.selectLanguage('en-US')
        assert state.message != initial and state.loading
        state._pending['view'] = 'request'
        state.accept_failure(SimpleNamespace(viewport_id='view', request_id='request', error=ValueError(message('text.0440'))))
        assert state.errorMessage == localize(message('text.0440'))
        english = state.errorMessage
        app.languageController.selectLanguage('zh-CN')
        assert state.status == 'error' and state.errorMessage != english
        assert state.errorMessage == localize(message('text.0440'))
        assert state._error.key == 'text.0440'
    finally: app.shutdown()


@pytest.mark.parametrize('mutation', ['version','locale','utf8','format'])
def test_pack_validation_keeps_active_translation(qt_app, tmp_path, mutation):
    language = LanguageController(SettingsController(path=False), root=tmp_path)
    try:
        language.selectLanguage('en-US')
        before = language.snapshot()
        pack = dict(formatVersion=1,locale='en-US',name='English',messages={})
        if mutation == 'version': pack['formatVersion'] = True
        if mutation == 'locale': pack['locale'] = '../bad'
        if mutation == 'utf8': pack['messages']['text.0539'] = '\ud800'
        if mutation == 'format': pack['messages']['sidebar.selected'] = '{count:.2f} selected'
        (tmp_path/'en-US.json').write_text(json.dumps(pack))
        assert not language.reload()
        assert language.locale == 'en-US' and language.snapshot() == before
    finally: language.shutdown()


def test_manual_images_and_language_resources_are_packaged():
    import runpy
    from qt_dicom_viewer.ui.controller.manual_tab_controller import manual_content
    qrc = Path('Voxenra.qrc').read_text()
    assets = Path('src/qt_dicom_viewer/qml/assets')
    packaged = {Path(source).resolve() for source, _ in runpy.run_path('packaging/hooks/hook-qt_dicom_viewer.py')['datas']}
    for locale in bundled_locales():
        path = assets/'languages'/(locale+'.json')
        assert path.as_posix() in qrc and path.resolve() in packaged
    for category in manual_content()['categories']:
        path = assets/'help'/category['file']
        assert path.is_file() and path.as_posix() in qrc and path.resolve() in packaged
    for locale in ('zh-CN','en-US'):
        for chapter in manual_content()['chapters']:
            for name in ([chapter['example']] if chapter.get('example') else chapter.get('examples', [])):
                path = assets/'help'/('en' if locale=='en-US' else '')/name
                assert path.is_file() and path.as_posix() in qrc and path.resolve() in packaged


def test_app_confirmation_and_buttons_switch_while_open(qt_app, tmp_path):
    from PySide6.QtCore import QTimer
    from qt_dicom_viewer.i18n.widgets import QMessageBox
    language = LanguageController(SettingsController(path=False), root=tmp_path)
    language.selectLanguage('en-US')
    checks = []
    def inspect_dialog():
        dialog = qt_app.activeModalWidget()
        checks.append(dialog.text() == localize(message('text.0418')))
        checks.append(dialog.button(QMessageBox.StandardButton.Cancel).text() == 'Cancel')
        language.selectLanguage('zh-CN')
        checks.append(dialog.text() == localize(message('text.0418')))
        checks.append(dialog.button(QMessageBox.StandardButton.Cancel).text() == '取消')
        dialog.button(QMessageBox.StandardButton.Cancel).click()
    try:
        QTimer.singleShot(30, inspect_dialog)
        answer = QMessageBox.question(None, message('text.0417'), message('text.0418'),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel)
        assert answer == QMessageBox.StandardButton.Cancel and checks == [True]*4
    finally: language.shutdown()


def test_sidebar_fallback_labels_retranslate_without_rebuilding_rows(sidebar_scene, tmp_path):
    from dataclasses import replace
    from qt_dicom_viewer.model import DicomFolderScanSnapshot
    from test_tag_qml import descendants
    window, app, records, warnings = sidebar_scene
    panel = app.panelController
    record = replace(records[0], study_date='', study_time='123045', series_description='')
    panel._update_series_record(DicomFolderScanSnapshot(tmp_path, 3, 3, 0, [record]))
    panel.selectSeries(record.series_instance_uid)
    QTest.qWait(50)
    model = panel.sidebarModel
    keys = [model.keyAt(i) for i in range(model.rowCount())]
    resets = []
    model.modelReset.connect(lambda:resets.append(True))
    for locale, date, description in [('en-US','Unknown date','[No description]'), ('zh-CN','日期未知','[无描述]')]:
        app.languageController.selectLanguage(locale)
        QTest.qWait(50)
        labels = [str(item.property('text')) for item in descendants(window.contentItem()) if item.isVisible() and item.property('text')]
        assert date + ' 12:30:45' in labels and description in labels, labels
        assert [model.keyAt(i) for i in range(model.rowCount())] == keys
        assert panel.activeSeriesUid == record.series_instance_uid
        assert not resets
    assert not warnings, warnings


@pytest.mark.parametrize('kind', ['2d', 'mpr', 'compare2d'])
def test_corner_labels_stay_english_and_old_orientation_pack_cannot_override(sidebar_scene, kind, tmp_path):
    window, app, records, warnings = sidebar_scene
    language = app.languageController
    language.root.mkdir(exist_ok=True)
    # Existing exported language packs can contain the former built-in labels.
    pack = dict(formatVersion=1, locale='zh-CN', name='简体中文', messages={
        'viewport.dicomOverlay': 'DICOM 叠加层',
        'overlay.patient': '患者：', 'overlay.slice': '切片：',
        'text.0532': '打开自定义影像',
    })
    path = language.root / 'zh-CN.json'
    path.write_text(json.dumps(pack, ensure_ascii=False))
    original = path.read_bytes()
    assert language.reload()
    assert language.messages['text.0532'] == '打开自定义影像'
    ws = app.workspaceController
    if kind == 'compare2d':
        ws.createCompareTab(*(r.series_instance_uid for r in records[:2]))
    else:
        ws.createTab(records[0].series_instance_uid, '示例', kind)
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    click(window, find(window, 'primaryTool-viewport-settings'))
    from test_tag_qml import descendants
    expected = None
    for locale in ('zh-CN', 'en-US', 'zh-CN'):
        language.selectLanguage(locale)
        QTest.qWait(70)
        assert find(window, 'viewportSetting-dicom-overlay').property('text') == (
            '方向标记' if locale == 'zh-CN' else 'Orientation markers')
        def visible_overlays():
            return [i for i in descendants(window.contentItem())
                    if i.objectName() == 'viewportMetadataOverlay' and i.isVisible()]
        # The active slice can finish before the other MPR planes on Windows.
        wait_until(lambda: len(visible_overlays()) == {'2d': 1, 'mpr': 3, 'compare2d': 2}[kind])
        overlays = visible_overlays()
        texts = tuple(tuple(o.findChild(QObject, 'overlay-' + corner).property('text')
                            for corner in ('topLeft', 'topRight', 'bottomLeft', 'bottomRight')) for o in overlays)
        assert all('Slice: ' in text[0] and 'Patient: ' in text[1] and 'Thickness: ' in text[2]
                   for text in texts)
        assert records[0].patient_name in texts[0][1]
        if expected is None: expected = texts
        else: assert texts == expected
    assert path.read_bytes() == original  # No user translation files are overwritten.
    assert window.grabWindow().save(str(tmp_path / ('english-corners-' + kind + '.png')))
    assert not warnings, warnings
