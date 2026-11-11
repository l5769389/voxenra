"""Native tool cursors keep their logical size on standard desktop DPI scales."""
import pytest
from PySide6.QtCore import QPoint, QSizeF, Qt
from voxplane.ui.cursors import tool_cursor, CURSOR_KINDS
from test_dicom_tags import qt_app


@pytest.mark.parametrize("kind", sorted(CURSOR_KINDS))
@pytest.mark.parametrize("ratio", [1.0, 1.25, 1.5, 2.0])
def test_native_tool_cursor_density_and_hotspot(qt_app, kind, ratio):
    cursor = tool_cursor(kind, ratio)
    assert cursor.shape() == Qt.BitmapCursor
    assert cursor.hotSpot() == QPoint(2, 2)
    pixmap = cursor.pixmap()
    assert pixmap.deviceIndependentSize() == QSizeF(40, 32)
    assert pixmap.devicePixelRatio() == ratio
    image = pixmap.toImage()
    assert image.pixelColor(0, 0).alpha() == 0
    assert any(image.pixelColor(x, y).alpha() > 0
               for y in range(image.height()) for x in range(image.width()))


@pytest.mark.parametrize("kind", ["volume-crop", "crosshair-rotate"])
def test_cursor_badge_uses_same_geometry_as_toolbar_icon(kind):
    from pathlib import Path
    import xml.etree.ElementTree as ET
    assets = Path(__file__).resolve().parents[1] / "src/voxplane/qml/assets"
    icon = ET.parse(assets / "icons" / (kind + ".svg")).getroot()
    cursor = ET.parse(assets / "cursors" / (kind + ".svg")).getroot()
    namespace = {"s": "http://www.w3.org/2000/svg"}
    expected = {p.attrib["d"] for p in icon.findall("s:path", namespace)}
    badge = cursor.find("s:g", namespace)
    assert {p.attrib["d"] for p in badge} == expected
    # The badge is separate from the arrow; the pointer tip remains the hotspot.
    assert cursor.find("s:path", namespace).attrib["d"].startswith("M2 2")
