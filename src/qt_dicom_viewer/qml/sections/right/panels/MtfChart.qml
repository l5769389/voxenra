pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import "../../../theme"
import "../../../components" as Components

Canvas {
    id: chart
    objectName: "mtfChart"
    property var result: ({})
    property string frequencyUnit: "lp/mm"
    readonly property color xColor: Theme.chartX
    readonly property color yColor: Theme.chartY
    property bool showX: true
    property bool showY: true
    // 显隐由外层（方向选择器所在的控制器）持有，图例点击只发请求信号。
    signal xToggled()
    signal yToggled()
    implicitHeight: 238
    readonly property string axisTitle: qsTrId("mtf.frequencyAxis").arg(frequencyUnit)
    onAxisTitleChanged: requestPaint()
    onXColorChanged: requestPaint()
    onYColorChanged: requestPaint()
    onResultChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onShowXChanged: requestPaint()
    onShowYChanged: requestPaint()

    // 两行紧凑图例放在图表右上方的留白内，不遮挡高于 1 的曲线。
    Column {
        id: legend
        objectName: "mtfChartLegend"
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.rightMargin: 12
        spacing: 3
        Row {
            anchors.right: parent.right
            spacing: 4
            Components.AppButton {
                id: xLegend
                objectName: "mtfLegend-x"
                Accessible.name: qsTrId("analysis.axisX")
                Accessible.checkable: true
                Accessible.checked: chart.showX
                Accessible.onPressAction: xLegend.click()
                implicitWidth: 43
                implicitHeight: 20
                hoverEnabled: true
                onClicked: chart.xToggled()
                contentItem: Text {
                    text: "━ X"
                    color: chart.xColor
                    opacity: chart.showX ? 1 : 0.35
                    font.pixelSize: 11
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                normalColor: "transparent"
                cornerRadius: 4
                padding: 0
                Components.AppToolTip {
                    visible: parent.hovered
                    delay: 600
                    timeout: 2000
                    text: chart.showX ? qsTrId("text.1136") : qsTrId("text.1137")
                }
            }
            Components.AppButton {
                id: yLegend
                objectName: "mtfLegend-y"
                Accessible.name: qsTrId("analysis.axisY")
                Accessible.checkable: true
                Accessible.checked: chart.showY
                Accessible.onPressAction: yLegend.click()
                implicitWidth: 43
                implicitHeight: 20
                hoverEnabled: true
                onClicked: chart.yToggled()
                contentItem: Text {
                    text: "┄ Y"
                    color: chart.yColor
                    opacity: chart.showY ? 1 : 0.35
                    font.pixelSize: 11
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                normalColor: "transparent"
                cornerRadius: 4
                padding: 0
                Components.AppToolTip {
                    visible: parent.hovered
                    delay: 600
                    timeout: 2000
                    text: chart.showY ? qsTrId("text.1138") : qsTrId("text.1139")
                }
            }
        }
        Text {
            objectName: "mtfThresholdLegend"
            text: "● MTF50    ◆ MTF10"
            color: Theme.textMuted
            font.pixelSize: 11
        }
    }

    onPaint: {
        const ctx = getContext("2d")
        ctx.reset()
        if (!result.x || !result.y || width < 100)
            return
        const axes = [result.x, result.y]
        const colors = [xColor.toString(), yColor.toString()]
        const left = 35, top = Math.max(31, legend.height + 8), w = width - left - 12, h = height - top - 43
        const xmax = Math.max(...axes.map(a => a.frequency[a.frequency.length - 1]))
        let ymax = 1.05
        for (const axis of axes)
            for (const value of axis.mtf)
                ymax = Math.max(ymax, value * 1.05)
        const px = f => left + f / xmax * w
        const py = v => top + h * (1 - v / ymax)
        ctx.font = "11px sans-serif"
        ctx.textBaseline = "middle"
        ctx.fillStyle = Theme.textMuted.toString()
        ctx.fillText("MTF", 1, 11)
        for (const value of [0, 0.1, 0.5, 1]) {
            ctx.strokeStyle = Theme.borderSubtle.toString()
            ctx.lineWidth = 1
            ctx.beginPath(); ctx.moveTo(left, py(value)); ctx.lineTo(left + w, py(value)); ctx.stroke()
            ctx.fillStyle = Theme.textMuted.toString()
            // 响应明显大于 1 时，避免零刻度与 0.1 参考线文字重叠。
            if (value !== 0 || h * 0.1 / ymax >= 12) {
                ctx.textAlign = "right"; ctx.fillText(value.toFixed(1), left - 6, py(value))
            }
        }
        if (ymax > 1.15) {
            ctx.fillText(ymax.toFixed(1), left - 6, top)
        }
        ctx.strokeStyle = Theme.borderStrong.toString()
        ctx.beginPath(); ctx.moveTo(left, top); ctx.lineTo(left, top + h); ctx.lineTo(left + w, top + h); ctx.stroke()
        for (let tick = 0; tick <= 4; ++tick) {
            const value = tick * xmax / 4
            ctx.textAlign = tick === 4 ? "right" : "center"
            ctx.fillStyle = Theme.textMuted.toString()
            ctx.fillText(value.toFixed(2), px(value), top + h + 14)
        }
        ctx.textAlign = "center"
        ctx.fillText(chart.axisTitle, left + w / 2, height - 7)
        for (let direction = 0; direction < 2; ++direction) {
            if ((direction === 0 && !showX) || (direction === 1 && !showY))
                continue
            const axis = axes[direction]
            ctx.strokeStyle = colors[direction]; ctx.lineWidth = 1.8
            ctx.beginPath()
            // Canvas 无需 QtCharts；Y 使用分段虚线，颜色之外仍可辨认方向。
            for (let i = 0; i < axis.mtf.length; ++i) {
                const x = px(axis.frequency[i]), y = py(axis.mtf[i])
                if (i === 0 || (direction === 1 && Math.floor(i / 3) % 2 === 1))
                    ctx.moveTo(x, y)
                else
                    ctx.lineTo(x, y)
            }
            ctx.stroke()
            for (const marker of [{frequency: axis.mtf50, value: 0.5}, {frequency: axis.mtf10, value: 0.1}]) {
                if (marker.frequency === null || marker.frequency === undefined)
                    continue
                const x = px(marker.frequency), y = py(marker.value)
                ctx.fillStyle = colors[direction]
                ctx.beginPath()
                if (marker.value === 0.5)
                    ctx.arc(x, y, 3.5, 0, Math.PI * 2)
                else {
                    ctx.moveTo(x, y - 4); ctx.lineTo(x + 4, y); ctx.lineTo(x, y + 4); ctx.lineTo(x - 4, y); ctx.closePath()
                }
                ctx.fill()
            }
        }
    }
}
