pragma ComponentBehavior: Bound
import QtQuick
MouseArea {
    id: root
    property string seriesUid: ""
    required property var panelController
    property point pressPoint
    property bool draggingSeries: false
    property int pressGeneration: 0
    property bool internalFinished: false
    onPressed: mouse => {
        ++pressGeneration
        internalFinished = false
        pressPoint = Qt.point(mouse.x, mouse.y)
        draggingSeries = false
        marker.seriesUid = seriesUid
    }
    preventStealing: draggingSeries
    Item {
        id: marker
        property string seriesUid: ""
        Drag.source: marker
        Drag.keys: ["application/x-voxenra-series"]
        Drag.supportedActions: Qt.CopyAction
    }
    onReleased: mouse => {
        ++pressGeneration
        if (marker.Drag.active) {
            marker.x = mouse.x
            marker.y = mouse.y
            marker.Drag.drop()
        }
        draggingSeries = false
    }
    onCanceled: { ++pressGeneration; marker.Drag.cancel(); draggingSeries = false }
    onPositionChanged: mouse => {
        if (!draggingSeries && seriesUid !== "" && (pressedButtons & Qt.LeftButton)
                && Math.abs(mouse.x - pressPoint.x) + Math.abs(mouse.y - pressPoint.y) >= Qt.styleHints.startDragDistance) {
            draggingSeries = true
        }
        if (!draggingSeries || internalFinished || !(mouse.buttons & Qt.LeftButton)) return
        const scenePoint = root.mapToItem(null, mouse.x, mouse.y)
        const window = root.Window.window
        if (window && (scenePoint.x < 0 || scenePoint.x >= window.width
                || scenePoint.y < 0 || scenePoint.y >= window.height
                || panelController.dragOverOtherWindow(window, root.mapToGlobal(mouse.x, mouse.y)))) {
            marker.Drag.cancel()
            internalFinished = true
            const uid = marker.seriesUid
            const generation = pressGeneration
            Qt.callLater(() => {
                if (root.pressGeneration === generation && root.draggingSeries
                        && root.enabled && root.visible && (root.pressedButtons & Qt.LeftButton)
                        && root.seriesUid === uid)
                    root.panelController.startSeriesDrag(uid)
            })
        } else {
            marker.x = mouse.x
            marker.y = mouse.y
            if (!marker.Drag.active) marker.Drag.start(Qt.CopyAction)
        }
    }
    Shortcut {
        sequence: "Escape"
        enabled: marker.Drag.active
        onActivated: {
            marker.Drag.cancel()
            root.internalFinished = true
        }
    }
}
