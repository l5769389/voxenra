"""Grouped choices retain exact profile identity and the owning window's context."""
from copy import deepcopy

import pytest
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt

from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from qt_dicom_viewer.ui.controller.tab.tool_controller import ToolController
from qt_dicom_viewer.model import TabType
from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_toolbar_visual_editor import visual_editor, item, click
from test_measurement_qml import _visual_children
from test_tag_qml import find
from test_pacs_qml import scene


def test_color_montage_edit_targets_its_runtime_profile_after_restart(qt_app, tmp_path):
    settings = SettingsController(path=tmp_path / 'settings.json')
    runtime = ToolController(tab_type=TabType.MONTAGE, modality='US', is_color=True)
    editor = settings.createToolbarEditor(settings)
    editor.selectProfile(runtime.toolbarProfile)
    assert editor.selectedProfile == 'montage:color'
    assert editor.selectedCategory == 'montage'
    assert editor.moveTool('common', 1, 0)
    assert editor.save()
    restored = SettingsController(path=settings._path)
    profiles = restored.section('toolbar')['rightProfiles']
    assert list(profiles) == ['montage:color']
    assert profiles['montage:color']['common'][0] == 'zoom'


def test_color_montage_opens_matching_editor_in_real_settings(scene, tmp_path):
    from test_color_dicom import scan_color
    from test_tag_qml import click as native_click
    window, app, warnings = scene
    _, _, snapshot = scan_color(tmp_path, frames=2)
    app.panelController.acceptPacsImport(snapshot)
    workspace = app.windowManager.mainWorkspace
    workspace.createTab(snapshot.series[0].series_instance_uid, 'Color montage', 'montage')
    wait_until(lambda: workspace.activeLoadState.status == 'ready')
    workspace.openSettings()
    app.settingsController.selectCategory('toolbar')
    editor = find(window, 'toolbarSettingsPage').property('editor')
    assert editor.selectedProfile == 'montage:color'
    native_click(window, find(window, 'toolbarTile-common-zoom'))
    native_click(window, find(window, 'toolbarUp-common-zoom'))
    native_click(window, find(window, 'toolbarSave'))
    profiles = app.settingsController.section('toolbar')['rightProfiles']
    assert list(profiles) == ['montage:color']
    assert profiles['montage:color']['common'][0] == 'zoom'
    assert not warnings, warnings


def test_grouped_choices_reach_every_profile_and_preserve_separate_saved_orders(qt_app, tmp_path):
    settings = SettingsController(path=tmp_path / 'settings.json')
    editor = settings.createToolbarEditor(settings)
    assert hasattr(editor, 'viewCategories'), 'The editor needs grouped view choices'
    reached = set()
    for category in editor.viewCategories:
        editor.selectCategory(category['key'])
        for mode in editor.modes:
            editor.selectMode(mode['key'])
            for capability in editor.capabilities:
                editor.selectCapability(capability['key'])
                reached.add(editor.selectedProfile)
                assert editor.moveTool('common', 0, 1)
    assert reached == {p['key'] for p in editor.profiles}
    assert len(reached) == 29
    assert editor.save()
    saved = SettingsController(path=settings._path).section('toolbar')['rightProfiles']
    assert len(saved) == 29
    editor.selectProfile('compare2d:color')
    editor.restoreCurrentDefault()
    assert editor.save()
    restored = SettingsController(path=settings._path).section('toolbar')['rightProfiles']
    assert restored == {k: v for k, v in saved.items() if k != 'compare2d:color'}


def test_category_navigation_retains_drafts_and_rejects_incompatible_options(qt_app):
    settings = SettingsController(path=False)
    editor = settings.createToolbarEditor(settings)
    editor.selectProfile('compare2d:mr')
    assert hasattr(editor, 'selectCategory')
    assert editor.moveTool('common', 0, 1)
    edited = deepcopy(editor.commonTools)
    editor.selectCategory('mpr')
    assert editor.selectedProfile == 'mpr:mr'
    editor.selectMode('comparempr')
    editor.selectCategory('fusion')
    assert editor.selectedProfile == 'petctfusion:pt'
    for method, value in [(editor.selectCapability, 'ct'), (editor.selectMode, 'compare2d'),
                          (editor.selectCategory, 'tag'), (editor.selectProfile, '3d:color')]:
        method(value)
        assert editor.selectedProfile == 'petctfusion:pt'
    editor.selectCategory('mpr')
    assert editor.selectedProfile == 'comparempr:mr'
    editor.selectCategory('2d')
    assert editor.selectedProfile == 'compare2d:mr'
    assert editor.commonTools == edited
    assert settings.section('toolbar')['rightProfiles'] == {}
    editor.cancel()
    assert not editor.dirty and editor.commonTools != edited


@pytest.mark.parametrize('mode,modality,color,want', [
    (TabType.TWO_D, 'CT', False, '2d:ct'),
    (TabType.COMPARE_2D, 'US', True, 'compare2d:color'),
    (TabType.MPR, 'MR', False, 'mpr:mr'),
    (TabType.THREE_D, 'PETCT3D', False, '3d:petct3d'),
    (TabType.PETCT_FUSION, 'PT', False, 'petctfusion:pt'),
])
def test_context_profile_uses_current_tool_capability(qt_app, mode, modality, color, want):
    tool = ToolController(tab_type=mode, modality=modality, is_color=color)
    assert hasattr(tool, 'toolbarProfile')
    assert tool.toolbarProfile == want


