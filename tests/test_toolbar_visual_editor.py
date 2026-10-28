"""Drag the real editor and verify exact draft/persisted placement, not only visuals."""
from copy import deepcopy
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, QUrl, Qt
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from shiboken6 import delete

from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
from test_dicom_tags import qt_app
from test_measurement_qml import _visual_children
from test_series_sidebar import sidebar_scene


def keys(items):
    return [item['toolType'] for item in items]


def test_atomic_placement_preserves_order_and_rejects_stale_or_full_drop(qt_app, tmp_path):
    settings = SettingsController(path=tmp_path / 'settings.json')
    editor = settings.createToolbarEditor(settings)
    assert hasattr(editor, 'placeEntry'), 'Drag placement must accept an insertion position'
    assert not editor.placeEntry('window', 'common', 'common', 1)
    assert not editor.dirty
    before = deepcopy(editor.commonTools)
    assert not editor.placeEntry('rotate', 'more', 'common', 0)
    assert editor.commonTools == before and not editor.dirty
    assert editor.placeEntry('play', 'common', 'more', 0)
    assert editor.placeEntry('rotate', 'more', 'common', 1)
    assert keys(editor.commonTools) == ['window', 'rotate', 'scroll', 'pan', 'zoom', 'measure', 'mpr-layout']
    snapshot = deepcopy((editor.commonTools, editor.moreTools))
    for args in [('rotate', 'more', 'common', 0), ('window', 'common', 'more', -1),
                 ('window', 'common', 'left', 0), ('window', 'bad', 'more', 0),
                 ('missing', 'common', 'more', 0), ('window', 'common', 'more', 1000)]:
        assert not editor.placeEntry(*args)
        assert (editor.commonTools, editor.moreTools) == snapshot
    assert editor.placeEntry('window', 'common', 'common', 7)
    assert keys(editor.commonTools)[-1] == 'window'
    assert editor.placeEntry('3d', 'left', 'left', 0)
    assert editor.save()
    restored = SettingsController(path=settings._path)
    assert restored.navigationViewOrder[:3] == ['3d', '2d', 'mpr']
    assert restored.section('toolbar')['rightProfiles']['2d:ct']['common'] == [
        'rotate', 'scroll', 'pan', 'zoom', 'measure', 'mpr-layout', 'window']


@pytest.fixture
def visual_editor(qt_app, tmp_path):
    settings = SettingsController(path=tmp_path / 'settings.json')
    window = QQuickView()
    window.engine().addImageProvider('navigation', SvgIconProvider())
    warnings = []
    window.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    window.setResizeMode(QQuickView.SizeRootObjectToView)
    window.setInitialProperties({'settingsController': settings})
    window.setSource(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] /
        'src/qt_dicom_viewer/qml/sections/settings/ToolbarSettingsPage.qml')))
    assert window.status() == QQuickView.Ready
    window.resize(940, 720)
    window.show()
    window.requestActivate()
    QTest.qWait(100)
    yield window, settings, window.rootObject().property('editor'), warnings
    window.close()
    delete(window)


def item(window, name):
    return next(i for i in _visual_children(window.rootObject()) if i.objectName() == name and i.isVisible())


def point(target, x=.5, y=.5):
    return target.mapToScene(QPointF(target.width() * x, target.height() * y)).toPoint()


def click(window, name):
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point(item(window, name)))
    QTest.qWait(30)


def drag(window, source, destination, *, release=True):
    start = point(item(window, source))
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
    for n in range(1, 13):
        QTest.mouseMove(window, start + (destination - start) * n / 12, 12)
    if release:
        QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, destination)
        QTest.qWait(50)


def test_tile_drag_reorders_and_cross_group_drop_inserts_at_pointer(visual_editor, tmp_path):
    window, settings, editor, warnings = visual_editor
    end = point(item(window, 'toolbarTile-common-pan'), .8)
    drag(window, 'toolbarTile-common-window', end, release=False)
    assert item(window, 'toolbarDragPreview').isVisible()
    assert item(window, 'toolbarInsertion-common').isVisible()
    assert keys(editor.commonTools)[:3] == ['window', 'scroll', 'pan']
    assert window.grabWindow().save(str(tmp_path / 'toolbar-dragging.png'))
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
    QTest.qWait(50)
    assert keys(editor.commonTools)[:3] == ['scroll', 'pan', 'window']
    drag(window, 'toolbarTile-common-play', point(item(window, 'toolbarTile-more-rotate'), .2))
    assert keys(editor.moreTools)[:2] == ['play', 'rotate']
    drag(window, 'toolbarTile-more-rotate', point(item(window, 'toolbarTile-common-pan'), .2))
    assert keys(editor.commonTools)[:4] == ['scroll', 'rotate', 'pan', 'window']
    assert settings.section('toolbar')['rightProfiles'] == {}
    click(window, 'toolbarSave')
    saved = SettingsController(path=settings._path).section('toolbar')['rightProfiles']['2d:ct']
    assert saved['common'][:4] == ['scroll', 'rotate', 'pan', 'window']
    assert saved['more'][0] == 'play'
    assert not warnings, warnings


