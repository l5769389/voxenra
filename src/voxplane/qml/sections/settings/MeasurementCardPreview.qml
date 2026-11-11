pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../center/viewportArea/measurementLayer" as Measurements
import "../../theme"

ColumnLayout {
    id: root
    required property var settingsController
    readonly property var options: settingsController.values.measurement
    spacing: 8
    Text {
        Layout.fillWidth: true
        text: qsTrId("measurement.cardPreview")
        color: Theme.textMuted
        font.pixelSize: 12
        wrapMode: Text.Wrap
    }
    Rectangle {
        id: stage
        objectName: "measurementCardPreview"
        Layout.fillWidth: true
        implicitHeight: card.implicitHeight + 170
        clip: true
        radius: 5
        gradient: Gradient {
            GradientStop { position: 0; color: Theme.previewGradientTop }
            GradientStop { position: 0.55; color: Theme.previewGradientMiddle }
            GradientStop { position: 1; color: Theme.previewGradientBottom }
        }
        property real shapeX: 20
        property real shapeY: 16
        property real cardX: 12
        property real cardY: 116
        function move(cardTarget, dx, dy, shapeStart, cardStart) {
            const linked = root.options.linkLabelToShape
            let minX = cardTarget ? cardStart.x : shapeStart.x
            let minY = cardTarget ? cardStart.y : shapeStart.y
            let maxX = cardTarget ? cardStart.x + card.width : shapeStart.x + shape.width
            let maxY = cardTarget ? cardStart.y + card.height : shapeStart.y + shape.height
            if (linked) {
                minX = Math.min(shapeStart.x, cardStart.x)
                minY = Math.min(shapeStart.y, cardStart.y)
                maxX = Math.max(shapeStart.x + shape.width, cardStart.x + card.width)
                maxY = Math.max(shapeStart.y + shape.height, cardStart.y + card.height)
            }
            dx = Math.max(4-minX, Math.min(width-4-maxX, dx))
            dy = Math.max(4-minY, Math.min(height-4-maxY, dy))
            if (linked || !cardTarget) { shapeX = shapeStart.x+dx; shapeY = shapeStart.y+dy }
            if (linked || cardTarget) { cardX = cardStart.x+dx; cardY = cardStart.y+dy }
        }
        component DragArea: MouseArea {
            required property bool cardTarget
            property point start
            property point shapeStart
            property point cardStart
            anchors.fill: parent
            cursorShape: Qt.SizeAllCursor
            onPressed: mouse => {
                start = mapToItem(stage, mouse.x, mouse.y)
                shapeStart = Qt.point(shape.x, shape.y)
                cardStart = Qt.point(card.x, card.y)
            }
            onPositionChanged: mouse => {
                if (!pressed) return
                const point = mapToItem(stage, mouse.x, mouse.y)
                stage.move(cardTarget, point.x-start.x, point.y-start.y, shapeStart, cardStart)
            }
        }
        Rectangle {
            id: shape
            objectName: "measurementPreviewShape"
            x: stage.shapeX; y: stage.shapeY
            width: 86; height: 62
            color: "transparent"
            border.color: root.options.completedColor
            border.width: root.options.lineWidth
            DragArea { cardTarget: false }
        }
        Measurements.RoiMetricCard {
            id: card
            objectName: "measurementPreviewCard"
            x: Math.max(4, Math.min(stage.cardX, stage.width-width-4))
            y: Math.max(4, Math.min(stage.cardY, stage.height-height-4))
            width: Math.min(implicitWidth, stage.width-16)
            settingsController: root.settingsController
            accentColor: root.options.completedColor
            visibleMetrics: root.settingsController.values.roi
            measurement: ({type: "rect", metrics: {width_mm: 20, height_mm: 20, area_mm2: 400,
                mean: 40, std: 8.5, minimum: 12, maximum: 65, pixel_count: 400, unit: "HU"}})
            DragArea { cardTarget: true }
        }
    }
    Text {
        objectName: "measurementPreviewLinkMode"
        Layout.fillWidth: true
        text: root.options.linkLabelToShape ? qsTrId("measurement.linked") : qsTrId("measurement.independent")
        color: Theme.textMuted
        font.pixelSize: 11
    }
}
