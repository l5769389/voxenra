pragma ComponentBehavior: Bound
import QtQuick
import "../../../theme"

Canvas {
    id: overlay
    required property var controller
    required property var coordinateMapper
    required property var transformState
    objectName: "cprPathOverlay"
    readonly property var guides: controller?.cprGuides ?? ({})
    onGuidesChanged: requestPaint()
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
    function pixel(col, row) {
        return coordinateMapper.mapDicomPixelToItem(overlay, col, row)
    }

    function line(ctx, a, b) {
        ctx.beginPath()
        ctx.moveTo(a.x, a.y)
        ctx.lineTo(b.x, b.y)
        ctx.stroke()
    }

    function drawInterval(ctx, rows) {
        const a = pixel(guides.startColumn, 0)
        const b = pixel(guides.endColumn, 0)
        const c = pixel(guides.endColumn, rows - 1)
        const d = pixel(guides.startColumn, rows - 1)
        ctx.save()
        ctx.strokeStyle = ctx.fillStyle = Theme.crosshairPreview
        ctx.globalAlpha = 0.12
        ctx.beginPath()
        ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y)
        ctx.lineTo(c.x, c.y); ctx.lineTo(d.x, d.y); ctx.closePath(); ctx.fill()
        ctx.globalAlpha = 1
        ctx.lineWidth = 1.5
        ctx.setLineDash([4, 3])
        line(ctx, a, d)
        line(ctx, b, c)
        ctx.setLineDash([])
        ctx.font = "bold 12px sans-serif"
        ctx.textBaseline = "bottom"
        ctx.fillStyle = Theme.overlayText
        ctx.strokeStyle = Theme.imageBlack
        ctx.lineWidth = 3
        const ax = Math.max(2, Math.min(width - 12, a.x + 3))
        const ay = Math.max(14, Math.min(height - 2, a.y - 1))
        if (a.x >= 0 && a.x <= width && a.y >= 0 && a.y <= height) {
            const label = "A " + guides.startMm.toFixed(2) + " mm"
            const x = Math.min(ax, width - ctx.measureText(label).width - 2)
            ctx.strokeText(label, x, ay)
            ctx.fillText(label, x, ay)
        }
        if (guides.length > 0 && c.x >= 0 && c.x <= width && c.y >= 0 && c.y <= height) {
            ctx.textBaseline = "top"
            const label = "B " + guides.endMm.toFixed(2) + " mm   |   A–B " + guides.length.toFixed(2) + " mm"
            const x = Math.max(2, Math.min(width - ctx.measureText(label).width - 2, c.x + 3))
            const y = Math.max(2, Math.min(height - 14, c.y + 1))
            ctx.strokeText(label, x, y)
            ctx.fillText(label, x, y)
        }
        ctx.restore()
    }

    function drawSectionGuide(ctx, columns, rows) {
        const x = (columns - 1) / 2, y = (rows - 1) / 2
        const halfWidth = Math.min(x, guides.widthPixels / 2)
        ctx.save()
        ctx.strokeStyle = Theme.crosshairPreview
        ctx.lineWidth = 1.25
        line(ctx, pixel(x - halfWidth, y), pixel(x + halfWidth, y))
        if (guides.widthPixels <= columns - 1) {
            for (const side of [-1, 1]) {
                const col = x + side * halfWidth
                line(ctx, pixel(col, y - 1), pixel(col, y + 1))
            }
        }
        const halfSlab = guides.slabPixels / 2
        if (halfSlab > 0 && halfSlab <= y) {
            ctx.setLineDash([4, 3])
            line(ctx, pixel(x - halfWidth, y - halfSlab), pixel(x + halfWidth, y - halfSlab))
            line(ctx, pixel(x - halfWidth, y + halfSlab), pixel(x + halfWidth, y + halfSlab))
        }
        ctx.restore()
    }

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
        ctx.globalAlpha = 1
        if (guides.startColumn !== undefined)
            drawInterval(ctx, controller.imageRows)
        if (guides.widthPixels !== undefined)
            drawSectionGuide(ctx, controller.imageColumns, controller.imageRows)
        for (const label of ["A", "B"]) {
            const mark = guides[label]
            if (!mark) continue
            const p = pixel(mark.col, mark.row)
            ctx.save()
            ctx.strokeStyle = Theme.crosshairPreview
            ctx.lineWidth = 2
            ctx.beginPath(); ctx.arc(p.x, p.y, 6, 0, Math.PI*2); ctx.stroke()
            ctx.font = "bold 12px sans-serif"
            ctx.strokeStyle = Theme.imageBlack; ctx.lineWidth = 3
            ctx.fillStyle = Theme.overlayText
            const y = p.y + (label === "A" ? -7 : 15)
            ctx.strokeText(label, p.x+6, y); ctx.fillText(label, p.x+6, y)
            ctx.restore()
        }
        if (guides.stationX !== undefined) {
            const center = pixel(guides.stationX, guides.stationY)
            ctx.strokeStyle = Theme.measurementPrimary
            ctx.beginPath(); ctx.arc(center.x, center.y, 5, 0, 2 * Math.PI); ctx.stroke()
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
