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
    readonly property var otherTraces: controller?.cprOtherTraces ?? []
    onOtherTracesChanged: requestPaint()
    readonly property bool wholePathSelected: !drawing && !!controller?.cprEditing && points.length > 0
        && !points.some(point => point.selected)
    onWholePathSelectedChanged: requestPaint()
    readonly property real marker: guides.positionColumn ?? -1
    readonly property color samplingColor: Theme.crosshairPreview
    onSamplingColorChanged: requestPaint()
    readonly property var referenceGuide: {
        const dependency = transformState ? transformState.join("|") : ""
        const guide = guides.samplingLine
        if (!guide || !coordinateMapper || !dependency) return null
        const a = pixel(guide.startColumn, guide.startRow)
        const b = pixel(guide.endColumn, guide.endRow)
        const center = pixel(guide.centerColumn, guide.centerRow)
        return {a: a, b: b, center: center,
            collapsed: Math.hypot(b.x - a.x, b.y - a.y) <= 4,
            projected: guide.projected, centerOnPlane: guide.centerOnPlane, endOn: guide.endOn}
    }
    onReferenceGuideChanged: requestPaint()
    Text {
        objectName: "cprSamplingGuideLabel"
        readonly property var guide: overlay.referenceGuide
        readonly property var anchor: overlay.guideLabelAnchor(guide)
        visible: anchor !== null
        text: !guide ? "" : guide.projected ? qsTrId("cpr.samplingProjection")
            : guide.endOn ? qsTrId("cpr.samplingPoint") : qsTrId("cpr.samplingLine")
        x: anchor ? Math.max(2, Math.min(overlay.width - width - 2, anchor.x + 9)) : 0
        y: anchor ? Math.max(2, Math.min(overlay.height - height - 2, anchor.y + 8)) : 0
        color: overlay.samplingColor
        font.pixelSize: 11
        style: Text.Outline
        styleColor: Theme.imageBlack
    }
    readonly property var styleSettings: controller?.settingsController?.values.measurement ?? ({})
    readonly property bool editing: controller?.cprEditing ?? false
    onStyleSettingsChanged: requestPaint()
    onEditingChanged: requestPaint()
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

    function guideLabelAnchor(guide) {
        if (!guide) return null
        const center = guide.center
        if (center.x >= 0 && center.x <= width && center.y >= 0 && center.y <= height)
            return center
        if (guide.collapsed) return null
        const visible = clippedSegment(guide.a, guide.b)
        if (!visible) return null
        return Qt.point((visible.a.x + visible.b.x) / 2, (visible.a.y + visible.b.y) / 2)
    }

    function clippedSegment(a, b) {
        // Clip finite image-space segments after all display transforms.
        let first = 0, last = 1
        for (const axis of [[a.x, b.x, width], [a.y, b.y, height]]) {
            const delta = axis[1] - axis[0]
            if (Math.abs(delta) < 1e-8) {
                if (axis[0] < 0 || axis[0] > axis[2]) return null
                continue
            }
            const entry = -axis[0] / delta
            const exit = (axis[2] - axis[0]) / delta
            first = Math.max(first, Math.min(entry, exit))
            last = Math.min(last, Math.max(entry, exit))
            if (first > last) return null
        }
        return {a: Qt.point(a.x + (b.x-a.x)*first, a.y + (b.y-a.y)*first),
            b: Qt.point(a.x + (b.x-a.x)*last, a.y + (b.y-a.y)*last), first: first, last: last}
    }

    function line(ctx, a, b) {
        ctx.beginPath()
        ctx.moveTo(a.x, a.y)
        ctx.lineTo(b.x, b.y)
        ctx.stroke()
    }

    function strokeSamplingPath(ctx, outline = true) {
        if (outline) {
            ctx.strokeStyle = Theme.imageBlack; ctx.lineWidth = 2.5; ctx.stroke()
        }
        ctx.strokeStyle = samplingColor; ctx.lineWidth = 1.5; ctx.stroke()
    }

    function samplingLine(ctx, a, b, outline = true) {
        ctx.beginPath()
        ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y)
        strokeSamplingPath(ctx, outline)
    }

    function sectionSamplingLine(ctx, a, b, fieldClipped) {
        const visible = clippedSegment(a, b)
        if (!visible) return
        const length = Math.hypot(visible.b.x-visible.a.x, visible.b.y-visible.a.y)
        if (length < 1) return
        const ux = (visible.b.x-visible.a.x)/length, uy = (visible.b.y-visible.a.y)/length
        const arrowLength = Math.min(5, length/4)
        ctx.beginPath()
        ctx.moveTo(visible.a.x, visible.a.y); ctx.lineTo(visible.b.x, visible.b.y)
        for (const [end, side, continued] of [[visible.a, -1, fieldClipped || visible.first > 0],
                                            [visible.b, 1, fieldClipped || visible.last < 1]]) {
            const dx = ux*side, dy = uy*side
            if (continued) {
                const tip = Qt.point(end.x-dx*2, end.y-dy*2)
                ctx.moveTo(tip.x-dx*arrowLength-dy*3, tip.y-dy*arrowLength+dx*3)
                ctx.lineTo(tip.x, tip.y)
                ctx.lineTo(tip.x-dx*arrowLength+dy*3, tip.y-dy*arrowLength-dx*3)
            } else {
                ctx.moveTo(end.x-dy*3, end.y+dx*3)
                ctx.lineTo(end.x+dy*3, end.y-dx*3)
            }
        }
        strokeSamplingPath(ctx)
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
        ctx.setLineDash([])
        sectionSamplingLine(ctx, pixel(x - halfWidth, y), pixel(x + halfWidth, y),
            guides.widthPixels > columns - 1 + 1e-6)
        const halfSlab = guides.slabPixels / 2
        if (halfSlab > 0 && halfSlab <= y) {
            ctx.setLineDash([4, 3])
            samplingLine(ctx, pixel(x - halfWidth, y - halfSlab), pixel(x + halfWidth, y - halfSlab))
            samplingLine(ctx, pixel(x - halfWidth, y + halfSlab), pixel(x + halfWidth, y + halfSlab))
        }
        ctx.restore()
    }

    function drawReferenceGuide(ctx) {
        const guide = referenceGuide
        if (!guide) return
        ctx.save()
        if (!guide.collapsed) {
            ctx.setLineDash(guide.projected ? [5, 4] : [])
            samplingLine(ctx, guide.a, guide.b, !guide.projected)
            const length = Math.hypot(guide.b.x - guide.a.x, guide.b.y - guide.a.y)
            const dx = (guide.b.y - guide.a.y) / length * 3
            const dy = (guide.a.x - guide.b.x) / length * 3
            ctx.setLineDash([])
            for (const end of [guide.a, guide.b])
                samplingLine(ctx, Qt.point(end.x - dx, end.y - dy), Qt.point(end.x + dx, end.y + dy), !guide.projected)
        }
        // Keep a screen-sized marker when the line collapses to a point.
        // A collapsed oblique line still needs projection styling, even if its
        // center lies on this slice. True end-on samples retain a solid ring.
        const projectedRing = !guide.centerOnPlane || (guide.collapsed && guide.projected)
        ctx.setLineDash(projectedRing ? [3, 2] : [])
        ctx.beginPath(); ctx.arc(guide.center.x, guide.center.y, 5, 0, 2 * Math.PI)
        strokeSamplingPath(ctx, !projectedRing)
        if (guide.centerOnPlane) {
            ctx.beginPath(); ctx.arc(guide.center.x, guide.center.y, 1.5, 0, 2 * Math.PI)
            ctx.fillStyle = samplingColor; ctx.fill()
        }
        ctx.restore()
    }

    onPaint: {
        const ctx = getContext("2d")
        ctx.clearRect(0, 0, width, height)
        if ((controller?.imageRows ?? 0) <= 0) return
        ctx.save()
        const widthPx = styleSettings.lineWidth ?? 1.5
        const dashes = [4, 2]
        ctx.strokeStyle = ctx.fillStyle = Theme.drawingLineColor(styleSettings, false)
        ctx.globalAlpha = Theme.referencePathOpacity
        ctx.lineWidth = widthPx
        ctx.setLineDash(Theme.drawingLineDashed(styleSettings, false) ? dashes : [])
        for (const trace of otherTraces) {
            ctx.beginPath()
            for (const [i, xy] of trace.entries()) {
                const p = pixel(xy[0], xy[1])
                if (!i) ctx.moveTo(p.x, p.y)
                else ctx.lineTo(p.x, p.y)
            }
            ctx.stroke()
            for (const xy of trace) {
                const p = pixel(xy[0], xy[1])
                ctx.beginPath(); ctx.arc(p.x, p.y, 2.5, 0, Math.PI * 2); ctx.fill()
            }
        }
        ctx.restore()
        ctx.save()
        const pathColor = Theme.drawingLineColor(styleSettings, editing)
        ctx.strokeStyle = pathColor
        ctx.lineWidth = widthPx
        ctx.setLineDash(Theme.drawingLineDashed(styleSettings, editing) ? dashes : [])
        for (let i = 0; i < points.length; i++) {
            const p = coordinateMapper.mapDicomPixelToItem(overlay, points[i].column, points[i].row)
            if (i > 0) {
                const before = coordinateMapper.mapDicomPixelToItem(overlay, points[i-1].column, points[i-1].row)
                ctx.globalAlpha = points[i].near && points[i-1].near ? 1 : .3
                ctx.beginPath(); ctx.moveTo(before.x, before.y); ctx.lineTo(p.x, p.y); ctx.stroke()
            }
            ctx.globalAlpha = points[i].near ? 1 : .45
            ctx.fillStyle = pathColor
            ctx.beginPath(); ctx.arc(p.x, p.y, points[i].selected ? 5 : wholePathSelected ? 4.5 : 3.5, 0, Math.PI*2); ctx.fill()
            if (points[i].selected) {
                ctx.fillStyle = Theme.overlayOutline
                ctx.beginPath(); ctx.arc(p.x, p.y, 2, 0, Math.PI*2); ctx.fill()
            }
            ctx.fillStyle = Theme.overlayText
            ctx.font = "11px sans-serif"
            ctx.fillText(String(i+1), p.x+7, p.y-6)
        }
        if (drawing && previewPoint && points.length > 0) {
            const last = points[points.length - 1]
            const a = coordinateMapper.mapDicomPixelToItem(overlay, last.column, last.row)
            const b = coordinateMapper.mapDicomPixelToItem(overlay, previewPoint.column, previewPoint.row)
            ctx.globalAlpha = .65
            ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke()
        }
        ctx.restore()
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
        drawReferenceGuide(ctx)
        if (controller.viewportRole === "curved" && marker >= 0) {
            ctx.globalAlpha = 1
            const a = coordinateMapper.mapDicomPixelToItem(overlay, marker, 0)
            const b = coordinateMapper.mapDicomPixelToItem(overlay, marker, controller.imageRows-1)
            ctx.setLineDash([])
            samplingLine(ctx, a, b)
        }
        ctx.globalAlpha = 1
    }
}