def test_drag_cancel_outside_and_full_group_never_lose_tools(visual_editor):
    window, _, editor, warnings = visual_editor
    before = deepcopy((editor.commonTools, editor.moreTools))
    drag(window, 'toolbarTile-more-rotate', point(item(window, 'toolbarTile-common-window'), .2))
    assert (editor.commonTools, editor.moreTools) == before
    assert editor.message and not editor.dirty
    drag(window, 'toolbarTile-common-window', QPointF(2, 2).toPoint())
    assert (editor.commonTools, editor.moreTools) == before
    end = point(item(window, 'toolbarTile-common-pan'))
    drag(window, 'toolbarTile-common-window', end, release=False)
    QTest.keyClick(window, Qt.Key_Escape)
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
    QTest.qWait(40)
    assert (editor.commonTools, editor.moreTools) == before
    assert not editor.dirty
    assert not warnings, warnings


def test_empty_group_accepts_drop_and_keyboard_actions_keep_selection(visual_editor):
    window, settings, editor, warnings = visual_editor
    assert settings.setValue('toolbar', 'rightProfiles', {'2d:ct': {'common': [], 'more': ['window', 'scroll']}})
    QTest.qWait(30)
    drag(window, 'toolbarTile-more-window', point(item(window, 'toolbarList-common'), .5, .2))
    assert keys(editor.commonTools) == ['window']
    click(window, 'toolbarScopeLeft')
    click(window, 'toolbarTile-left-3d')
    QTest.keyClick(window, Qt.Key_Left, Qt.AltModifier)
    QTest.qWait(30)
    assert keys(editor.leftViews)[:3] == ['2d', '3d', 'mpr']
    # The newly rebuilt selection is still keyboard operable.
    QTest.keyClick(window, Qt.Key_Left, Qt.AltModifier)
    QTest.qWait(30)
    assert keys(editor.leftViews)[:3] == ['3d', '2d', 'mpr']
    click(window, 'toolbarCancel')
    assert keys(editor.leftViews)[:3] == ['2d', 'mpr', '3d']
    assert keys(editor.commonTools) == []
    assert not warnings, warnings


def test_drag_scrolls_to_last_row_and_drops_after_last_tool(visual_editor):
    window, _, editor, warnings = visual_editor
    window.resize(940, 500)
    QTest.qWait(60)
    scroll = item(window, 'toolbarList-more')
    assert scroll.property('contentHeight') > scroll.height()
    end = point(scroll, .98, .98)
    drag(window, 'toolbarTile-common-window', end, release=False)
    for _ in range(50):
        QTest.qWait(30)
        if scroll.property('contentY') >= scroll.property('contentHeight') - scroll.height() - 1:
            break
    assert scroll.property('contentY') > 0
    assert scroll.property('contentY') >= scroll.property('contentHeight') - scroll.height() - 1
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
    QTest.qWait(60)
    assert keys(editor.moreTools)[-1] == 'window'
    assert 'window' not in keys(editor.commonTools)
    assert not warnings, warnings


def test_tab_navigation_reveals_tools_below_scroll_view(visual_editor):
    window, _, editor, warnings = visual_editor
    window.resize(940, 500)
    QTest.qWait(50)
    click(window, 'toolbarTile-more-rotate')
    # Focus the first tile, then use actual Tab traversal through the remaining tools.
    item(window, 'toolbarTile-more-rotate').forceActiveFocus()
    for _ in range(len(editor.moreTools) - 1):
        QTest.keyClick(window, Qt.Key_Tab)
        QTest.qWait(15)
    last = item(window, 'toolbarTile-more-' + keys(editor.moreTools)[-1])
    assert last.hasActiveFocus()
    scroll = item(window, 'toolbarList-more')
    position = last.mapToItem(scroll, QPointF())
    assert position.y() >= 0
    assert position.y() + last.height() <= scroll.height() + 1
    assert not warnings, warnings


@pytest.mark.parametrize('locale', ['zh-CN', 'en-US', 'pt-BR'])
def test_narrow_editor_keeps_icon_buttons_and_save_controls_usable(visual_editor, locale):
    from qt_dicom_viewer.ui.controller.language_controller import LanguageController
    window, settings, _, warnings = visual_editor
    language = LanguageController(settings, root=False)
    language.attach_engine(window.engine())
    language.selectLanguage(locale)
    window.resize(390, 650)
    QTest.qWait(80)
    try:
        for name in ('toolbarTile-common-window', 'toolbarTile-more-rotate'):
            tile = item(window, name)
            assert tile.width() >= 60, 'The icon and label must fit without colliding with adjacent tiles'
        for name in ('toolbarSave', 'toolbarRestore', 'toolbarCancel', 'toolbarProfile', 'toolbarScopeRight'):
            control = item(window, name)
            origin = control.mapToScene(QPointF())
            assert origin.x() >= 0 and origin.y() >= 0
            assert origin.x() + control.width() <= window.width()
            assert origin.y() + control.height() <= window.height()
        assert not warnings, warnings
    finally:
        language.shutdown()


