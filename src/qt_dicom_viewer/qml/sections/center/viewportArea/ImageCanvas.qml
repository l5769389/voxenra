import QtQuick
import 'measurementLayer' as MeasurementLayer
import "../../../theme"

Rectangle {
    id: imageCanvasRoot
    required property var viewportController
    anchors.fill: parent
    color: viewportController
        ? viewportController.canvasBackgroundColor
        : Theme.canvasBackground
    clip: true
    readonly property real pixelsPerMillimeter: imageScene.scale
    Canvas {
        id: referenceCanvas
        objectName: "compareReferenceLines"
        anchors.fill: parent
        z: 15
        visible: !!imageCanvasRoot.viewportController?.referenceLines && imageCanvasRoot.viewportController.showLocalizer
        readonly property var lines: imageCanvasRoot.viewportController?.referenceLines ?? []
        readonly property var transforms: imageCanvasRoot.measurementTransformState
        onLinesChanged: requestPaint()
        onTransformsChanged: requestPaint()
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onPaint: {
            const ctx = getContext("2d")
            ctx.reset()
            ctx.strokeStyle = Theme.crosshairPreview
            ctx.lineWidth = 1
            for (const line of lines) {
                const a = imageCanvasRoot.mapDicomPixelToItem(referenceCanvas, line.x1, line.y1)
                const b = imageCanvasRoot.mapDicomPixelToItem(referenceCanvas, line.x2, line.y2)
                ctx.beginPath(); ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y); ctx.stroke()
            }
        }
    }
    TapHandler {
        enabled: !!imageCanvasRoot.viewportController?.locatePatientPoint
        acceptedModifiers: Qt.AltModifier
        onTapped: {
            const p = imageCanvasRoot.mapToDicomPixel(imageCanvasRoot, point.position)
            if (p.valid) imageCanvasRoot.viewportController.locatePatientPoint(p.column, p.row)
        }
    }

    function updateMeasurementHitRegions(interactionLayer) {
        if (["service:mtf", "service:fwhm"].includes(imageCanvasRoot.viewportController?.activeInteraction)) {
            imageCanvasRoot.viewportController.activeAnnotationController.setLabelHitRegions(
                mtfOverlay.labelHitRegions(interactionLayer))
        }
        if (imageCanvasRoot.viewportController
                && (imageCanvasRoot.viewportController.activeInteraction.startsWith("measure:")
                    || imageCanvasRoot.viewportController.activeInteraction.startsWith("annotate:"))) {
            imageCanvasRoot.viewportController.measurementController.setLabelHitRegions(
                measurementOverlay.labelHitRegions(interactionLayer)
            )
        }
    }

    function hitToleranceInImagePixels(screenTolerance) {
        return screenTolerance / Math.max(
            Math.abs(imageScene.scale) * Math.min(imageScene.rowSpacing, imageScene.columnSpacing),
            0.0001
        )
    }

    readonly property real pointHitToleranceInImagePixels:
        hitToleranceInImagePixels(8)

    readonly property real lineHitToleranceInImagePixels:
        hitToleranceInImagePixels(6)

    readonly property point crosshairViewportPosition: {
    const controller = imageCanvasRoot.viewportController

    if (!controller || !controller.hasCrosshair)
        return Qt.point(-1, -1)

    const imagePosition = controller.crosshairImagePosition

    if (!Number.isFinite(imagePosition.x)
            || !Number.isFinite(imagePosition.y))
        return Qt.point(-1, -1)

    // 显式读取变换属性，让绑定在变换后重新计算
    const transformDependency =
        imageScene.x
        + imageScene.y
        + imageScene.scale
        + imageScene.rotation
        + pixelLayer.width
        + pixelLayer.height
        + (controller.horizontalFlip ? 1 : 0)
        + (controller.verticalFlip ? 1 : 0)

    if (!Number.isFinite(transformDependency))
        return Qt.point(-1, -1)

    return pixelLayer.mapToItem(
        imageCanvasRoot,
        imagePosition.x + 0.5,
        imagePosition.y + 0.5
    )
}

    function mapToDicomPixel(interactionLayer, position) {
        if (
            pixelLayer.width <= 0
            || pixelLayer.height <= 0
        ) {
            return {
                valid: false,
                column: 0,
                row: 0,
                clipColumn: 0,
                clipRow: 0,
                columnIndex: 0,
                rowIndex: 0
            }
        }

        const local = pixelLayer.mapFromItem(
            interactionLayer,
            position.x,
            position.y
        )

        const inside =
            local.x >= 0
            && local.y >= 0
            && local.x < pixelLayer.width
            && local.y < pixelLayer.height

        if (!inside) {
            return {
                valid: false,
                column: local.x - 0.5,
                row: local.y - 0.5,
                clipColumn: 0,
                clipRow: 0,
                columnIndex: 0,
                rowIndex: 0
            }
        }

        return {
            valid: true,

            // 连续像素坐标，以第一颗像素中心为 (0, 0)
            column: local.x - 0.5,
            row: local.y - 0.5,

            clipColumn: Math.floor(Math.max(0, Math.min(pixelLayer.width - 1, local.x))),
            clipRow: Math.floor(Math.max(0, Math.min(pixelLayer.height - 1, local.y))),

            // 对应 PixelData 的整数索引
            columnIndex: Math.floor(local.x),
            rowIndex: Math.floor(local.y)
        }
    }

    function mapDicomPixelToItem(targetItem, column, row) {
        if (pixelLayer.width <= 0 || pixelLayer.height <= 0)
            return Qt.point(-1, -1)

        return pixelLayer.mapToItem(
            targetItem,
            column + 0.5,
            row + 0.5
        )
    }

    readonly property real fitScale: {
        if (!imageCanvasRoot.viewportController)
            return 1

        const physicalWidth =
            imageCanvasRoot.viewportController.imageColumns
            * imageCanvasRoot.viewportController.imageColumnSpacing

        const physicalHeight =
            imageCanvasRoot.viewportController.imageRows
            * imageCanvasRoot.viewportController.imageRowSpacing

        if (physicalWidth <= 0 || physicalHeight <= 0)
            return 1

        const fitted = Math.min(
            imageCanvasRoot.width / physicalWidth,
            imageCanvasRoot.height / physicalHeight
        )
        return imageCanvasRoot.viewportController.fitToWindow ? fitted : 1
    }

    // 将测量轮廓映射到屏幕层，文字、线宽和控制点不随缩放/翻转变形。
    readonly property var measurementTransformState: [
        imageScene.x, imageScene.y, imageScene.scale, imageScene.rotation,
        imageScene.rowSpacing, imageScene.columnSpacing, pixelLayer.width, pixelLayer.height,
        imageScene.controller ? imageScene.controller.horizontalFlip : false,
        imageScene.controller ? imageScene.controller.verticalFlip : false
    ]

    // 图像场景使用毫米作为局部尺寸，负责整体平移、缩放和旋转。
    Item {
        id: imageScene
        readonly property var controller: imageCanvasRoot.viewportController

        readonly property real rowSpacing:
            controller ? controller.imageRowSpacing : 1.0
        readonly property real columnSpacing:
            controller ? controller.imageColumnSpacing : 1.0

        readonly property real physicalWidth:
            controller
                ? controller.imageColumns * columnSpacing
                : 0

        readonly property real physicalHeight:
            controller
                ? controller.imageRows * rowSpacing
                : 0

        width: physicalWidth
        height: physicalHeight


        // 未缩放时让图像中心位于 viewport 中心
        x: (
            imageCanvasRoot.width - width
        ) / 2 + (
            controller ? controller.panX : 0
        )

        y: (
            imageCanvasRoot.height - height
        ) / 2 + (
            controller ? controller.panY : 0
        )

        transformOrigin: Item.Center

        scale: imageCanvasRoot.fitScale * (
            controller ? controller.zoom : 1
        )

        rotation: controller
            ? controller.rotationDegrees : 0


        // pixelLayer 保持一单位对应一个原始/重采样像素；spacingLayer
        // 再按毫米间距缩放，使非等距像素也能保持正确的物理宽高比例。
        Item {
            id: spacingLayer

            width: imageScene.controller
                ? imageScene.controller.imageColumns
                : 0
            height: imageScene.controller
                ? imageScene.controller.imageRows
                : 0

            transform: Scale {
                origin.x: 0
                origin.y: 0

                xScale: imageScene.columnSpacing
                yScale: imageScene.rowSpacing
            }
            // 负责水平、垂直翻转
            Item {
                id: pixelLayer
                objectName: "dicomPixelLayer"
                anchors.fill: parent

                transform: Scale {
                    origin.x
                        :
                        pixelLayer.width / 2
                    origin.y
                        :
                        pixelLayer.height / 2

                    xScale: imageScene.controller
                        && imageScene.controller.horizontalFlip
                        ? -1 : 1

                    yScale: imageScene.controller
                        && imageScene.controller.verticalFlip
                        ? -1 : 1
                }

                Image {
                    anchors.fill: parent

                    source: imageScene.controller ? imageScene.controller.imageSource : ""

                    // pixelLayer 的宽高已经保持图像比例
                    fillMode: Image.Stretch
                    cache: false
                    smooth: true
                }

                Repeater {
                    model: imageCanvasRoot.viewportController?.voiMasks ?? []
                    delegate: Image {
                        required property var modelData
                        objectName: "mprSegmentationMask"
                        anchors.fill: parent
                        source: modelData.source
                        smooth: false
                        cache: false
                    }
                }

            }
        }
    }

    MprVoiOverlay {
        anchors.fill: parent
        items: imageCanvasRoot.viewportController?.voiOverlays ?? []
        coordinateMapper: imageCanvasRoot
        transformState: imageCanvasRoot.measurementTransformState
    }

    WaterQaOverlay {
        anchors.fill: parent
        controller: imageCanvasRoot.viewportController?.qaController ?? null
        coordinateMapper: imageCanvasRoot
        transformState: imageCanvasRoot.measurementTransformState
    }

    MeasurementLayer.MeasurementLayer {
        id: measurementOverlay
        preferences: imageCanvasRoot.viewportController?.settingsController.values ?? ({})
        anchors.fill: parent
        coordinateMapper: imageCanvasRoot
        transformState: imageCanvasRoot.measurementTransformState
        measurementController: imageCanvasRoot.viewportController
            ? imageCanvasRoot.viewportController.measurementController : null
    }

    MeasurementLayer.MeasurementLayer {
        id: mtfOverlay
        preferences: imageCanvasRoot.viewportController?.settingsController.values ?? ({})
        objectName: "mtfOverlay"
        anchors.fill: parent
        coordinateMapper: imageCanvasRoot
        transformState: imageCanvasRoot.measurementTransformState
        measurementController: imageCanvasRoot.viewportController?.activeProfileController?.roiController ?? null
        showRoiMetrics: false
        roiLabel: imageCanvasRoot.viewportController?.activeProfileController?.roiMetricLabel ?? ""
    }

}
