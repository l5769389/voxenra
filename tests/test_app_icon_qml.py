"""统一 SVG 图标在实际工具栏尺寸下加载、切换与状态着色。"""

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QImage
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from shiboken6 import delete

from test_measurement_qml import qt_app


def test_tool_svgs_render_and_recolor_when_icon_name_changes(qt_app):
    qml = Path(__file__).resolve().parents[1] / "src/voxplane/qml"
    names = ["fusion", "measure", "service", "mtf", "info",
             "remove-bed", "segmentation", "voi", "qa", "mip",
             "tab-detach", "tab-return", "tab-close-others", "tab-close-right", "tab-close-all"]
    view = QQuickView()
    from voxplane.ui.svg_icon_provider import SvgIconProvider
    view.engine().addImageProvider("navigation", SvgIconProvider())
    warnings = []
    view.engine().warnings.connect(
        lambda errors: warnings.extend(error.toString() for error in errors)
    )
    view.setColor(QColor("#07131c"))
    view.setInitialProperties({"iconName": names[0], "iconSize": 22})
    view.setSource(QUrl.fromLocalFile(str(qml / "components/AppIcon.qml")))
    assert view.status() == QQuickView.Ready
    view.show()
    try:
        for name in names:
            root = view.rootObject()
            root.setProperty("iconName", name)
            assert root.property("isSvgIcon")
            for color in [QColor("#b8c3cf"), QColor("#00cfff")]:
                root.setProperty("iconColor", color)
                QTest.qWait(120)
                frame = view.grabWindow()
                assert not frame.isNull()
                # 验证真实像素，而不仅是 QML 属性：图形非空且已跟随颜色变化。
                matching = sum(
                    abs(frame.pixelColor(x, y).red() - color.red()) < 30
                    and abs(frame.pixelColor(x, y).green() - color.green()) < 30
                    and abs(frame.pixelColor(x, y).blue() - color.blue()) < 30
                    for x in range(frame.width()) for y in range(frame.height())
                )
                assert matching >= 8, (name, color.name(), matching)
        assert not warnings, warnings
        # 高 DPI 画布的可视窗口必须覆盖完整图形，不能只显示放大后的左上角。
        root.setProperty("iconName", "window")
        root.setProperty("iconColor", QColor("#00cfff"))
        QTest.qWait(120)
        circle = view.grabWindow()
        for x_half in range(2):
            for y_half in range(2):
                cyan = sum(
                    circle.pixelColor(x, y).blue() > 140
                    and circle.pixelColor(x, y).green() > 110
                    and circle.pixelColor(x, y).red() < 70
                    for x in range(x_half * circle.width() // 2,
                                   (x_half + 1) * circle.width() // 2)
                    for y in range(y_half * circle.height() // 2,
                                   (y_half + 1) * circle.height() // 2)
                )
                assert cyan > 2, (x_half, y_half, cyan)
    finally:
        view.hide()
        delete(view)
