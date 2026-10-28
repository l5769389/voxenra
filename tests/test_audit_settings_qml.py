"""User-visible audit regressions: safe resets, discoverable navigation, tool labels."""
from copy import deepcopy
import os
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_settings_redesign import reveal_setting
from test_pet_fusion import paired_series
from test_tag_qml import click, find, descendants


def capture(window, name, tmp_path):
    root = Path(os.environ.get('VOXENRA_AUDIT_CAPTURES', tmp_path))
    root.mkdir(parents=True, exist_ok=True)
    assert window.grabWindow().save(str(root / (name + '.png')))


@pytest.mark.parametrize('locale', ['zh-CN', 'en-US'])
def test_window_reset_requires_confirmation_and_explains_deleted_presets(sidebar_scene, locale, tmp_path):
    window, app, records, warnings = sidebar_scene
    settings = app.settingsController
    app.languageController.selectLanguage(locale)
    settings.saveWindowTemplate('', 'Custom A', 900, 100)
    settings.saveWindowTemplate('', 'Custom B', 1200, 50)
    settings.setValue('measurement', 'fontSize', 18)
    before = deepcopy(settings.values)
    app.workspaceController.openSettings()
    settings.selectCategory('window')
    click(window, find(window, 'resetDisplaySettings'))
    assert settings.values == before, 'Opening reset must not change settings or erase presets'
    message = find(window, 'settingsResetImpact').property('text')
    assert '2' in message
    assert ('自定义' if locale == 'zh-CN' else 'custom') in message
    capture(window, 'reset-' + locale, tmp_path)
    click(window, find(window, 'cancelSettingsReset'))
    assert settings.values == before
    click(window, find(window, 'resetDisplaySettings'))
    click(window, find(window, 'confirmSettingsReset'))
    assert settings.values['window']['custom'] == []
    assert settings.values['measurement']['fontSize'] == 18
    restored = SettingsController(path=settings._path)
    assert restored.values['window']['custom'] == []
    assert restored.values['measurement']['fontSize'] == 18
    assert not warnings, warnings


def test_settings_navigation_exposes_scroll_and_reaches_last_category(sidebar_scene):
    window, app, records, warnings = sidebar_scene
    window.resize(1280, 720)
    app.languageController.selectLanguage('en-US')
    app.workspaceController.openSettings()
    app.settingsController.selectCategory('appearance')
    entry = find(window, 'settingsCategory-appearance')
    assert entry.width() >= 100
    assert entry.property('contentItem').property('lineCount') <= 2
    bar = find(window, 'settingsNavigationScrollBar')
    assert bar.isVisible() and bar.property('size') < 1 and bar.property('active')
    track = bar.mapToScene(QPointF(bar.width() / 2, bar.height() - 3)).toPoint()
    for _ in range(4):
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, track)
        QTest.qWait(30)
    entry = find(window, 'settingsCategory-ai')
    nav = find(window, 'settingsCategoryScroll')
    point = entry.mapToItem(nav, QPointF(entry.width() / 2, entry.height() / 2))
    assert 0 <= point.y() <= nav.height()
    click(window, entry)
    assert app.settingsController.activeCategory == 'ai'
    assert not warnings, warnings


