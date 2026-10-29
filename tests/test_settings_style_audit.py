"""Regressions for settings findings from the October style review."""
from copy import deepcopy

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtTest import QTest

from test_dicom_tags import qt_app, wait_until
from test_pacs_qml import scene
from test_tag_qml import find, click
from test_settings_redesign import open_page, reveal_setting, find_any


def test_toolbar_draft_survives_category_switch_until_save_or_cancel(scene):
    window, app, warnings = open_page(scene, 'toolbar')
    settings = app.settingsController
    editor = find(window, 'toolbarSettingsPage').property('editor')
    original = deepcopy(editor.commonTools)
    assert editor.moveTool('common', 0, 1)
    draft = deepcopy(editor.commonTools)
    assert draft != original
    for category in ('appearance', 'window', 'toolbar'):
        settings.selectCategory(category)
        QTest.qWait(40)
    reopened = find(window, 'toolbarSettingsPage').property('editor')
    assert reopened == editor and reopened.dirty and reopened.commonTools == draft
    click(window, find(window, 'toolbarCancel'))
    assert not editor.dirty and editor.commonTools == original
    editor.moveTool('common', 0, 1)
    click(window, find(window, 'toolbarSave'))
    settings.selectCategory('appearance')
    settings.selectCategory('toolbar')
    assert find(window, 'toolbarSettingsPage').property('editor').commonTools == draft
    assert not editor.dirty
    assert not warnings, warnings


def test_crosshair_collapse_migrates_legacy_and_remains_independent(scene):
    window, app, warnings = open_page(scene, 'appearance')
    settings = app.settingsController
    settings.setValue('layout', 'settingsCollapsedGroups', ['crosshair-style', 'appearance-theme'])
    settings.selectCategory('crosshair')
    axial = find(window, 'settingsGroup-crosshair-style-axial')
    groups = settings.values['layout']['settingsCollapsedGroups']
    assert 'crosshair-style' not in groups
    assert all('crosshair-style-' + plane in groups for plane in ('axial', 'coronal', 'sagittal'))
    click(window, axial)
    groups = settings.values['layout']['settingsCollapsedGroups']
    assert 'crosshair-style-axial' not in groups
    assert 'crosshair-style-coronal' in groups and 'crosshair-style-sagittal' in groups
    assert 'appearance-theme' in groups
    settings.selectCategory('appearance')
    settings.selectCategory('crosshair')
    assert find(window, 'setting-crosshair-axialWidth').isVisible()
    assert not find_any(window, 'setting-crosshair-coronalWidth').isVisible()
    assert not warnings, warnings


@pytest.mark.parametrize('locale,query', [('zh-CN', '界面大小'), ('en-US', 'Interface size'), ('pt-BR', 'Tamanho da interface'), ('en-US', 'scaling')])
def test_search_matches_control_labels_and_aliases_and_shows_empty_state(scene, locale, query):
    window, app, warnings = open_page(scene, 'appearance')
    app.languageController.selectLanguage(locale)
    search = find(window, 'settingsSearch')
    search.setProperty('text', query)
    QTest.qWait(60)
    assert find(window, 'settingsCategory-appearance').isVisible()
    search.setProperty('text', 'no-setting-matches-98765')
    assert find(window, 'settingsSearchNoResults').isVisible()
    assert find(window, 'settingsSearchNoResults').property('text') != 'settings.searchNoResults'
    search.setProperty('text', '  ')
    assert find(window, 'settingsCategory-toolbar').isVisible()
    assert not find_any(window, 'settingsSearchNoResults').isVisible()
    assert not warnings, warnings


def test_window_template_edit_reveals_expands_and_focuses_form(scene):
    window, app, warnings = open_page(scene, 'window')
    settings = app.settingsController
    for i in range(18):
        assert settings.saveWindowTemplate('', f'Custom {i}', 800 + i, 50 + i)
    QTest.qWait(80)
    custom = next(p for p in settings.windowTemplates if p['label'] == 'Custom 0')
    editor_header = find(window, 'settingsGroup-window-template-editor')
    reveal_setting(window, editor_header)
    click(window, editor_header)
    assert not find_any(window, 'windowTemplateName').isVisible()
    edit = find(window, 'windowEdit-' + custom['presetId'])
    reveal_setting(window, edit)
    click(window, edit)
    name = find(window, 'windowTemplateName')
    wait_until(lambda: name.hasActiveFocus())
    scroll = find(window, 'displaySettingsScroll').property('contentItem')
    top = name.mapToItem(scroll, QPointF()).y()
    assert 0 <= top and top + name.height() <= scroll.height()
    assert name.property('text') == 'Custom 0'
    assert find(window, 'windowTemplateWidth').property('text') == '800'
    assert find(window, 'windowTemplateCenter').property('text') == '50'
    assert not warnings, warnings
