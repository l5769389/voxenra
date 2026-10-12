import pytest
from PySide6.QtTest import QTest
from test_pacs_qml import scene
from test_dicom_tags import qt_app
from test_display_settings_qml import select_category
from test_tag_qml import find,click

def test_ai_and_services_have_separate_content(scene):
    from test_tag_qml import descendants
    window, app, warnings = scene
    app.workspaceController.openSettings()
    select_category(window, 'ai')
    find(window, 'autoSegDetect')
    assert not any(item.isVisible() and item.objectName() == 'setting-services-mtfFrequencyUnit'
                   for item in descendants(window.contentItem()))
    select_category(window, 'services')
    find(window, 'setting-services-mtfFrequencyUnit')
    assert not any(item.isVisible() and item.objectName() == 'autoSegDetect'
                   for item in descendants(window.contentItem()))
    assert not warnings, warnings

@pytest.mark.parametrize('language',['zh-CN','en-US'])
@pytest.mark.parametrize('theme',['dark','graphite','light'])
def test_local_environment_settings_load_in_minimum_window(scene,language,theme):
    window,app,warnings=scene
    app.settingsController.setValue('appearance','language',language)
    app.settingsController.setValue('appearance','theme',theme)
    app.workspaceController.openSettings()
    window.resize(1280,720)
    QTest.qWait(60)
    select_category(window,'ai')
    QTest.qWait(60)
    assert not warnings,warnings
    if language=='en-US':assert app.localSegmentationController.message=='Environment not checked'

@pytest.mark.parametrize('width',[240,300,420])
def test_dialog_search_selection_and_responsive_size(scene,width):
    from PySide6.QtCore import QUrl,QMetaObject
    from PySide6.QtQml import QQmlComponent
    from pathlib import Path
    window,app,warnings=scene
    c=app.localSegmentationController
    c._environment={'model_ready':True,'devices':['cpu'],'organs':['liver','spleen','kidney_left','kidney_right']}
    c._state='ready'
    c._checked_config=c._configuration()
    path=Path(__file__).resolve().parents[1]/'src/qt_dicom_viewer/qml/sections/right/panels/AutomaticSegmentationDialog.qml'
    from PySide6.QtQml import qmlEngine
    component=QQmlComponent(qmlEngine(window),QUrl.fromLocalFile(str(path)))
    assert component.isReady(), [e.toString() for e in component.errors()]
    dialog=component.createWithInitialProperties({'controller':c,'settingsController':app.settingsController})
    assert dialog
    dialog.setParent(window)
    dialog.setProperty("parent",window.contentItem())
    app.settingsController.setValue("layout","rightPanelWidth",width)
    window.resize(1280,720)
    QMetaObject.invokeMethod(dialog,'open')
    QTest.qWait(80)
    assert dialog.property('visible')
    assert dialog.property('width')<=window.width() and dialog.property('height')<=window.height()
    c.selectAll(False);assert not any(o['selected'] for o in c.organs)
    c.selectOrgan('liver',True);assert [o['id'] for o in c.organs if o['selected']]==['liver']
    QMetaObject.invokeMethod(dialog,'close');dialog.deleteLater()
    assert not warnings,warnings


def test_unsupported_target_error_is_not_replaced_by_automatic_probe(scene):
    from PySide6.QtCore import QUrl,QMetaObject
    from PySide6.QtQml import QQmlComponent,qmlEngine
    from pathlib import Path
    window,app,warnings=scene
    c=app.localSegmentationController
    assert not c.prepare(None)
    error=c.message
    path=Path(__file__).resolve().parents[1]/'src/qt_dicom_viewer/qml/sections/right/panels/AutomaticSegmentationDialog.qml'
    component=QQmlComponent(qmlEngine(window),QUrl.fromLocalFile(str(path)))
    dialog=component.createWithInitialProperties({'controller':c})
    dialog.setParent(window);dialog.setProperty('parent',window.contentItem())
    QMetaObject.invokeMethod(dialog,'open');QTest.qWait(20)
    assert c.state=='error' and c.message==error
    QMetaObject.invokeMethod(dialog,'close');dialog.deleteLater()


def test_settings_keep_unavailable_device_visible_and_advanced_reachable(scene):
    window,app,warnings=scene
    c=app.localSegmentationController
    app.settingsController.setValue('appearance','language','en-US')
    c._checked_config=c._configuration()
    c._environment={'model_ready':True,'devices':['cpu'],'organs':['liver'],'version':'2.19.0'}
    c._environment_state='ready'
    app.settingsController.setValue('services','segmentationDevice','gpu')
    app.workspaceController.openSettings();window.resize(1280,720)
    select_category(window,'ai');QTest.qWait(60)
    combo=find(window,'autoSegDevice')
    assert combo.property('currentText')=='CUDA · Unavailable'
    assert 'not tested' in c.compatibilityMessage
    click(window,find(window,'autoSegAdvanced'))
    button=find(window,'autoSegChoosePython')
    assert button.property('text')=='Choose Python interpreter'
    from PySide6.QtCore import QPointF
    point=button.mapToScene(QPointF())
    assert point.x()>=0 and point.x()+button.width()<=window.width()
    assert not warnings,warnings


def test_environment_refresh_keeps_explicit_device_selected(scene):
    window,app,warnings=scene
    c=app.localSegmentationController
    app.settingsController.setValue('services','segmentationDevice','mps')
    app.workspaceController.openSettings()
    select_category(window,'ai');QTest.qWait(60)
    combo=find(window,'autoSegDevice')
    assert combo.property('currentText').startswith('MPS')
    # A real background probe rebuilds the model and its display labels.
    c._checked_config=c._configuration()
    c._environment={'model_ready':True,'devices':['mps','cpu'],'organs':['liver'],'version':'2.18.0'}
    c._environment_state='ready';c.changed.emit();QTest.qWait(60)
    assert combo.property('currentText')=='MPS'
    assert app.settingsController.values['services']['segmentationDevice']=='mps'
    c.changed.emit();QTest.qWait(60)
    assert combo.property('currentText')=='MPS'
    app.settingsController.setValue('services','segmentationDevice','cpu')
    QTest.qWait(30)
    assert combo.property('currentText')=='CPU'
    app.settingsController.setValue('services','segmentationDevice','gpu')
    QTest.qWait(30)
    assert combo.property('currentText').startswith('CUDA · ')
    assert app.settingsController.values['services']['segmentationDevice']=='gpu'
    assert not warnings,warnings