@pytest.mark.parametrize('theme,locale', [('dark', 'zh-CN'), ('graphite', 'en-US'), ('light', 'zh-CN'), ('dark', 'pt-BR')])
def test_optional_tool_labels_update_live_and_preserve_tool_actions(sidebar_scene, theme, locale, tmp_path):
    window, app, records, warnings = sidebar_scene
    window.resize(1600, 900)
    settings = app.settingsController
    settings.setValue('appearance', 'theme', theme)
    settings.setValue('appearance', 'toolLabels', False)
    app.languageController.selectLanguage(locale)
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'Labels CT', '2d')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    tab = ws.activeTab
    primary = find(window, 'primaryTool-window')
    labels = lambda: [i for i in descendants(primary) if i.objectName() == 'toolbarLabel']
    assert labels() and not labels()[0].isVisible()
    app.workspaceController.openSettings()
    settings.selectCategory('appearance')
    toggle = find(window, 'setting-appearance-toolLabels')
    assert not toggle.property('checked')
    reveal_setting(window, toggle)
    click(window, toggle)
    assert SettingsController(path=settings._path).values['appearance']['toolLabels'] is True
    click(window, find(window, 'workspaceTab-' + tab.tab_config.tab_id))
    for width in (240, 300, 420):
        settings.setValue('layout', 'rightPanelWidth', width)
        QTest.qWait(80)
        for name in ('window', 'scroll', 'pan', 'zoom', 'measure'):
            button = find(window, 'primaryTool-' + name)
            label = next(i for i in descendants(button) if i.objectName() == 'toolbarLabel')
            assert label.isVisible() and label.property('text')
            assert not label.property('truncated'), (width, name, label.property('text'))
            point = label.mapToItem(button, QPointF(0, 0))
            assert point.y() >= 0 and point.y() + label.height() <= button.height() + .5
        click(window, find(window, 'primaryTool-measure'))
        assert tab.toolController.activeTool == 'measure'
        measure = find(window, 'measureEntry-length')
        assert any(i.objectName() == 'toolActionLabel' and i.isVisible() for i in descendants(measure))
        for item in descendants(find(window, 'rightPanel')):
            if item.objectName() == 'toolActionLabel' and item.isVisible():
                assert not item.property('truncated'), (width, item.property('text'))
        capture(window, f'labels-{theme}-{locale}-{width}', tmp_path)
    click(window, find(window, 'toggleRightPanel'))
    compact = find(window, 'compactTool-window')
    assert any(i.objectName() == 'toolbarLabel' and i.isVisible() for i in descendants(compact))
    click(window, find(window, 'compactTool-measure'))
    for item in descendants(find(window, 'compactToolRail')):
        if item.objectName() == 'toolbarLabel' and item.isVisible():
            assert not item.property('truncated'), item.property('text')
    capture(window, f'labels-compact-{theme}-{locale}', tmp_path)
    settings.setValue('appearance', 'toolLabels', False)
    QTest.qWait(50)
    assert not any(i.objectName() == 'toolbarLabel' and i.isVisible() for i in descendants(compact))
    assert not warnings, warnings


@pytest.mark.parametrize('key', ['toolLabels', 'sidebarLabels'])
def test_tool_label_preference_rejects_non_boolean_values(qt_app, key):
    settings = SettingsController(path=False)
    assert not settings.setValue('appearance', key, 'false')
    assert settings.setValue('appearance', key, True)
    assert not settings.setValue('appearance', key, 0)
    assert settings.values['appearance'][key] is True


