"""Settings help stays attached to its heading, including narrow localized forms."""
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtTest import QTest

from test_dicom_tags import qt_app, wait_until
from test_pacs_qml import scene
from test_settings_redesign import open_page, find_any
from test_tag_qml import click, find


@pytest.mark.parametrize('locale', ['zh-CN', 'en-US'])
@pytest.mark.parametrize('width', [1280, 1440])
def test_workspace_help_belongs_to_header_and_does_not_collapse(scene, locale, width):
    scene[1].languageController.selectLanguage(locale)
    window, app, warnings = open_page(scene, 'workspace', width)
    heading = find_any(window, 'settingsGroup-workspace-exit')
    help_button = find_any(window, 'workspaceExitDescription')
    combo = find_any(window, 'workspaceExitBehavior')
    center = lambda item: item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
    assert abs(center(heading).y() - center(help_button).y()) <= 1
    assert center(help_button).y() < combo.mapToScene(QPointF()).y()
    assert heading.mapToScene(QPointF(heading.width(), 0)).x() <= help_button.mapToScene(QPointF()).x()
    original = help_button.property('explanation')
    app.settingsController.setValue('workspace', 'exitBehavior', 'discard')
    QTest.qWait(30)
    assert help_button.property('explanation') != original
    click(window, help_button)
    assert combo.isVisible()
    assert 'workspace-exit' not in app.settingsController.values['layout']['settingsCollapsedGroups']
    assert not warnings, warnings


@pytest.mark.parametrize('theme', ['dark', 'graphite', 'light'])
@pytest.mark.parametrize('locale', ['zh-CN', 'en-US'])
def test_all_settings_pages_keep_actions_inside_form(scene, theme, locale, tmp_path):
    from pathlib import Path
    import os
    from test_tag_qml import descendants
    from test_ui_polish import inside_width

    window, app, warnings = scene
    app.languageController.selectLanguage(locale)
    app.settingsController.setValue('appearance', 'theme', theme)
    app.workspaceController.openSettings()
    find(window, 'settingsPage')
    categories = ['appearance', 'input', 'privacy', 'workspace', 'updates', 'sources',
                  'export', 'colormap', 'window', 'crosshair', 'corners', 'scale',
                  'measurement', 'roi', 'services', 'ai']
    output = Path(os.environ.get('VOXENRA_LAYOUT_CAPTURES', tmp_path))
    output.mkdir(parents=True, exist_ok=True)
    for width, height in [(1280, 720), (1440, 900)]:
        window.resize(width, height)
        for category in categories:
            app.settingsController.selectCategory(category)
            QTest.qWait(40)
            page = find(window, 'settingsPage')
            if category != 'sources':
                form = find(window, 'settingsCategoryContent')
                wait_until(lambda: form.property('item') is not None)
            QTest.qWait(40)
            image = window.grabWindow()
            assert image.save(str(output / f'{theme}-{locale}-{width}-{category}.png'))
            for item in descendants(page):
                if not item.isVisible() or item.width() <= 0 or item.property('checkable') is None:
                    continue
                # Controls in combo popups are intentionally outside the form.
                if any(p.objectName() == 'settingsCategoryContent' for p in ancestors(item)):
                    form = find_any(window, 'settingsCategoryContent')
                    try:
                        inside_width(item, form)
                    except AssertionError as error:
                        raise AssertionError((theme, locale, width, category, str(error))) from error
            assert not warnings, (category, warnings)


def ancestors(item):
    while item.parentItem() is not None:
        item = item.parentItem()
        yield item


def test_english_window_headers_and_narrow_navigation_do_not_clip(scene):
    scene[1].languageController.selectLanguage('en-US')
    window, app, warnings = open_page(scene, 'window', 1280)
    app.settingsController.setValue('layout', 'settingsNavigationWidth', 156)
    QTest.qWait(40)
    assert not window.grabWindow().isNull()
    for name in ['windowHeaderWW', 'windowHeaderWL']:
        header = find(window, name)
        assert header.property('paintedWidth') <= header.width() + 0.5
        assert header.property('paintedHeight') <= header.height() + 0.5
    for category in ['appearance', 'input', 'measurement', 'updates']:
        text = find_any(window, 'settingsCategory-' + category).property('contentItem')
        assert not text.property('truncated'), category
        assert text.property('paintedHeight') <= text.height() + 0.5, (category, text.property('implicitHeight'), text.property('lineCount'), text.parentItem().height())
    assert not warnings, warnings
