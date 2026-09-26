pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Shapes
import "../../../theme"

Item {
    id: annotationLayer
    objectName: "textAnnotationLayer"
    required property var annotationController
    required property var coordinateMapper
    required property var transformState
    property var preferences: ({})
    property bool hideText: false
    readonly property var styleSettings: preferences.measurement ?? ({})

    Repeater {
        model: annotationLayer.annotationController
            ? annotationLayer.annotationController.annotationItems : []

        delegate: Item {
            id: annotationItem
            required property var modelData
            anchors.fill: parent
            objectName: "textAnnotation-" + modelData.annotationId

            readonly property point tailPoint: {
                const dependency = annotationLayer.transformState
                    ? annotationLayer.transformState.join("|") : ""
                if (!dependency || !annotationLayer.coordinateMapper)
                    return Qt.point(-1000, -1000)
                return annotationLayer.coordinateMapper.mapDicomPixelToItem(
                    annotationLayer,
                    modelData.tailColumn,
                    modelData.tailRow
                )
            }
            readonly property point headPoint: {
                const dependency = annotationLayer.transformState
                    ? annotationLayer.transformState.join("|") : ""
                if (!dependency || !annotationLayer.coordinateMapper)
                    return Qt.point(-1000, -1000)
                return annotationLayer.coordinateMapper.mapDicomPixelToItem(
                    annotationLayer,
                    modelData.headColumn,
                    modelData.headRow
                )
            }
            readonly property real arrowLength: Math.hypot(
                headPoint.x - tailPoint.x,
                headPoint.y - tailPoint.y
            )
            readonly property real directionX:
                (headPoint.x - tailPoint.x) / Math.max(arrowLength, 0.001)
            readonly property real directionY:
                (headPoint.y - tailPoint.y) / Math.max(arrowLength, 0.001)
            readonly property real normalX: -directionY
            readonly property real normalY: directionX
            readonly property real arrowHeadLength: Math.min(annotationLayer.styleSettings.annotationSize ?? 14, arrowLength * 0.45)
            readonly property real arrowHeadHalfWidth: arrowHeadLength * 0.48
            readonly property point arrowBase: Qt.point(
                headPoint.x - directionX * arrowHeadLength,
                headPoint.y - directionY * arrowHeadLength
            )
            readonly property point arrowLeft: Qt.point(
                arrowBase.x + normalX * arrowHeadHalfWidth,
                arrowBase.y + normalY * arrowHeadHalfWidth
            )
            readonly property point arrowRight: Qt.point(
                arrowBase.x - normalX * arrowHeadHalfWidth,
                arrowBase.y - normalY * arrowHeadHalfWidth
            )
            readonly property color arrowColor: modelData.color

            Shape {
                preferredRendererType: Shape.CurveRenderer
                objectName: "annotationArrow-" + annotationItem.modelData.annotationId
                readonly property bool draftStyle: annotationItem.modelData.draft
                anchors.fill: parent
                visible: annotationItem.arrowLength > 1
                antialiasing: true
                opacity: draftStyle ? 0.78 : 1

                ShapePath {
                    objectName: "annotationStem"
                    strokeColor: annotationItem.arrowColor
                    strokeWidth: annotationLayer.styleSettings.lineWidth ?? 1.5
                    fillColor: "transparent"
                    strokeStyle: (annotationItem.modelData.draft
                        ? (annotationLayer.styleSettings.editingDash ?? true)
                        : (annotationLayer.styleSettings.completedDash ?? false))
                        ? ShapePath.DashLine : ShapePath.SolidLine
                    dashPattern: [4, 2.5]
                    capStyle: ShapePath.RoundCap
                    startX: annotationItem.tailPoint.x
                    startY: annotationItem.tailPoint.y

                    PathLine {
                        x: annotationItem.arrowBase.x
                        y: annotationItem.arrowBase.y
                    }
                }

                ShapePath {
                    strokeColor: annotationItem.arrowColor
                    strokeWidth: annotationLayer.styleSettings.lineWidth ?? 1.5
                    fillColor: annotationItem.modelData.draft
                        ? "transparent" : annotationItem.arrowColor
                    joinStyle: ShapePath.RoundJoin
                    startX: annotationItem.headPoint.x
                    startY: annotationItem.headPoint.y

                    PathLine {
                        x: annotationItem.arrowLeft.x
                        y: annotationItem.arrowLeft.y
                    }
                    PathLine {
                        x: annotationItem.arrowRight.x
                        y: annotationItem.arrowRight.y
                    }
                    PathLine {
                        x: annotationItem.headPoint.x
                        y: annotationItem.headPoint.y
                    }
                }
            }

            Rectangle {
                width: 7
                height: 7
                radius: width / 2
                x: annotationItem.tailPoint.x - width / 2
                y: annotationItem.tailPoint.y - height / 2
                visible: annotationItem.modelData.selected
                    && annotationItem.arrowLength > 1
                color: annotationItem.arrowColor
                border.color: Theme.annotationHandle
                border.width: 1
            }

            Rectangle {
                width: 7
                height: 7
                radius: width / 2
                x: annotationItem.headPoint.x - width / 2
                y: annotationItem.headPoint.y - height / 2
                visible: annotationItem.modelData.selected
                    && annotationItem.arrowLength > 1
                color: annotationItem.arrowColor
                border.color: Theme.annotationHandle
                border.width: 1
            }

            Rectangle {
                id: annotationLabel
                objectName: "annotationLabel-" + annotationItem.modelData.annotationId
                x: Math.max(4, Math.min(
                    annotationItem.width - width - 4,
                    annotationItem.tailPoint.x + 9
                ))
                y: Math.max(4, Math.min(
                    annotationItem.height - height - 4,
                    annotationItem.tailPoint.y - height - 9
                ))
                width: annotationText.implicitWidth + 12
                height: annotationText.implicitHeight + 8
                radius: 4
                visible: !annotationLayer.hideText && annotationItem.modelData.text.length > 0
                color: annotationItem.modelData.draft
                    ? Theme.annotationArrowBackground
                    : annotationItem.modelData.selected
                    ? Theme.annotationSelectedBackground : Theme.annotationBackground
                border.color: annotationItem.modelData.selected
                    ? annotationItem.arrowColor : Theme.annotationBorder
                border.width: 1

                Text {
                    id: annotationText
                    anchors.centerIn: parent
                    text: annotationItem.modelData.text
                    color: annotationItem.arrowColor
                    font.pixelSize: annotationItem.modelData.fontSize
                    font.weight: Font.DemiBold
                    font.italic: annotationItem.modelData.draft
                    style: Text.Outline
                    styleColor: Theme.overlayOutline
                }
            }
        }
    }
}
