pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Shapes
import "../../../../theme"

Item {
    id: root
    property var preferences: ({})
    readonly property var styleSettings: preferences.measurement ?? ({})
    property bool draftStyle: isDraft
    readonly property bool dashed: Theme.drawingLineDashed(styleSettings, draftStyle)
    property var labelPosition: null
    required property var measurement
    required property var mappedPoints
    required property bool isDraft
    required property bool isSelected
    property alias labelItem: measurementLabel
    readonly property color lineColor: Theme.drawingLineColor(styleSettings, draftStyle)
    readonly property point a: mappedPoints?.[0] ?? Qt.point(0, 0)
    readonly property point vertex: mappedPoints?.[1] ?? Qt.point(0, 0)
    readonly property point b: mappedPoints?.[2] ?? Qt.point(0, 0)
    readonly property real startAngle: Math.atan2(a.y - vertex.y, a.x - vertex.x) * 180 / Math.PI
    readonly property real sweepAngle: {
        const end = Math.atan2(b.y - vertex.y, b.x - vertex.x) * 180 / Math.PI
        return ((end - startAngle + 540) % 360) - 180
    }
    readonly property real arcRadius: Math.min(24,
        Math.hypot(a.x - vertex.x, a.y - vertex.y) / 3,
        Math.hypot(b.x - vertex.x, b.y - vertex.y) / 3)

    Shape {
        preferredRendererType: Shape.CurveRenderer
        antialiasing: true
        anchors.fill: parent
        ShapePath {
            strokeColor: root.lineColor
            strokeWidth: root.styleSettings.lineWidth ?? 1.5
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            strokeStyle: root.dashed ? ShapePath.DashLine : ShapePath.SolidLine
            dashPattern: [4, 2]
            startX: root.a.x
            startY: root.a.y
            PathLine { x: root.vertex.x; y: root.vertex.y }
            PathLine { x: root.b.x; y: root.b.y }
        }
        ShapePath {
            strokeColor: root.arcRadius > 1 ? root.lineColor : "transparent"
            strokeWidth: root.styleSettings.lineWidth ?? 1.5
            fillColor: "transparent"
            PathAngleArc {
                centerX: root.vertex.x
                centerY: root.vertex.y
                radiusX: root.arcRadius
                radiusY: root.arcRadius
                startAngle: root.startAngle
                sweepAngle: root.sweepAngle
            }
        }
    }
    Repeater {
        model: root.mappedPoints
        Rectangle {
            required property var modelData
            width: 6; height: 6; radius: 3
            x: modelData.x - 3; y: modelData.y - 3
            visible: root.isDraft || root.isSelected
            color: root.lineColor
        }
    }
    Text {
        id: measurementLabel
        objectName: "measurementLabel"
        x: Math.max(4, Math.min(root.width - width - 4, root.labelPosition ? root.labelPosition.x : root.vertex.x + 14))
        y: Math.max(4, Math.min(root.height - height - 4, root.labelPosition ? root.labelPosition.y : root.vertex.y + 14))
        text: root.measurement?.label ?? ""
        color: root.lineColor
        font.pixelSize: root.styleSettings.fontSize ?? 13
        font.bold: true
        style: Text.Outline
        styleColor: Theme.overlayOutline
    }
}
