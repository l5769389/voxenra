"""Follow the visible More entry when a primary tool is in the secondary group."""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtGui import QGuiApplication


def reveal_primary_tool(root, name):
    if not name.startswith('primaryTool-'):
        return
    def items(node):
        for child in node.childItems():
            yield child
            yield from items(child)
    all_items = list(items(root))
    target = next((i for i in all_items if i.objectName() == name), None)
    if target is None or target.isVisible():
        return
    more = next((i for i in all_items if i.objectName() == 'primaryToolsMore' and i.isVisible()), None)
    if more is not None:
        position = more.mapToScene(QPointF(more.width()/2, more.height()/2)).toPoint()
        top = root
        while top.parentItem() is not None:
            top = top.parentItem()
        window = next(w for w in QGuiApplication.allWindows() if w.contentItem() == top)
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, position)
        QTest.qWait(40)
