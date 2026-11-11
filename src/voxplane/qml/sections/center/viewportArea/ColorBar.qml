pragma ComponentBehavior: Bound

import QtQuick
import "../../../theme"

Item {
    id: colorBar
    objectName: "viewportColorBar"
    required property var stops
    required property real minimumValue
    required property real maximumValue

    function formatValue(value) {
        const precision = Math.abs(value) >= 100 ? 0 : Math.abs(value) >= 1 ? 1 : 3
        return Number(value).toFixed(precision)
    }

    width: 58
    height: Math.min(230, parent ? parent.height * 0.42 : 230)

    Canvas {
        id: colorRamp
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: 13

        function paintRamp() {
            requestPaint()
        }
        onPaint: {
            const context = getContext("2d")
            context.reset()
            const gradient = context.createLinearGradient(0, height, 0, 0)
            for (const stop of colorBar.stops)
                gradient.addColorStop(stop.position, stop.color)
            context.fillStyle = gradient
            context.fillRect(0, 0, width, height)
            context.strokeStyle = Theme.overlayText
            context.lineWidth = 1
            context.strokeRect(0.5, 0.5, width - 1, height - 1)
        }
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
    }

    Text {
        anchors.left: colorRamp.right
        anchors.leftMargin: 6
        anchors.top: parent.top
        text: colorBar.formatValue(colorBar.maximumValue)
        color: Theme.overlayText
        font.pixelSize: 10
        style: Text.Outline
        styleColor: Theme.overlayOutline
    }

    Text {
        anchors.left: colorRamp.right
        anchors.leftMargin: 6
        anchors.bottom: parent.bottom
        text: colorBar.formatValue(colorBar.minimumValue)
        color: Theme.overlayText
        font.pixelSize: 10
        style: Text.Outline
        styleColor: Theme.overlayOutline
    }

    onStopsChanged: colorRamp.requestPaint()
}
