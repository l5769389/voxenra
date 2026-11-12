"""Display/export settings remain usable at narrow widths and across themes."""
from pathlib import Path
import time
import pytest
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtQml import QQmlEngine, QQmlExpression
from test_dicom_tags import qt_app, wait_until
from test_pacs_qml import scene
from test_tag_qml import find as find_control, click, descendants, settled_point
from qt_pointer import activate_window, move_pointer


def find(window, name):
    # Preset category changes can briefly expose the outgoing Loader's controls.
    # Keep this stability wait local: modal tests arm callbacks before clicks.
    current = None
    stable_since = 0.0
    def stable():
        nonlocal current, stable_since
        item = find_control(window, name)
        if item is not current:
            current, stable_since = item, time.monotonic()
        return time.monotonic() - stable_since >= .05
    wait_until(stable)
    return current


def open_combo(window, control):
    activate_window(window)
    move_pointer(window, settled_point(control))
    click(window, control)
    wait_until(lambda: QQmlExpression(QQmlEngine.contextForObject(control), control, "popup.opened").evaluate()[0])


@pytest.mark.parametrize('locale', ['zh-CN', 'en-US'])
@pytest.mark.parametrize('width', [1000, 1280, 1800])
def test_initial_window_values_and_responsive_order(scene, locale, width, tmp_path):
    from test_settings_redesign import reveal_setting
    window, app, warnings = scene
    settings = app.settingsController
    app.languageController.selectLanguage(locale)
    window.resize(width, 900)
    if width == 1000:
        # The native window has a minimum width; also exercise a narrow content
        # area by widening its independently resizable settings navigation.
        settings.setValue('layout', 'settingsNavigationWidth', 300)
    app.workspaceController.openSettings()
    settings.selectCategory('initialDisplay')
    mode = find(window, 'setting-initialDisplay-windowMode')
    reveal_setting(window, mode)
    open_combo(window, mode)
    QTest.keyClick(window, Qt.Key_End)
    QTest.keyClick(window, Qt.Key_Return)
    assert settings.section('initialDisplay')['windowMode'] == 'preset'
    selector = find(window, 'setting-initialDisplay-ctPreset')
    templates = [p for p in settings.windowTemplates if p['enabled']]
    index = next(i for i, p in enumerate(templates, 1) if p['presetId'] == 'ct-lung')
    reveal_setting(window, selector)
    open_combo(window, selector)
    wait_until(lambda: QQmlExpression(QQmlEngine.contextForObject(selector), selector, "popup.opened").evaluate()[0])
    QTest.keyClick(window, Qt.Key_Home)
    for _ in range(index):
        QTest.keyClick(window, Qt.Key_Down)
    QTest.keyClick(window, Qt.Key_Return)
    assert settings.section('initialDisplay')['ctPreset'] == 'ct-lung'
    selected = next(p for p in templates if p['presetId'] == 'ct-lung')
    summary = find(window, 'initialWindowValues-ctPreset')
    assert str(int(selected['width'])) in summary.property('text')
    assert str(int(selected['center'])) in summary.property('text')
    assert 'WW' in summary.property('text') and 'WL' in summary.property('text')
    assert settings.saveWindowTemplate('ct-lung', selected['label'], 1555.5, -602.25)
    wait_until(lambda: '1555.5' in summary.property('text') and '-602.25' in summary.property('text'))
    # The opened list exposes exact values too; selected field keeps the name readable.
    assert '1555.5' in selector.property('currentText')
    assert selector.property('displayText') == selected['label']
    for kind, category, control in [('initialDisplay', 'initialDisplay', 'setting-initialDisplay-zoom'),
                                    ('screenshot', 'export', 'screenshot-option-scope'),
                                    ('report', 'report', 'reportOption_orientation')]:
        settings.selectCategory(category)
        field = find(window, control)
        preview = find(window, 'presetPreview-' + kind)
        wait_until(lambda: preview.property('ready'))
        reveal_setting(window, field)
        a = field.mapToScene(QPointF())
        b = preview.mapToScene(QPointF())
        if width == 1000:
            assert a.y() < b.y()
        else:
            assert a.x() + field.width() <= b.x()
        QTest.qWait(120)
        assert window.grabWindow().save(str(tmp_path / f'{category}-{locale}-{width}.png'))
        if kind == 'report':
            image = find(window, 'presetPreviewImage-report')
            assert image.property('paintedWidth') == pytest.approx(image.width(), abs=1)
            scroll = find(window, 'presetPreviewScroll-report').property('contentItem')
            bottom = scroll.property('contentHeight') - scroll.height()
            assert bottom > 0
            scroll.setProperty('contentY', bottom)
            assert scroll.property('contentY') > 0
            preview.setProperty('pageIndex', 1)
            assert scroll.property('contentY') == 0
    assert not warnings, warnings