def test_keyboard_enters_selected_tool_actions_and_transfers_without_losing_focus(visual_editor):
    window, _, editor, warnings = visual_editor
    tile = item(window, 'toolbarTile-common-window')
    tile.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_Return)
    QTest.qWait(20)
    assert item(window, 'toolbarDown-common-window').hasActiveFocus()
    QTest.keyClick(window, Qt.Key_Tab)
    QTest.keyClick(window, Qt.Key_Space)
    QTest.qWait(40)
    assert keys(editor.moreTools)[-1] == 'window'
    assert item(window, 'toolbarGroup-more-window').hasActiveFocus()
    QTest.keyClick(window, Qt.Key_Space)
    QTest.qWait(40)
    assert keys(editor.commonTools)[-1] == 'window'
    assert not warnings, warnings


def test_keyboard_action_can_move_the_same_tool_repeatedly(visual_editor):
    window, _, editor, warnings = visual_editor
    item(window, 'toolbarTile-common-window').forceActiveFocus()
    QTest.keyClick(window, Qt.Key_Return)
    for _ in range(2):
        QTest.keyClick(window, Qt.Key_Space)
        QTest.qWait(30)
    assert keys(editor.commonTools)[:3] == ['scroll', 'pan', 'window']
    assert item(window, 'toolbarDown-common-window').hasActiveFocus()
    assert not warnings, warnings


def test_external_clean_draft_refresh_cancels_an_in_progress_drag(visual_editor):
    window, settings, editor, warnings = visual_editor
    end = point(item(window, 'toolbarTile-common-pan'), .8)
    drag(window, 'toolbarTile-common-window', end, release=False)
    assert settings.setValue('toolbar', 'rightProfiles', {'2d:ct': {'common': ['window', 'zoom'], 'more': ['pan']}})
    QTest.qWait(30)
    assert not window.rootObject().property('dragging')
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
    QTest.qWait(30)
    assert keys(editor.commonTools) == ['window', 'zoom']
    assert not editor.dirty
    assert not warnings, warnings


def test_short_narrow_editor_scrolls_groups_without_clipping_button_labels(visual_editor):
    window, _, editor, warnings = visual_editor
    window.resize(528, 502)
    QTest.qWait(60)
    for group in ('common', 'more'):
        assert item(window, 'toolbarList-' + group).height() >= 76
    scroll = item(window, 'toolbarBoardsScroll')
    assert scroll.property('contentHeight') > scroll.height()
    end = point(scroll, .95, .97)
    drag(window, 'toolbarTile-common-window', end, release=False)
    for _ in range(70):
        QTest.qWait(30)
        if scroll.property('contentY') >= scroll.property('contentHeight') - scroll.height() - 1:
            break
    assert scroll.property('contentY') >= scroll.property('contentHeight') - scroll.height() - 1
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
    QTest.qWait(40)
    assert keys(editor.moreTools)[-1] == 'window'
    for name in ('toolbarSave', 'toolbarCancel'):
        control = item(window, name)
        assert point(control, 1, 1).y() <= window.height()
    assert not warnings, warnings


def test_visual_toolbar_native_layout_themes_and_languages(sidebar_scene, tmp_path):
    from test_tag_qml import find, click as native_click
    window, app, _, warnings = sidebar_scene
    app.workspaceController.openSettings()
    app.settingsController.selectCategory('toolbar')
    window.resize(1280, 720)
    for theme, locale in [('dark', 'zh-CN'), ('light', 'en-US'), ('graphite', 'pt-BR')]:
        app.settingsController.setValue('appearance', 'theme', theme)
        app.languageController.selectLanguage(locale)
        QTest.qWait(100)
        for scope in ('Right', 'Left'):
            native_click(window, find(window, 'toolbarScope' + scope))
            scope_button = find(window, 'toolbarScope' + scope)
            assert not any(child.property('truncated') for child in _visual_children(scope_button)
                           if child.property('text') == scope_button.property('text'))
            native_click(window, find(window, 'toolbarTile-common-scroll' if scope == 'Right' else 'toolbarTile-left-mpr'))
            for name in ('toolbarSave', 'toolbarRestore', 'toolbarCancel'):
                control = find(window, name)
                origin = control.mapToScene(QPointF())
                assert origin.x() >= 0 and origin.y() >= 0
                assert origin.x() + control.width() <= window.width()
                assert origin.y() + control.height() <= window.height()
            assert window.grabWindow().save(str(tmp_path / f'toolbar-{theme}-{locale}-{scope}.png'))
    app.languageController.selectLanguage('zh-CN')
    window.setProperty('availableWindowWidth', 800)
    window.setProperty('availableWindowHeight', 600)
    window.resize(800, 600)
    native_click(window, find(window, 'toolbarScopeRight'))
    QTest.qWait(100)
    tile = find(window, 'toolbarTile-common-window')
    assert tile.width() >= 60
    scroll = find(window, 'toolbarList-common')
    assert scroll.height() >= tile.height()
    assert point(find(window, 'toolbarSave'), 1, 1).y() <= window.height()
    assert window.grabWindow().save(str(tmp_path / 'toolbar-small-800x600.png'))
    assert not warnings, warnings
