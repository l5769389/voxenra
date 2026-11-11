pragma ComponentBehavior: Bound
import QtQuick

Item {
    id: pinch
    objectName: "viewportPinchHandler"
    anchors.fill: parent
    required property var viewportController
    // Montage maps the gesture into the tile below its midpoint.
    property var anchorGeometry: null
    enabled: viewportController !== null && !Window.window?.shortcutPopupOpen

    function zoom(delta, position) {
        if (delta === 1 || !viewportController) return
        const geometry = anchorGeometry ? anchorGeometry(position)
            : { x: position.x, y: position.y, width: width, height: height }
        viewportController.pinchZoom(delta, geometry.x, geometry.y, geometry.width, geometry.height)
    }

    // Keep device routing explicit: the averaged touchscreen centroid may have
    // a null device even though its position is valid (Qt 6.11).
    PinchHandler {
        target: null
        acceptedDevices: PointerDevice.TouchScreen
        minimumPointCount: 2
        maximumPointCount: 2
        xAxis.enabled: false
        yAxis.enabled: false
        rotationAxis.enabled: false
        onScaleChanged: delta => pinch.zoom(delta, centroid.position)
        onActiveChanged: if (!active) persistentScale = 1
    }
    PinchHandler {
        target: null
        acceptedDevices: PointerDevice.TouchPad
        minimumPointCount: 2
        maximumPointCount: 2
        xAxis.enabled: false
        yAxis.enabled: false
        rotationAxis.enabled: false
        onScaleChanged: delta => {
            if (delta !== 1 && pinch.viewportController)
                pinch.zoom(delta, pinch.viewportController.pinchCursorPosition(pinch))
        }
        onActiveChanged: if (!active) persistentScale = 1
    }
}