@pytest.mark.parametrize('theme', ['dark','graphite','light'])
@pytest.mark.parametrize('width', [1000,1440])
def test_preset_settings_render_and_change_only_defaults(scene, theme, width, tmp_path):
    window, app, warnings = scene
    window.resize(width,800)
    app.settingsController.setValue('appearance','theme',theme)
    app.workspaceController.openSettings()
    app.settingsController.selectCategory('initialDisplay')
    combo=find(window,'setting-initialDisplay-zoom')
    from test_settings_redesign import reveal_setting
    reveal_setting(window,combo)
    open_combo(window,combo);QTest.keyClick(window,Qt.Key_End);QTest.keyClick(window,Qt.Key_Return)
    assert app.settingsController.section('initialDisplay')['zoom']=='pixel'
    app.settingsController.selectCategory('export')
    QTest.qWait(80)
    for category,name in [('export','screenshotPresetName'),('report','reportPresetName'),('report','reportOption_orientation'),('report','reportOption_softwareName')]:
        app.settingsController.selectCategory(category)
        QTest.qWait(80)
        item=find(window,name)
        left=item.mapToScene(QPointF(0,0)).x();right=item.mapToScene(QPointF(item.width(),0)).x()
        assert item.width()>0 and 0<=left<right<=window.width(), (name,left,right,width)
    assert window.grabWindow().save(str(tmp_path/f'presets-{theme}-{width}.png'))
    assert not warnings,warnings

@pytest.mark.parametrize('theme', ['dark','graphite','light'])
@pytest.mark.parametrize('width', [1280,1800])
def test_live_previews_render_refresh_and_fit(scene, theme, width, tmp_path):
    from test_settings_redesign import reveal_setting
    window,app,warnings=scene
    window.resize(width,900)
    app.settingsController.setValue('appearance','theme',theme)
    app.workspaceController.openSettings()
    for kind,category in [('initialDisplay','initialDisplay'),('screenshot','export'),('report','report')]:
        app.settingsController.selectCategory(category)
        preview=find(window,'presetPreview-'+kind)
        wait_until(lambda: find(window,'settingsNavigation').width()==144)
        image=find(window,'presetPreviewImage-'+kind)
        reveal_setting(window,preview)
        wait_until(lambda: preview.property('ready') and image.width()>50 and image.height()>50)
        before=image.property('source').toString()
        if kind=='initialDisplay':app.settingsController.setValue('initialDisplay','zoom','pixel')
        elif kind=='screenshot':app.settingsController.setExportOptions('screenshot',{'scope':'tab','anonymous':False,'measurements':False})
        else:app.settingsController.setExportOptions('report',{'orientation':'landscape','imageColumns':2})
        wait_until(lambda: image.property('source').toString()!=before and preview.property('ready'))
        left=preview.mapToScene(QPointF()).x()
        if width==1800: assert preview.width()>900
        assert 0<=left and left+preview.width()<=window.width()+1
        QTest.qWait(150)
        if kind == 'report':
            # Fit the page width rather than shrinking it to fit the whole height.
            assert image.property('paintedWidth') == pytest.approx(image.width(), abs=1)
        assert window.grabWindow().save(str(tmp_path/f'{kind}-{theme}-{width}.png'))
        assert not preview.property('controller').property('error')
        enlarge=find(window,'presetPreviewEnlarge-'+kind)
        reveal_setting(window,enlarge)
        click(window,enlarge)
        dialog=preview.findChild(QObject,'presetPreviewDialog-'+kind)
        assert dialog is not None
        wait_until(lambda: dialog.property('visible'))
        assert window.grabWindow().save(str(tmp_path/f'{kind}-enlarged-{theme}-{width}.png'))
        QTest.keyClick(window,Qt.Key_Escape)
        wait_until(lambda: not dialog.property('visible'))
    assert not warnings,warnings


def test_familiar_screenshot_sizes_keep_existing_storage(scene, tmp_path):
    from test_settings_redesign import reveal_setting
    from test_tag_qml import type_text
    window,app,warnings=scene
    app.workspaceController.openSettings();app.settingsController.selectCategory('export')
    combo=find(window,'screenshot-output-size')
    for index,edge in [(1,1920),(2,2560),(3,3840)]:
        reveal_setting(window,combo);open_combo(window,combo)
        QTest.keyClick(window,Qt.Key_Home)
        for _ in range(index):QTest.keyClick(window,Qt.Key_Down)
        QTest.keyClick(window,Qt.Key_Return)
        options=app.settingsController.section('screenshot')
        assert options['size']=='longEdge' and options['longEdge']==edge
    reveal_setting(window,combo);open_combo(window,combo)
    QTest.keyClick(window,Qt.Key_End);QTest.keyClick(window,Qt.Key_Return)
    field=find(window,'screenshot-option-longEdge');reveal_setting(window,field)
    assert field.isVisible()
    type_text(window,field,'4096')
    assert field.property('text')=='4096'
    QTest.keyClick(window,Qt.Key_Tab)
    wait_until(lambda: app.settingsController.section('screenshot')['longEdge']==4096)
    type_text(window,field,'9999');QTest.keyClick(window,Qt.Key_Tab)
    assert app.settingsController.section('screenshot')['longEdge']==4096
    assert field.property('text')=='4096'
    assert not warnings,warnings


