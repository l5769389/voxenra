from pathlib import Path
from test_series_sidebar import sidebar_scene
from test_dicom_tags import qt_app,wait_until
from test_workspace_persistence import draw_length
from test_tag_qml import find
from test_two_d_selector import choose
from PySide6.QtTest import QTest


def test_created_plane_measurement_visible_in_list(sidebar_scene):
    window,app,records,warnings=sidebar_scene
    window.resize(1280,800)
    app.settingsController.setValue("layout", "rightPanelWidth", 220)
    ws=app.workspaceController
    ws.createTab(records[0].series_instance_uid,'CT','2d')
    wait_until(lambda:ws.activeLoadState.status=='ready')
    tab=ws.activeTab
    find(window,'twoDPlane-0')
    draw_length(tab.activeViewport)
    tab.toolController.activateTool('measure')
    QTest.qWait(50)
    assert '(1)' in find(window,'measurementResultsToggle').property('text')
    choose(window,0,'coronal')
    wait_until(lambda:tab.activeViewport.loadState=='ready')
    draw_length(tab.activeViewport)
    QTest.qWait(50)
    assert len(tab.measurementResults.items)==2
    window.grabWindow().save(str(Path('build/p0-review/fixed-list.png').resolve()))
    assert '(2)' in find(window,'measurementResultsToggle').property('text')