@pytest.mark.parametrize('locale', ['zh-CN', 'en-US'])
def test_sidebar_and_right_labels_are_independent_and_persist(sidebar_scene, locale, tmp_path):
    window, app, records, warnings = sidebar_scene
    window.resize(1600, 900)
    app.languageController.selectLanguage(locale)
    settings, ws = app.settingsController, app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'Independent labels', '2d')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    tab_id = ws.activeTab.tab_config.tab_id
    sidebar_names = ['sidebarOpenFolder', 'sidebarPacs', 'openView-2d', 'openView-mpr',
                     'openView-3d', 'openView-montage', 'openView-4d', 'openView-tag', 'openView-fusion']

    def label_for(name):
        return next(item for item in descendants(find(window, name)) if item.objectName() == 'toolbarLabel')

    assert label_for('sidebarOpenFolder').isVisible()
    assert label_for('primaryTool-window').isVisible()
    ws.openSettings()
    settings.selectCategory('appearance')
    left = find(window, 'setting-appearance-sidebarLabels')
    right = find(window, 'setting-appearance-toolLabels')
    assert left.property('checked') and right.property('checked')
    language = find(window, 'settingsGroup-appearance-language')
    labels = find(window, 'settingsGroup-appearance-tools')
    assert labels.mapToScene(QPointF()).y() > language.mapToScene(QPointF()).y() + language.height()
    reveal_setting(window, left)
    capture(window, f'button-label-settings-{locale}', tmp_path)

    for key, left_on, right_on in [('sidebarLabels', False, True), ('toolLabels', False, False),
                                   ('sidebarLabels', True, False), ('toolLabels', True, True)]:
        ws.openSettings()
        toggle = find(window, 'setting-appearance-' + key)
        reveal_setting(window, toggle)
        click(window, toggle)
        stored = SettingsController(path=settings._path).section('appearance')
        assert stored['sidebarLabels'] is left_on and stored['toolLabels'] is right_on
        click(window, find(window, 'workspaceTab-' + tab_id))
        QTest.qWait(40)
        assert all(label_for(name).isVisible() == left_on for name in sidebar_names)
        assert label_for('primaryTool-window').isVisible() == right_on
        if left_on:
            for width in (200, 300, 350):
                find(window, 'sidebarContainer').setProperty('expandedWidth', width)
                QTest.qWait(40)
                for name in sidebar_names:
                    label, button = label_for(name), find(window, name)
                    assert label.property('text') and not label.property('truncated'), (width, name)
                    point = label.mapToItem(button, QPointF())
                    assert point.y() >= 0 and point.y() + label.height() <= button.height() + .5
            capture(window, f'independent-labels-{locale}-{right_on}', tmp_path)
            click(window, find(window, 'sidebarToggle'))
            assert label_for('compactSidebarImport').isVisible()
            assert label_for('compactSidebarPacs').isVisible()
            capture(window, f'left-labels-compact-{locale}-{right_on}', tmp_path)
            click(window, find(window, 'sidebarToggle'))
    settings.setValue('appearance', 'sidebarLabels', True)
    settings.setValue('appearance', 'toolLabels', True)
    settings.resetSection('appearance')
    QTest.qWait(40)
    assert label_for('sidebarOpenFolder').isVisible()
    assert label_for('primaryTool-window').isVisible()
    assert not warnings, warnings


@pytest.mark.parametrize('locale', ['zh-CN', 'en-US'])
def test_window_button_name_follows_display_editor(sidebar_scene, paired_series, locale, tmp_path):
    from qt_dicom_viewer.model import DicomFolderScanSnapshot
    from PySide6.QtGui import QAccessible
    from test_ct_perfusion import perfusion, save_and_scan
    window, app, _, warnings = sidebar_scene
    window.resize(1600, 900)
    app.languageController.selectLanguage(locale)
    app.settingsController.setValue('appearance', 'toolLabels', True)
    _, ct, pet = paired_series
    _, scan = save_and_scan(tmp_path, perfusion())
    scalar = scan.series[0]
    records = [ct, pet, scalar]
    snapshot = DicomFolderScanSnapshot(tmp_path, 0, 0, 0, records)
    app.panelController.update_series_session(snapshot)
    app.panelController._update_series_record(snapshot)
    expected = {'zh-CN': [('调窗', '窗宽／窗位'), ('强度', 'PET 强度'), ('映射', '显示映射')],
                'en-US': [('W/L', 'Window / level'), ('Range', 'PET intensity'), ('Map', 'Display mapping')]}
    for record, (short, full) in zip(records, expected[locale]):
        ws = app.workspaceController
        ws.createTab(record.series_instance_uid, 'Contextual label', '2d')
        wait_until(lambda: ws.activeLoadState.status == 'ready')
        for name in ['primaryTool-window', 'compactTool-window']:
            if name.startswith('compact'):
                click(window, find(window, 'toggleRightPanel'))
            button = find(window, name)
            label = next(i for i in descendants(button) if i.objectName() == 'toolbarLabel')
            QTest.qWait(40)
            assert label.isVisible() and label.property('text') == short
            assert not label.property('truncated')
            assert QAccessible.queryAccessibleInterface(button).text(QAccessible.Name) == full
            click(window, button)
            assert ws.activeTab.toolController.activeTool == 'window'
        capture(window, f'tool-name-{record.modality}-{ws.activeViewport.displayMappingEditor}-{locale}', tmp_path)
        click(window, find(window, 'toggleRightPanel'))
    assert not warnings, warnings


