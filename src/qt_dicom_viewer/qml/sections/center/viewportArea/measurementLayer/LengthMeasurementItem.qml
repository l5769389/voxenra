import QtQuick
import QtQuick.Shapes
import "../../../../theme"

Item {
    id: root

    property var preferences: ({})
    readonly property var styleSettings: preferences.measurement ?? ({})
    property bool draftStyle: isDraft
    readonly property bool dashed: draftStyle ? (styleSettings.editingDash ?? true) : (styleSettings.completedDash ?? false)
    property var labelPosition: null
    required property var measurement

    required property var isDraft
    required property bool isSelected
    property alias labelItem: measurementLabel
    property var mappedPoints: [
        Qt.point(Number(measurement?.startColumn ?? 0) + 0.5, Number(measurement?.startRow ?? 0) + 0.5),
        Qt.point(Number(measurement?.endColumn ?? 0) + 0.5, Number(measurement?.endRow ?? 0) + 0.5)
    ]

    property var renderedPoints: mappedPoints

    readonly property color measurementColor:
        measurement?.type === "arrow" ? (styleSettings.annotationColor ?? Theme.annotationDefault) : draftStyle
            ? (styleSettings.editingColor ?? Theme.measurementSelected)
            : (styleSettings.completedColor ?? Theme.measurementPrimary)

    readonly property real startX:
        (mappedPoints?.length ?? 0) > 0 ? mappedPoints[0].x : 0

    readonly property real startY:
        (mappedPoints?.length ?? 0) > 0 ? mappedPoints[0].y : 0

    readonly property real endX:
        (mappedPoints?.length ?? 0) > 1 ? mappedPoints[mappedPoints.length - 1].x : 0

    readonly property real endY:
        (mappedPoints?.length ?? 0) > 1 ? mappedPoints[mappedPoints.length - 1].y : 0

    Shape {
        preferredRendererType: Shape.CurveRenderer
        antialiasing: true
        anchors.fill: parent

        ShapePath {
            strokeColor: root.measurementColor
            strokeWidth: root.styleSettings.lineWidth ?? 1.5
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            strokeStyle: root.dashed
                ? ShapePath.DashLine
                : ShapePath.SolidLine
            dashPattern: [4, 2]
            startX: root.startX
            startY: root.startY

            PathSvg {
                path: (root.renderedPoints?.length ?? 0) > 0 ? "M " + root.renderedPoints.map(p => p.x + " " + p.y).join(" L ") : ""
            }
        }
    }

    Shape {
        preferredRendererType: Shape.CurveRenderer
        antialiasing: true
        id: arrowHead
        anchors.fill: parent
        visible: root.measurement?.type === "arrow"
        readonly property real angle: Math.atan2(root.endY - root.startY, root.endX - root.startX)
        readonly property real headSize: root.styleSettings.annotationSize ?? 14
        ShapePath {
            strokeColor: root.measurementColor
            strokeWidth: root.styleSettings.lineWidth ?? 1.5
            fillColor: root.measurementColor
            joinStyle: ShapePath.RoundJoin
            startX: root.endX
            startY: root.endY
            PathLine { x: root.endX - arrowHead.headSize * Math.cos(arrowHead.angle - 0.45); y: root.endY - arrowHead.headSize * Math.sin(arrowHead.angle - 0.45) }
            PathLine { x: root.endX - arrowHead.headSize * Math.cos(arrowHead.angle + 0.45); y: root.endY - arrowHead.headSize * Math.sin(arrowHead.angle + 0.45) }
            PathLine { x: root.endX; y: root.endY }
        }
    }

    Repeater {
        model: root.mappedPoints
        Rectangle {
            required property var modelData
            objectName: "measurementControlPoint"
            width: 6; height: 6; radius: 1
            color: root.measurementColor
            visible: root.isDraft || root.isSelected
            x: modelData.x - width / 2
            y: modelData.y - height / 2
        }
    }

    Text {
        id: measurementLabel
        objectName: "measurementLabel"
        x: root.labelPosition ? root.labelPosition.x : (root.startX + root.endX) / 2 + 6
        y: root.labelPosition ? root.labelPosition.y : (root.startY + root.endY) / 2 - height - 4

        visible: root.measurement?.type !== "arrow"
        text: root.measurement?.label ?? "--"
        color:  root.measurementColor
        font.pixelSize: root.styleSettings.fontSize ?? 13
        font.bold: true

        style: Text.Outline
        styleColor: Theme.overlayOutline
    }
}
