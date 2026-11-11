pragma ComponentBehavior: Bound
import QtQuick
import "../../../theme"

Item {
    id: frame
    required property bool active
    property bool hovered: false
    // Reserve the same space in every state so selection never resizes images.
    readonly property int contentInset: 5

    Rectangle {
        anchors.fill: parent
        color: "transparent"
        border.width: 1
        border.color: Theme.canvasBackground
    }
    Rectangle {
        objectName: "viewportSelectionBorder"
        anchors.fill: parent
        anchors.margins: 1
        color: "transparent"
        border.width: frame.active ? 2 : 1
        border.color: frame.active ? Theme.viewportActiveBorder
            : frame.hovered ? Theme.viewportHoverBorder : Theme.viewportBorder
    }
    Rectangle {
        anchors.fill: parent
        anchors.margins: 4
        color: "transparent"
        border.width: 1
        border.color: Theme.canvasBackground
    }
}