@pytest.mark.parametrize('locale', ['zh-CN', 'en-US'])
def test_short_labels_fit_secondary_tools_at_minimum_width(sidebar_scene, locale):
    window, app, records, warnings = sidebar_scene
    app.languageController.selectLanguage(locale)
    settings = app.settingsController
    settings.setValue('appearance', 'toolLabels', True)
    settings.setValue('layout', 'rightPanelWidth', 240)
    ws = app.workspaceController
    for tab_type, tools in [('2d', ['measure', 'rotate', 'annotate', 'service']),
                            ('mpr', ['segmentation', 'voi'])]:
        ws.createTab(records[0].series_instance_uid, tab_type, tab_type)
        wait_until(lambda: ws.activeLoadState.status == 'ready')
        for tool in tools:
            ws.activeTab.toolController.activateTool(tool)
            QTest.qWait(50)
            for item in descendants(find(window, 'rightPanel')):
                if item.objectName() == 'toolActionLabel' and item.isVisible():
                    assert not item.property('truncated'), (locale, tool, item.property('text'))
    assert not warnings, warnings


def test_window_template_keyboard_save_is_atomic_and_escape_discards(sidebar_scene):
    from test_tag_qml import type_text
    window, app, records, warnings = sidebar_scene
    app.workspaceController.openSettings()
    app.settingsController.selectCategory('window')
    field = find(window, 'windowTemplateWidth')
    # Bring the bottom editor into view in this long settings page.
    scroll = find(window, 'displaySettingsScroll').property('contentItem')
    scroll.setProperty('contentY', max(0, scroll.property('contentHeight') - scroll.height()))
    type_text(window, find(window, 'windowTemplateName'), 'Keyboard template')
    type_text(window, field, '800')
    type_text(window, find(window, 'windowTemplateCenter'), '60')
    assert not app.settingsController.values['window']['custom']
    QTest.keyClick(window, Qt.Key_Return)
    assert len(app.settingsController.values['window']['custom']) == 1
    saved = deepcopy(app.settingsController.values['window']['custom'])
    type_text(window, find(window, 'windowTemplateWidth'), '1500')
    QTest.keyClick(window, Qt.Key_Escape)
    assert field.property('text') == '400'
    assert app.settingsController.values['window']['custom'] == saved
    assert not warnings, warnings


def test_pacs_timeout_enter_saves_form_and_escape_discards(sidebar_scene):
    from test_tag_qml import type_text
    window, app, records, warnings = sidebar_scene
    app.workspaceController.openSettings()
    app.settingsController.selectCategory('sources')
    click(window, find(window, 'pacsAddProfile'))
    type_text(window, find(window, 'pacsProfileName'), 'Keyboard PACS')
    type_text(window, find(window, 'pacsProfileUrl'), 'http://127.0.0.1:8042/dicom-web')
    type_text(window, find(window, 'pacsProfileTimeout'), '30')
    assert not app.pacsController.profiles
    QTest.keyClick(window, Qt.Key_Return)
    assert len(app.pacsController.profiles) == 1
    assert app.pacsController.profiles[0]['timeout'] == 30
    click(window, find(window, 'pacsAddProfile'))
    type_text(window, find(window, 'pacsProfileTimeout'), '60')
    QTest.keyClick(window, Qt.Key_Escape)
    assert len(app.pacsController.profiles) == 1
    assert not any(i.objectName() == 'pacsProfileTimeout' and i.isVisible() for i in descendants(window.contentItem()))
    assert not warnings, warnings
