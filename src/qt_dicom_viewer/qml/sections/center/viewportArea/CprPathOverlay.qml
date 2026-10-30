pragma ComponentBehavior: Bound
import QtQuick
import "../../../theme"

Canvas {
    id: overlay
    required property var controller
    required property var coordinateMapper
    required property var transformState
    readonly property var points: controller?.cprPoints ?? []
    readonly property real marker: controller?.cprMarkerColumn ?? -1
    property var previewPoint: null
    readonly property bool drawing: controller?.cprDrawing ?? false
    onPreviewPointChanged: if (drawing) requestPaint()
    onDrawingChanged: requestPaint()
    onPointsChanged: requestPaint()
    onMarkerChanged: requestPaint()
    onTransformStateChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onPaint: {
        const ctx = getContext("2d")
        ctx.clearRect(0, 0, width, height)
        if ((controller?.imageRows ?? 0) <= 0) return
        ctx.strokeStyle = Theme.crosshairPreview
        ctx.lineWidth = 2
        for (let i = 0; i < points.length; i++) {
            const p = coordinateMapper.mapDicomPixelToItem(overlay, points[i].column, points[i].row)
            if (i > 0) {
                const before = coordinateMapper.mapDicomPixelToItem(overlay, points[i-1].column, points[i-1].row)
                ctx.globalAlpha = points[i].near && points[i-1].near ? 1 : .3
                ctx.beginPath(); ctx.moveTo(before.x, before.y); ctx.lineTo(p.x, p.y); ctx.stroke()
            }
            ctx.globalAlpha = points[i].near ? 1 : .45
            ctx.fillStyle = points[i].selected ? Theme.measurementPrimary : Theme.crosshairPreview
            ctx.beginPath(); ctx.arc(p.x, p.y, points[i].selected ? 5 : 4, 0, Math.PI*2); ctx.fill()
            ctx.fillStyle = Theme.overlayText
            ctx.font = "11px sans-serif"
            ctx.fillText(String(i+1), p.x+7, p.y-6)
        }
        if (drawing && previewPoint && points.length > 0) {
            const last = points[points.length - 1]
            const a = coordinateMapper.mapDicomPixelToItem(overlay, last.column, last.row)
            const b = coordinateMapper.mapDicomPixelToItem(overlay, previewPoint.column, previewPoint.row)
            ctx.globalAlpha = .65
            ctx.setLineDash([4, 4])
            ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke()
            ctx.setLineDash([])
        }
        if (controller.viewportRole === "curved" && marker >= 0) {
            ctx.globalAlpha = 1
            const a = coordinateMapper.mapDicomPixelToItem(overlay, marker, 0)
            const b = coordinateMapper.mapDicomPixelToItem(overlay, marker, controller.imageRows-1)
            ctx.strokeStyle = Theme.measurementPrimary
            ctx.beginPath(); ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y); ctx.stroke()
        }
        ctx.globalAlpha = 1
    }
}
