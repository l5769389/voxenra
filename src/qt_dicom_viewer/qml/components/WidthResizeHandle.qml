import QtQuick
import "../theme"

MouseArea {
    id: handle
    property real currentWidth: 0
    property real minimumWidth: 0
    property real maximumWidth: 1000
    property real direction: 1
    property bool verticalDrag: false
    property bool showGrip: false
    property real pressCoordinate: 0
    function coordinate(mouse) {
        const p = mapToItem(null, mouse.x, mouse.y)
        return verticalDrag ? p.y : p.x
    }
    property real pressWidth: 0
    property real candidateWidth: currentWidth
    signal widthDragged(real value)
    signal widthCommitted(real value)
    implicitWidth: 8
    hoverEnabled: true
    cursorShape: verticalDrag ? Qt.SizeVerCursor : Qt.SizeHorCursor
    preventStealing: true
    onPressed: mouse => {
        pressCoordinate = coordinate(mouse)
        pressWidth = currentWidth
        candidateWidth = currentWidth
    }
    onPositionChanged: mouse => {
        if (!pressed) return
        candidateWidth = Math.max(minimumWidth, Math.min(maximumWidth,
            pressWidth + direction * (coordinate(mouse) - pressCoordinate)))
        widthDragged(candidateWidth)
    }
    onReleased: widthCommitted(candidateWidth)
    onCanceled: widthCommitted(candidateWidth)
    Rectangle {
        anchors.centerIn: parent
        width: handle.verticalDrag ? parent.width : 1
        height: handle.verticalDrag ? 1 : parent.height
        opacity: handle.showGrip && !handle.containsMouse && !handle.pressed ? 0.45 : 1
        color: handle.containsMouse || handle.pressed ? Theme.primaryColor : Theme.dividerColor
    }
    Rectangle {
        objectName: "resizeGrip"
        visible: handle.showGrip && (handle.containsMouse || handle.pressed)
        anchors.centerIn: parent
        width: handle.verticalDrag ? 28 : 3
        height: handle.verticalDrag ? 3 : 28
        radius: 2
        color: Theme.primaryColor
    }
}
