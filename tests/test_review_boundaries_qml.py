"""Review regressions using real controllers and rendered controls."""
from pathlib import Path
import pytest
from PySide6.QtCore import QObject, QPointF, QUrl, Qt
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from shiboken6 import delete
from test_dicom_tags import qt_app, wait_until
from test_four_d_tools import temporal, draw
from test_tag_qml import find, click, type_text
from test_series_sidebar import sidebar_scene
from test_sidebar_style_polish import reveal, open_image
from test_window_sizing import fit_desktop


@pytest.mark.parametrize('field,key', [('voiDiameter', 'diameter'), ('voiDepth', 'depth')])
def test_voi_mm_input_is_independent_of_relative_brush(temporal, field, key, tmp_path):
    tab, _, _ = temporal
    draw(tab, 'voi')
    controller = tab.voiController
    controller.setBrushRelative(True)
    view = QQuickView()
    from qt_dicom_viewer.ui.svg_icon_provider import SvgIconProvider
    view.engine().addImageProvider("navigation", SvgIconProvider())
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(330, 900)
    warnings = []
    view.engine().warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    view.setInitialProperties(dict(controller=controller, mode='voi', tabController=tab))
    view.setSource(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] /
        'src/qt_dicom_viewer/qml/sections/right/panels/MprVoiPanel.qml')))
    assert view.status() == QQuickView.Ready
    view.show()
    QTest.qWait(80)
    try:
        number = find(view, field)
        type_text(view, number, '0.5')
        assert number.property('acceptableInput')
        QTest.keyClick(view, Qt.Key_Return)
        wait_until(lambda: controller.selected[key] == 0.5)
        assert view.grabWindow().save(str(tmp_path / (field + '.png')))
        assert not warnings, warnings
    finally:
        view.hide()
        delete(view)


def test_small_desktop_analysis_tools_remain_reachable(sidebar_scene, monkeypatch, tmp_path):
    window, app, records, warnings = sidebar_scene
    viewport = open_image(app, records[0])
    fit_desktop(window, app, monkeypatch, (800, 600))
    assert find(window, 'rightPanel').property('collapsed')
    assert not find(window, 'toggleRightPanel').isEnabled()
    rail = find(window, 'compactToolRail')
    reveal(window, rail, find(window, 'compactTool-service'))
    popup = window.findChild(QObject, 'compactVolumePanel')
    wait_until(lambda: popup.property('visible'))
    for name, action in [('serviceEntry-mtf', 'service:mtf'), ('serviceEntry-fwhm', 'service:fwhm')]:
        button = find(popup.findChild(QObject, 'servicePanel').window(), name)
        assert button is not None and button.isVisible()
        click(button.window(), button)
        assert app.workspaceController.activeTab.activeToolController.activeService == action
        assert viewport.activeInteraction == action
        position = button.mapToScene(QPointF())
        assert position.x() >= 0 and position.y() >= 0
        assert position.y() + button.height() <= button.window().height()
        assert button.window().grabWindow().save(str(tmp_path / (action.replace(':', '-') + '.png')))
    assert window.grabWindow().save(str(tmp_path / 'small-desktop.png'))
    assert not warnings, warnings