def test_settings_initializes_from_recent_image_and_does_not_reset_live_draft(sidebar_scene):
    from test_tab_windows import detached
    window, app, records, warnings = sidebar_scene
    session = app.windowManager.mainWorkspace
    assert hasattr(session, 'toolbarProfileForEditing')
    assert session.toolbarProfileForEditing() == ''
    app.workspaceController.createTab(records[0].series_instance_uid, 'Synthetic CT', 'mpr')
    wait_until(lambda: app.workspaceController.activeLoadState.status == 'ready')
    assert session.toolbarProfileForEditing() == 'mpr:ct'
    session.createTab(records[1].series_instance_uid, 'Other window CT', '2d')
    wait_until(lambda: session.activeLoadState.status == 'ready')
    other, _ = detached(app, session.activeTab)
    assert other.toolbarProfileForEditing() == '2d:ct'
    session.openSettings()
    app.settingsController.selectCategory('toolbar')
    wait_until(lambda: session.activeTabType == 'settings')
    QTest.qWait(120)
    page = find(window, 'toolbarSettingsPage')
    editor = page.property('editor')
    assert editor.selectedProfile == 'mpr:ct'
    editor.selectProfile('compare2d:mr')
    assert editor.moveTool('common', 0, 1)
    before = deepcopy(editor.commonTools)
    other.openManual('toolbar')
    QTest.qWait(100)
    assert session.toolbarProfileForEditing() == 'mpr:ct'
    assert other.toolbarProfileForEditing() == '2d:ct'
    assert find(window, 'toolbarSettingsPage').property('editor') is editor
    assert editor.selectedProfile == 'compare2d:mr'
    assert editor.commonTools == before
    assert not warnings, warnings


def test_language_switch_keeps_specific_profile_and_pending_order(visual_editor):
    from qt_dicom_viewer.ui.controller.language_controller import LanguageController
    window, settings, editor, warnings = visual_editor
    language = LanguageController(settings, root=False)
    language.attach_engine(window.engine())
    editor.selectProfile('compare2d:color')
    editor.moveTool('common', 0, 1)
    before = deepcopy(editor.commonTools)
    try:
        for locale, expected in [('en-US', '2D reading'), ('pt-BR', 'Leitura 2D'), ('zh-CN', '2D 阅片')]:
            language.selectLanguage(locale)
            QTest.qWait(50)
            assert item(window, 'toolbarProfile').property('displayText') == expected
            assert item(window, 'toolbarProfileSummary').property('text') == editor.selectedProfileLabel
            assert editor.selectedProfile == 'compare2d:color' and editor.dirty
            assert [x['toolType'] for x in editor.commonTools] == [x['toolType'] for x in before]
        assert not warnings, warnings
    finally:
        language.shutdown()


def choose(window, name, offset):
    control = item(window, name)
    control.forceActiveFocus()
    for _ in range(offset):
        QTest.keyClick(window, Qt.Key_Down)
    QTest.qWait(40)


def test_grouped_ui_shows_exact_target_and_saves_only_that_profile(visual_editor, tmp_path):
    window, settings, editor, warnings = visual_editor
    assert item(window, 'toolbarProfile').property('count') == 6
    assert not any(i.objectName() == 'toolbarMode' and i.isVisible()
                   for i in _visual_children(window.rootObject()))
    click(window, 'toolbarDetails')
    choose(window, 'toolbarMode', 1)
    choose(window, 'toolbarCapability', 1)
    assert editor.selectedProfile == 'compare2d:mr'
    QTest.keyClick(window, Qt.Key_Tab)
    assert item(window, 'toolbarTile-common-window').hasActiveFocus()
    QTest.keyClick(window, Qt.Key_Backtab)
    assert item(window, 'toolbarCapability').hasActiveFocus()
    click(window, 'toolbarTile-common-scroll')
    click(window, 'toolbarUp-common-scroll')
    click(window, 'toolbarDetails')
    assert item(window, 'toolbarProfileSummary').property('text') == editor.selectedProfileLabel
    click(window, 'toolbarSave')
    saved = SettingsController(path=settings._path).section('toolbar')['rightProfiles']
    assert list(saved) == ['compare2d:mr'] and saved['compare2d:mr']['common'][0] == 'scroll'
    click(window, 'toolbarDetails')
    window.resize(390, 600)
    QTest.qWait(80)
    for name in ('toolbarMode', 'toolbarCapability', 'toolbarSave'):
        control = item(window, name)
        assert control.mapToScene(control.boundingRect().bottomRight()).y() <= window.height()
    assert window.grabWindow().save(str(tmp_path / 'toolbar-categories-small.png'))
    assert not warnings, warnings


def test_expanded_settings_fit_small_application_window(sidebar_scene, tmp_path):
    from test_tag_qml import click as native_click
    from PySide6.QtCore import QPointF
    window, app, _, warnings = sidebar_scene
    app.windowManager.mainWorkspace.openSettings()
    app.settingsController.selectCategory('toolbar')
    window.setProperty('availableWindowWidth', 800)
    window.setProperty('availableWindowHeight', 600)
    window.resize(800, 600)
    QTest.qWait(100)
    native_click(window, find(window, 'toolbarDetails'))
    for locale in ('zh-CN', 'en-US', 'pt-BR'):
        app.languageController.selectLanguage(locale)
        QTest.qWait(60)
        for name in ('toolbarMode', 'toolbarCapability', 'toolbarSave', 'toolbarRestore'):
            control = find(window, name)
            top = control.mapToScene(QPointF())
            bottom = control.mapToScene(QPointF(control.width(), control.height()))
            assert top.x() >= 0 and top.y() >= 0
            assert bottom.x() <= window.width() and bottom.y() <= window.height()
        assert window.grabWindow().save(str(tmp_path / f'toolbar-details-{locale}.png'))
    assert not warnings, warnings
