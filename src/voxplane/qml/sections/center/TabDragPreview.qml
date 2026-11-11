import QtQuick
import QtQuick.Window
import "../../theme"

Window {
    id: preview
    required property var manager
    required property string sourceWindowId
    visible: !!manager && manager.dragging && manager.dragSource === sourceWindowId
    flags: Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
    color: "transparent"
    width: 200
    height: 38
    x: (manager?.dragX ?? 0) + 12
    y: (manager?.dragY ?? 0) + 12
    Rectangle {
        anchors.fill: parent
        radius: 6
        color: Theme.selectionBackground
        border.width: 1
        border.color: Theme.selectionBorder
        Text {
            anchors.fill: parent
            anchors.margins: 10
            text: preview.manager?.dragLabel ?? ""
            color: Theme.textPrimary
            font.pixelSize: 12
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
    }
}
