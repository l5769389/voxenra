import QtQuick

Item {
    id: root
    objectName: "mprSlabGuideLayer"
    clip: true

    required property var coordinateMapper
    required property var guides
    required property var transformState

    onGuidesChanged: guideCanvas.requestPaint()
    onTransformStateChanged: guideCanvas.requestPaint()
    onWidthChanged: guideCanvas.requestPaint()
    onHeightChanged: guideCanvas.requestPaint()

    Canvas {
        id: guideCanvas
        objectName: "mprSlabGuideCanvas"
        anchors.fill: parent

        onPaint: {
            const context = getContext("2d")
            context.reset()

            if (!root.coordinateMapper || !root.guides)
                return

            const armLength = 2 * Math.hypot(width, height)
            const dashLength = 7
            const gapLength = 6

            for (const guide of root.guides) {
                const anchor = root.coordinateMapper.mapDicomPixelToItem(
                    root,
                    guide.anchorColumn,
                    guide.anchorRow
                )
                const directionPoint =
                    root.coordinateMapper.mapDicomPixelToItem(
                        root,
                        guide.anchorColumn + guide.directionColumn,
                        guide.anchorRow + guide.directionRow
                    )
                const dx = directionPoint.x - anchor.x
                const dy = directionPoint.y - anchor.y
                const length = Math.hypot(dx, dy)
                if (!Number.isFinite(length) || length < 0.0001)
                    continue

                const ux = dx / length
                const uy = dy / length
                context.beginPath()
                for (
                    let distance = -armLength;
                    distance < armLength;
                    distance += dashLength + gapLength
                ) {
                    const dashEnd = Math.min(
                        distance + dashLength,
                        armLength
                    )
                    context.moveTo(
                        anchor.x + ux * distance,
                        anchor.y + uy * distance
                    )
                    context.lineTo(
                        anchor.x + ux * dashEnd,
                        anchor.y + uy * dashEnd
                    )
                }
                context.lineWidth = 1
                context.strokeStyle = guide.color
                context.globalAlpha = 0.85
                context.stroke()
            }
        }
    }
}
