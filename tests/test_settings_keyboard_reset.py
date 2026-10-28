"""Settings keyboard navigation and explicit shortcut reset consent."""
from copy import deepcopy

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest

from qt_dicom_viewer.ui.controller.settings_controller import SettingsController
from test_dicom_tags import qt_app, wait_until
from test_series_sidebar import sidebar_scene
from test_settings_redesign import reveal_setting
from test_tag_qml import click, find


def fully_visible(item, scroll):
    position = item.mapToItem(scroll, QPointF())
    return position.y() >= -1 and position.y() + item.height() <= scroll.height() + 1


@pytest.fixture(autouse=True)
def all_controls_keyboard_navigation(qt_app):
    # Match macOS with Keyboard navigation enabled; restore the platform choice.
    hints = QGuiApplication.styleHints()
    previous = hints.tabFocusBehavior()
    hints.setTabFocusBehavior(Qt.TabFocusAllControls)
    try:
        yield
    finally:
        hints.setTabFocusBehavior(previous)


@pytest.mark.parametrize('theme,locale', [('dark', 'zh-CN'), ('graphite', 'en-US'), ('light', 'en-US')])
def test_navigation_reveals_keyboard_focus_and_external_selection(sidebar_scene, theme, locale, tmp_path):
    window, app, _, warnings = sidebar_scene
    app.settingsController.setValue('appearance', 'theme', theme)
    app.languageController.selectLanguage(locale)
    window.resize(1280, 720)
    app.workspaceController.openSettings()
    app.settingsController.selectCategory('appearance')
    first = find(window, 'settingsCategory-appearance')
    first.forceActiveFocus(Qt.TabFocusReason)
    for _ in range(16):
        QTest.keyClick(window, Qt.Key_Tab)
    last = find(window, 'settingsCategory-ai')
    scroll = find(window, 'settingsCategoryScroll')
    assert last.hasActiveFocus()
    wait_until(lambda: fully_visible(last, scroll))
    QTest.keyClick(window, Qt.Key_Space)
    assert app.settingsController.activeCategory == 'ai'
    assert window.grabWindow().save(str(tmp_path / 'keyboard-last-category.png'))
    for _ in range(16):
        QTest.keyClick(window, Qt.Key_Backtab)
    assert first.hasActiveFocus()
    wait_until(lambda: fully_visible(first, scroll))
    # A settings link may select a category while focus remains elsewhere.
    find(window, 'settingsSearch').forceActiveFocus()
    app.settingsController.selectCategory('services')
    selected = find(window, 'settingsCategory-services')
    wait_until(lambda: fully_visible(selected, scroll))
    window.resize(1150, 650)
    wait_until(lambda: fully_visible(selected, scroll))
    assert not warnings, warnings


@pytest.mark.parametrize('locale', ['zh-CN', 'en-US'])
def test_shortcut_reset_requires_confirmation_and_preserves_mouse_settings(sidebar_scene, locale, tmp_path):
    window, app, _, warnings = sidebar_scene
    app.languageController.selectLanguage(locale)
    settings = app.settingsController
    app.workspaceController.openSettings()
    settings.selectCategory('input')
    assert app.shortcutController.assign('window', 'F9')
    settings.setValue('input', 'reverseWheel', True)
    before = deepcopy(settings.values)
    reset = find(window, 'resetShortcuts')
    reveal_setting(window, reset)
    click(window, reset)
    assert settings.values == before
    assert window.property('shortcutPopupOpen')
    impact = find(window, 'settingsResetImpact').property('text')
    assert ('自定义' if locale == 'zh-CN' else 'custom') in impact
    assert window.grabWindow().save(str(tmp_path / 'shortcut-reset-confirmation.png'))
    click(window, find(window, 'cancelSettingsReset'))
    assert settings.values == before
    click(window, reset)
    QTest.keyClick(window, Qt.Key_Escape)
    assert settings.values == before
    click(window, reset)
    click(window, find(window, 'confirmSettingsReset'))
    assert app.shortcutController.hint('window') == 'W'
    assert settings.section('input') == before['input']
    restored = SettingsController(path=settings._path)
    assert restored.section('shortcuts') == settings.section('shortcuts')
    assert restored.section('input') == before['input']
    assert not warnings, warnings
