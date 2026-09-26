pragma ComponentBehavior: Bound
import QtQuick
import "../../../theme"

Item {
    id: root
    objectName: "imageScaleBar"
    required property real pixelsPerMm
    required property bool calibrated
    required property var options
    readonly property real availablePixels: Math.max(0, Math.min(width - 32, width * 0.25, 160))
    readonly property real lengthMm: {
        if (!calibrated || !Number.isFinite(pixelsPerMm) || pixelsPerMm <= 0)
            return 0
        const selected = options.lengthMm ?? 100
        const limit = Math.min(selected, availablePixels / pixelsPerMm)
        if (!(limit > 0) || !Number.isFinite(limit)) return 0
        const power = Math.pow(10, Math.floor(Math.log10(limit)))
        return Number(((limit >= 5 * power ? 5 : limit >= 2 * power ? 2 : 1) * power).toPrecision(8))
    }
    readonly property real barPixels: lengthMm * pixelsPerMm
    visible: options.enabled !== false && lengthMm > 0
    height: 28
    Rectangle {
        id: line
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        width: root.barPixels
        height: 1
        color: root.options.color ?? Theme.scaleText
        Rectangle { width: 1; height: 7; anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; color: line.color }
        Rectangle { width: 1; height: 7; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; color: line.color }
    }
    Text {
        objectName: "scaleBarLabel"
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: line.top
        anchors.bottomMargin: 5
        text: root.lengthMm === 100 ? "10 cm" : root.lengthMm + " mm"
        color: line.color
        font.pixelSize: 11
        style: Text.Outline
        styleColor: Theme.scaleOutline
    }
}
