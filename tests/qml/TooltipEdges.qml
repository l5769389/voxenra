import QtQuick
import "../../src/voxplane/qml/components" as Components

Rectangle {
    width: 420
    height: 280
    color: "#121920"
    property alias anchorX: anchor.x
    property alias anchorY: anchor.y
    property alias placement: anchor.tooltipPlacement
    property alias tooltipText: anchor.tooltipText
    property alias actionEnabled: anchor.actionEnabled
    property int clicks: 0
    Components.ToolbarAction {
        id: anchor
        objectName: "edgeAction"
        x: 190
        y: 4
        width: 40
        height: 36
        label: "Window / Level"
        iconName: "window"
        buttonObjectName: "edgeButton"
        onTriggered: parent.clicks++
    }
}
