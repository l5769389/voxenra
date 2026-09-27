pragma
ComponentBehavior: Bound

import QtQuick
import QtQuick.Shapes
import "../../../components" as Components
import "../../../theme"
import "CursorPolicy.js" as CursorPolicy

Item {
    id: interactionLayer
    objectName: "viewportInteractionLayer"
    clip: true

    signal pointerMoved(point position)
    signal pointerExited()
    signal pointerPressedAt(point position, int buttons)
    signal pointerTapFinished()

    signal tapped(point position)
    signal finishMeasurementRequested()

    signal dragStarted(
        point startPosition,
        int buttons
    )

    signal dragMoved(
        point startPosition,
        point currentPosition,
        point stepDelta,
        point totalDelta
    )

    signal dragFinished(
        point startPosition,
        point endPosition,
        point totalDelta
    )

    signal wheelMoved(
        point position,
        real angleDeltaY,
        real pixelDeltaY,
        int modifiers
    )


    property point dragStart: Qt.point(0, 0)
    property point lastPosition: Qt.point(0, 0)
    property string crosshairHoverTarget: ""
    property string measurementCursorKind: ""
    property string regionCursorKind: ""
    property string activeInteraction: ""
    property real brushDiameterPixels: 0
    property bool brushPreviewEnabled: false
    property bool registrationInteraction: false
    property bool locatorPressed: false
    property string dragCursorKind: ""
    // 从按下到释放持续为 true，不受 DragHandler 拖动阈值影响。
    readonly property bool pointerPressed: pressTracker.active
    // ROI 和箭头标注需要从第一个像素位移就反馈。其他视图操作继续沿用
    // 平台拖动阈值，避免一次普通点击被解释成调窗、平移或缩放。
    readonly property bool immediateRoiDrag:
        locatorPressed || registrationInteraction || activeInteraction === "mpr:segmentation"
        || activeInteraction === "mpr:voi"
        || activeInteraction === "measure:rect"
        || activeInteraction === "measure:ellipse"
        || activeInteraction === "measure:freehand"
        || activeInteraction === "measure:curve"
        || activeInteraction === "service:mtf"
        || activeInteraction === "service:fwhm"
        || activeInteraction === "annotate:text"
        || activeInteraction === "service:qa"
    readonly property bool immediateDrag: registrationInteraction
        || (immediateRoiDrag && (pressTracker.point.pressedButtons & Qt.LeftButton) !== 0)

    readonly property string hoverCursorKind: locatorPressed ? "crosshair-move"
        : registrationInteraction ? (crosshairHoverTarget === "center" ? "crosshair-move" : "pan")
        : CursorPolicy.resolve(activeInteraction, regionCursorKind, crosshairHoverTarget, measurementCursorKind)
    function dragCursorForButtons(buttons) {
        return CursorPolicy.resolveDrag(hoverCursorKind, buttons, registrationInteraction)
    }
    onActiveInteractionChanged: {
        dragCursorKind = ""
        if (hoverHandler.hovered && !pointerPressed)
            pointerMoved(hoverHandler.point.position)
    }

    readonly property string effectiveCursorKind:
        dragHandler.active
            ? dragCursorKind
            : hoverCursorKind

    readonly property bool customCursorActive:
        effectiveCursorKind !== "" && effectiveCursorKind !== "default"
    readonly property int effectiveCursorShape: customCursorActive ? Qt.BlankCursor : Qt.ArrowCursor

    readonly property point cursorPosition:
        dragHandler.active
            ? dragHandler.centroid.position
            : hoverHandler.point.position

    // 作用只有一个：稳定判断鼠标是否处于“按下到释放”的周期。
    // 鼠标按下       pressTracker.active = true
    // 按住并移动     pressTracker.active = true
    // 进入 Drag      pressTracker.active = true
    // 鼠标释放       pressTracker.active = false
    PointHandler {
        id: pressTracker

        target: null
        cursorShape: interactionLayer.effectiveCursorShape
        acceptedDevices: PointerDevice.Mouse
            | PointerDevice.TouchPad
        acceptedButtons: Qt.LeftButton
            | Qt.RightButton
            | Qt.MiddleButton
        onActiveChanged: {
            if (active) {
                interactionLayer.locatorPressed = false
                interactionLayer.pointerPressedAt(point.position, point.pressedButtons)
            }
        }
    }

    HoverHandler {
        id: hoverHandler

        acceptedDevices: PointerDevice.Mouse
            | PointerDevice.TouchPad

        cursorShape: interactionLayer.effectiveCursorShape

        onHoveredChanged: {
            if (!hovered)
                interactionLayer.pointerExited()
        }

        onPointChanged: {
            if (
                !hoverHandler.hovered
                || interactionLayer.pointerPressed
            )
                return

            interactionLayer.pointerMoved(
                hoverHandler.point.position
            )
        }
    }

    Rectangle {
        objectName: "segmentationBrushPreview"
        visible: interactionLayer.brushPreviewEnabled && (hoverHandler.hovered || dragHandler.active)
            && ["segmentation-paint", "segmentation-erase"].includes(interactionLayer.effectiveCursorKind)
        width: interactionLayer.brushDiameterPixels
        height: width
        x: interactionLayer.cursorPosition.x - width / 2
        y: interactionLayer.cursorPosition.y - height / 2
        radius: width / 2
        color: "transparent"
        border.width: 1.5
        border.color: interactionLayer.effectiveCursorKind === "segmentation-erase"
            ? Theme.dangerColor : Theme.overlayText
        z: 99
    }

    Item {
        id: customCursor
        objectName: "viewportCustomCursor"

        // The arrow tip, not the tool badge, is the click/drawing hotspot.
        width: 40; height: 32
        x: interactionLayer.cursorPosition.x - 2
        y: interactionLayer.cursorPosition.y - 2
        z: 100
        visible: (hoverHandler.hovered || dragHandler.active) && interactionLayer.customCursorActive
        CursorGlyph {
            objectName: "viewportCursorOperationIcon"
            anchors.fill: parent
            iconName: interactionLayer.effectiveCursorKind
        }
    }

    TapHandler {
        id: pressHandler

        acceptedButtons: Qt.LeftButton
            | Qt.RightButton
            | Qt.MiddleButton


        onDoubleTapped: (eventPoint, button) => {
            if (button === Qt.LeftButton) interactionLayer.finishMeasurementRequested()
        }
        onTapped: (eventPoint, button) => {
            // 只有左键点击执行测量选择等 tapped 逻辑。
            if (button !== Qt.LeftButton)
                return
            if (interactionLayer.locatorPressed) {
                interactionLayer.locatorPressed = false
                interactionLayer.pointerTapFinished()
                return
            }

            interactionLayer.tapped(
                eventPoint.position
            )
            interactionLayer.pointerTapFinished()
        }
    }

    DragHandler {
        id: dragHandler

        target: null
        cursorShape: interactionLayer.effectiveCursorShape
        // undefined 会恢复 Qt 的平台默认值；零阈值用于 ROI 和箭头标注。
        dragThreshold: interactionLayer.immediateDrag ? 0 : undefined

        acceptedButtons: Qt.LeftButton
            | Qt.RightButton
            | Qt.MiddleButton

        onActiveChanged: {
            if (dragHandler.active) {
                interactionLayer.dragCursorKind =
                    interactionLayer.dragCursorForButtons(dragHandler.centroid.pressedButtons)

                interactionLayer.dragStart =
                    dragHandler.centroid.pressPosition

                interactionLayer.lastPosition =
                    interactionLayer.dragStart

                interactionLayer.dragStarted(
                    interactionLayer.dragStart,
                    dragHandler.centroid.pressedButtons
                )

                // DragHandler 用本次 move 激活时，不一定再发一次
                // activeTranslationChanged。立即转发激活点，避免 ROI 的首个位移丢失。
                if (interactionLayer.immediateDrag) {
                    const current = dragHandler.centroid.position
                    const initial = Qt.point(
                        current.x - interactionLayer.dragStart.x,
                        current.y - interactionLayer.dragStart.y
                    )
                    if (initial.x !== 0 || initial.y !== 0) {
                        interactionLayer.dragMoved(
                            interactionLayer.dragStart,
                            current,
                            initial,
                            initial
                        )
                    }
                    interactionLayer.lastPosition = current
                } else {
                    interactionLayer.lastPosition =
                        dragHandler.centroid.position
                }
            } else {
                interactionLayer.dragCursorKind = ""

                interactionLayer.dragFinished(
                    interactionLayer.dragStart,
                    dragHandler.centroid.position,
                    dragHandler.activeTranslation
                )
            }
        }

        onActiveTranslationChanged: {
            if (!dragHandler.active)
                return

            const current = dragHandler.centroid.position
            const step = Qt.point(
                current.x - interactionLayer.lastPosition.x,
                current.y - interactionLayer.lastPosition.y
            )

            interactionLayer.dragMoved(
                interactionLayer.dragStart,
                current,
                step,
                dragHandler.activeTranslation
            )

            interactionLayer.lastPosition = current
        }
    }

    WheelHandler {
        id: wheelHandler

        target: null
        orientation: Qt.Vertical
        blocking: true

        acceptedDevices: PointerDevice.Mouse
            | PointerDevice.TouchPad

        onWheel: wheelEvent => {
            interactionLayer.wheelMoved(
                Qt.point(wheelEvent.x, wheelEvent.y),
                wheelEvent.angleDelta.y,
                wheelEvent.pixelDelta.y,
                Number(wheelEvent.modifiers)
            )

            // 已处理事件，不再继续传递给下面的组件。
            wheelEvent.accepted = true
        }
    }
}
