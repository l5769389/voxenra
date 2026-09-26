from pathlib import Path
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from test_series_sidebar import sidebar_scene
from test_tag_qml import find, click
from test_dicom_tags import qt_app, wait_until
from test_workspace_persistence import draw_length


@pytest.mark.parametrize('locale,theme', [('zh-CN','dark'), ('en-US','dark'), ('zh-CN','light'), ('en-US','light')])
def test_result_list_actions_and_narrow_panel(sidebar_scene, locale, theme):
    window, app, records, warnings = sidebar_scene
    app.languageController.selectLanguage(locale)
    app.settingsController.setValue('appearance', 'theme', theme)
    app.settingsController.setValue('layout', 'rightPanelWidth', 220)
    window.resize(1000, 760)
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'CT', '2d')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    tab, view = ws.activeTab, ws.activeViewport
    mid = draw_length(view)
    tab.toolController.activateTool('measure')
    wait_until(lambda: find(window, 'measurementResultsToggle').isVisible())
    QTest.qWait(60)
    click(window, find(window, 'measurementLock-0'))
    assert view.measurementController.presentation(mid)['locked']
    click(window, find(window, 'measurementVisible-0'))
    assert not view.measurementController.measurementItems
    click(window, find(window, 'locateMeasurement-0'))
    assert view.measurementController.measurementItems
    assert view.measurementController.selectedMeasurementId == mid
    field = find(window, 'measurementName-0')
    click(window, field)
    QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier)
    for character in 'Reference':
        QTest.keyClick(window, character)
    QTest.keyClick(window, Qt.Key_Return)
    assert view.measurementController.presentation(mid)['name'] == 'Reference'
    for name in ('measurementName-0','measurementResultsToggle','locateMeasurement-0'):
        assert find(window, name).width() <= 220
    folder = Path('build/p0/ui'); folder.mkdir(parents=True, exist_ok=True)
    assert window.grabWindow().save(str(folder/f'measurements-{locale}-{theme}.png'))
    click(window, find(window, 'deleteMeasurement-0'))
    assert not tab.measurementResults.items
    assert not warnings, warnings