def test_separate_export_pages_reset_only_their_own_defaults(scene):
    from test_settings_redesign import reveal_setting
    window,app,warnings=scene
    settings=app.settingsController
    app.workspaceController.openSettings()
    settings.setExportOptions('screenshot',{'format':'jpeg'})
    settings.setExportOptions('report',{'orientation':'landscape'})
    settings.selectCategory('export')
    reset=find(window,'resetDisplaySettings');click(window,reset)
    click(window,find(window,'confirmSettingsReset'))
    assert settings.section('screenshot')['format']=='png'
    assert settings.section('report')['orientation']=='landscape'
    settings.setExportOptions('screenshot',{'format':'jpeg'})
    settings.selectCategory('report')
    reset=find(window,'resetDisplaySettings');click(window,reset)
    click(window,find(window,'confirmSettingsReset'))
    assert settings.section('report')['orientation']=='portrait'
    assert settings.section('screenshot')['format']=='jpeg'
    shared=find(window,'reportSharedDirectory');reveal_setting(window,shared);click(window,shared)
    wait_until(lambda: settings.activeCategory=='export')
    assert find(window,'exportDirectoryField').width()>0
    assert not warnings,warnings


@pytest.mark.parametrize('locale,query', [('zh-CN','科室'),('en-US','Department')])
def test_report_fields_remain_searchable_after_page_split(scene,locale,query):
    window,app,warnings=scene
    app.languageController.selectLanguage(locale)
    app.workspaceController.openSettings()
    from PySide6.QtGui import QInputMethodEvent, QGuiApplication
    search=find(window,'settingsSearch');search.forceActiveFocus()
    event=QInputMethodEvent();event.setCommitString(query)
    QGuiApplication.sendEvent(search,event)
    page=find(window,'settingsPage')
    wait_until(lambda: page.property('searchMatchCount')==1)
    # Navigation matching must identify the report page, not the former combined page.
    # Use the stable navigation object name for activation.
    report=find(window,'settingsCategory-report')
    click(window,report)
    assert app.settingsController.activeCategory=='report'
    assert find(window,'reportOption_department').width()>0
    assert not warnings,warnings


@pytest.mark.parametrize('kind,category', [('screenshot','export'),('report','report')])
def test_preset_picker_only_appears_after_saving_and_hides_after_last_delete(scene,kind,category):
    from test_settings_redesign import reveal_setting
    from test_tag_qml import type_text
    window,app,warnings=scene
    app.workspaceController.openSettings()
    settings=app.settingsController;settings.selectCategory(category)
    find(window,kind+'PresetName')
    # Hidden items remain instantiated, so inspect their actual visibility too.
    def item(name):
        return next(i for i in descendants(window.contentItem()) if i.objectName()==kind+name)
    chooser=item('PresetPicker');delete=item('DeletePreset')
    name=item('PresetName');save=item('SavePreset')
    assert not chooser.isVisible() and not delete.isVisible()
    assert name.isVisible() and save.isVisible() and not save.isEnabled()
    options=settings.section(kind)
    for label in ['First','Second']:
        reveal_setting(window,name);type_text(window,name,label)
        reveal_setting(window,save)
        click(window,save)
        wait_until(lambda: chooser.isVisible() and chooser.property('currentText')==label)
        assert name.property('text')==''
        assert not save.isEnabled()
        assert settings.section(kind)==options
    reveal_setting(window,chooser);open_combo(window,chooser)
    QTest.keyClick(window,Qt.Key_Home);QTest.keyClick(window,Qt.Key_Down);QTest.keyClick(window,Qt.Key_Return)
    assert chooser.property('currentText')=='First'
    click(window,delete)
    assert chooser.isVisible() and not delete.isEnabled()
    open_combo(window,chooser);QTest.keyClick(window,Qt.Key_End);QTest.keyClick(window,Qt.Key_Return)
    assert chooser.property('currentText')=='Second'
    click(window,delete)
    wait_until(lambda: not chooser.isVisible() and not delete.isVisible())
    assert name.isVisible() and save.isVisible()
    assert settings.section(kind)==options
    assert not warnings,warnings
