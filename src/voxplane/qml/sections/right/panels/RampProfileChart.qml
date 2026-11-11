pragma ComponentBehavior: Bound
import QtQuick
import "../../../theme"

Canvas {
    id: chart
    objectName: "rampProfileChart"
    property var result: null
    readonly property color curveColor: Theme.chartX
    readonly property color fitColor: Theme.chartY
    readonly property color textColor: Theme.textMuted
    readonly property string axisTitle: qsTrId("ramp.distanceAxis")
    implicitHeight: 190
    onResultChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onVisibleChanged: { if (visible) requestPaint() }
    onCurveColorChanged: requestPaint()
    onFitColorChanged: requestPaint()
    onTextColorChanged: requestPaint()
    onAxisTitleChanged: requestPaint()
    onPaint: {
        const ctx = getContext("2d")
        ctx.clearRect(0, 0, width, height)
        if (!result || !result.profile || result.profile.length < 2) return
        const fit = result.fitted
        const raw = result.profile.map(value => value - (fit.length ? (result.fitted_background ?? 0) : 0))
        const maximum = Math.max(...(fit.length ? fit : raw))
        if (!(maximum > 0)) return
        const low = Math.min(0, ...raw) / maximum
        const high = Math.max(1, ...raw.map(value => value / maximum)) * 1.05
        const left = 32, top = 22, w = width - 44, h = height - 62
        const px = i => left + i / (raw.length - 1) * w
        const py = v => top + (high - v / maximum) / (high - low) * h
        ctx.font = "10px sans-serif"
        ctx.fillStyle = chart.textColor
        ctx.strokeStyle = chart.textColor
        ctx.lineWidth = .5
        ctx.textAlign = "right"
        for (const value of [0, .5, 1]) {
            const y = py(value * maximum)
            ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(left + w, y); ctx.stroke()
            ctx.fillText(value.toFixed(1), left - 5, y + 3)
        }
        function curve(values, color) {
            if (!values.length) return
            ctx.strokeStyle = color; ctx.lineWidth = 1.8
            ctx.beginPath()
            values.forEach((value, i) => i ? ctx.lineTo(px(i), py(value)) : ctx.moveTo(px(i), py(value)))
            ctx.stroke()
        }
        curve(raw, chart.curveColor)
        ctx.setLineDash([5, 3]); curve(fit, chart.fitColor); ctx.setLineDash([])
        ctx.fillStyle = chart.textColor; ctx.textAlign = "center"
        for (const fraction of [0, .5, 1]) {
            ctx.fillText(((raw.length - 1) * result.spacing * fraction).toFixed(1), left + fraction * w, height - 25)
        }
        ctx.fillText(chart.axisTitle, left + w / 2, height - 7)
        ctx.textAlign = "left"
        ctx.fillText(qsTrId("ramp.profileTitle"), left, 12)
    }
}
