"""Grouped tools remain reachable while keeping the reading panel compact."""
from PySide6.QtCore import QPointF
from PySide6.QtTest import QTest
from test_series_sidebar import sidebar_scene
from test_tag_qml import find, click, descendants
from test_dicom_tags import qt_app, wait_until


def test_grouped_toolbar_more_and_width_stability(sidebar_scene, tmp_path):
    window, app, records, warnings = sidebar_scene
    ws = app.workspaceController
    ws.createTab(records[0].series_instance_uid, 'CT', '2d')
    wait_until(lambda: ws.activeLoadState.status == 'ready')
    panel = find(window, 'rightPanel')
    assert panel.width() == 300
    for theme, locale in [('dark','zh-CN'), ('light','en-US'), ('graphite','zh-CN')]:
        app.settingsController.setValue('appearance', 'theme', theme)
        app.languageController.selectLanguage(locale)
        for width in (240, 300, 420):
            app.settingsController.setValue('layout', 'rightPanelWidth', width)
            QTest.qWait(60)
            toolbar = find(window, 'primaryToolBar')
            assert toolbar.height() <= 110
            start_width = panel.width()
            for tool in ('window','pan','zoom','measure','service'):
                click(window, find(window, 'primaryTool-'+tool))
                assert ws.activeTab.toolController.activeTool == tool
                assert panel.width() == start_width
            more = find(window, 'primaryToolsMore')
            click(window, more)
            assert find(window, 'primaryTool-export').isVisible()
            assert window.grabWindow().save(str(tmp_path/f'{theme}-{width}-more.png'))
            click(window, more)
            assert not any(i.objectName() == 'primaryTool-export' and i.isVisible()
                           for i in descendants(window.contentItem()))
            click(window, more)
            click(window, find(window, 'primaryTool-export'))
            assert ws.activeTab.toolController.activeTool == 'export'
            assert toolbar.height() <= 110 and panel.width() == start_width
            for name in ('primaryTool-window','primaryTool-measure','primaryToolsMore'):
                item=find(window,name); pos=item.mapToScene(QPointF())
                assert pos.x() >= 0 and pos.x()+item.width() <= window.width()
            assert window.grabWindow().save(str(tmp_path/f'{theme}-{width}.png'))
    assert not warnings, warnings
