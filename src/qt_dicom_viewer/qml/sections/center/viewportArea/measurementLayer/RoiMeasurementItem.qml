pragma ComponentBehavior: Bound
import QtQuick
import "../LabelPlacement.js" as LabelPlacement
import QtQuick.Shapes
import "../../../../theme"

Item {
    id: root
    property var preferences: ({})
    property var settingsController: null
    readonly property var styleSettings: preferences.measurement ?? ({})
    property bool draftStyle: isDraft
    readonly property bool dashed: Theme.drawingLineDashed(styleSettings, draftStyle)
    property var labelPosition: null
    property var reservedRegions: []
    required property var measurement
    property var controlPoints: corners
    required property var corners
    required property bool isDraft
    required property bool isSelected
    property bool showMetrics: true
    readonly property bool expandedMetrics: showMetrics && (isDraft || isSelected)
    property string shortLabel: ""
    property var avoidanceRegions: []
    readonly property bool compactAnalysis: width < 420 || height < 360
    readonly property string analysisLabel: compactAnalysis
        ? shortLabel.split("\n")[0].split(" · ")[0] : shortLabel
    readonly property string compactTextLabel: showMetrics
        ? [measurement?.name || measurement?.label || "ROI",
           preferences.roi?.area === false ? "" : metricCard.format(measurement?.metrics?.area_mm2) + " mm²"].filter(Boolean).join(" · ")
        : analysisLabel

    // Keep automatic badges inside the direction markers and choose the least
    // obstructed side. Explicit user placement is retained by the bindings below.
    function analysisLabelPosition(labelWidth, labelHeight) {
        const margin = 28, gap = 10
        const maxX = Math.max(4, width - labelWidth - margin)
        const maxY = Math.max(4, height - labelHeight - margin)
        const clamp = p => ({x: Math.max(Math.min(margin, maxX), Math.min(maxX, p.x)),
                             y: Math.max(Math.min(margin, maxY), Math.min(maxY, p.y))})
        const bottom = (corners?.length ?? 0) ? Math.max(...corners.map(p => p.y)) : topEdge
        const center = (leftEdge + rightEdge - labelWidth) / 2
        const candidates = [
            {x: rightEdge + gap, y: topEdge},
            {x: leftEdge - labelWidth - gap, y: topEdge},
            {x: center, y: bottom + gap},
            {x: center, y: topEdge - labelHeight - gap},
            {x: margin, y: margin}, {x: maxX, y: margin},
            {x: margin, y: maxY}, {x: maxX, y: maxY}
        ].map(clamp)
        const obstacles = [{x: leftEdge - gap, y: topEdge - gap,
                            width: rightEdge - leftEdge + 2 * gap,
                            height: bottom - topEdge + 2 * gap}].concat(avoidanceRegions)
        let best = candidates[0], bestScore = Infinity
        for (const candidate of candidates) {
            let score = 0
            for (const obstacle of obstacles) {
                score += Math.max(0, Math.min(candidate.x + labelWidth, obstacle.x + obstacle.width) - Math.max(candidate.x, obstacle.x))
                    * Math.max(0, Math.min(candidate.y + labelHeight, obstacle.y + obstacle.height) - Math.max(candidate.y, obstacle.y))
            }
            if (score < bestScore) { best = candidate; bestScore = score }
        }
        return best
    }
    readonly property Item labelItem: expandedMetrics ? metricCard : compactLabel
    readonly property color lineColor: Theme.drawingLineColor(styleSettings, draftStyle)

    readonly property string outlinePath: {
        if (!root.corners)
            return ""
        if (root.measurement?.type === "freehand")
            return root.corners.length ? "M " + root.corners.map(p => p.x + " " + p.y).join(" L ") + (root.corners.length >= 3 ? " Z" : "") : ""
        if (root.corners.length !== 4)
            return ""
        const p = root.corners
        const xy = point => point.x + " " + point.y
        if (root.measurement?.type === "rect")
            return "M " + xy(p[0]) + " L " + xy(p[1]) + " L " + xy(p[2]) + " L " + xy(p[3]) + " Z"
        // 用映射后的两条半轴构造贝塞尔椭圆，旋转/镜像/非等距像素均保持对齐。
        const cx = (p[0].x + p[2].x) / 2, cy = (p[0].y + p[2].y) / 2
        const ux = (p[1].x - p[0].x) / 2, uy = (p[1].y - p[0].y) / 2
        const vx = (p[3].x - p[0].x) / 2, vy = (p[3].y - p[0].y) / 2
        const point = (u, v) => (cx + u * ux + v * vx) + " " + (cy + u * uy + v * vy)
        const k = 0.5522847498
        return "M " + point(1, 0)
            + " C " + point(1, k) + " " + point(k, 1) + " " + point(0, 1)
            + " C " + point(-k, 1) + " " + point(-1, k) + " " + point(-1, 0)
            + " C " + point(-1, -k) + " " + point(-k, -1) + " " + point(0, -1)
            + " C " + point(k, -1) + " " + point(1, -k) + " " + point(1, 0) + " Z"
    }
    readonly property real rightEdge: (corners?.length ?? 0) ? Math.max(...corners.map(p => p.x)) : 0
    readonly property real leftEdge: (corners?.length ?? 0) ? Math.min(...corners.map(p => p.x)) : 0
    readonly property real topEdge: (corners?.length ?? 0) ? Math.min(...corners.map(p => p.y)) : 0

    Shape {
        preferredRendererType: Shape.CurveRenderer
        antialiasing: true
        anchors.fill: parent
        ShapePath {
            strokeColor: root.lineColor
            strokeWidth: root.styleSettings.lineWidth ?? 1.5
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            strokeStyle: root.dashed ? ShapePath.DashLine : ShapePath.SolidLine
            dashPattern: [4, 2]
            PathSvg { path: root.outlinePath }
        }
    }
    Repeater {
        model: root.measurement?.type === "freehand" ? root.controlPoints : root.corners
        Rectangle {
            required property var modelData
            objectName: "roiHandle"
            width: 6; height: 6; radius: 1
            x: modelData.x - 3; y: modelData.y - 3
            visible: root.isDraft || root.isSelected
            color: Theme.panelBackground
            border.color: root.lineColor
            border.width: 1.5
        }
    }
    RoiMetricCard {
        id: metricCard
        settingsController: root.settingsController
        objectName: "roiMetricCard"
        visible: root.expandedMetrics && root.measurement?.metricsReady !== false && (root.corners?.length ?? 0) >= 3
                 && !(root.measurement?.creating && root.measurement?.type === "freehand")
        measurement: root.measurement
        accentColor: root.lineColor
        visibleMetrics: root.preferences.roi ?? ({})
        metricFontSize: root.styleSettings.fontSize ?? 13
        width: Math.max(0, Math.min(implicitWidth, root.width - 16))
        readonly property var displayPosition: LabelPlacement.place(root.labelPosition || root.analysisLabelPosition(width, height),
            width, height, root.width, root.height, root.reservedRegions, root.avoidanceRegions, !!root.labelPosition)
        x: displayPosition.x
        y: displayPosition.y
    }
    Rectangle {
        id: compactLabel
        objectName: root.showMetrics ? "roiCompactLabel" : "mtfRoiMetricBadge"
        readonly property string text: root.compactTextLabel
        visible: !root.expandedMetrics && root.measurement?.metricsReady !== false && (root.corners?.length ?? 0) >= 3 && text.length > 0
                 && !(root.measurement?.creating && root.measurement?.type === "freehand")
        implicitWidth: compactText.implicitWidth + 14
        width: Math.min(implicitWidth, Math.max(0, root.width - 56))
        implicitHeight: compactText.implicitHeight + 8
        readonly property var displayPosition: LabelPlacement.place(root.labelPosition || root.analysisLabelPosition(width, height),
            width, height, root.width, root.height, root.reservedRegions, root.avoidanceRegions, !!root.labelPosition)
        x: displayPosition.x
        y: displayPosition.y
        Accessible.role: Accessible.StaticText
        Accessible.name: text
        color: Qt.rgba(0.035, 0.065, 0.095, 1 - (root.styleSettings.cardTransparency ?? 8) / 100)
        border.width: 1
        border.color: root.lineColor
        radius: 4

        Text {
            id: compactText
            width: Math.max(0, compactLabel.width - 14)
            wrapMode: root.showMetrics || root.compactAnalysis ? Text.NoWrap : Text.Wrap
            elide: root.showMetrics || root.compactAnalysis ? Text.ElideRight : Text.ElideNone
            objectName: "mtfRoiLabel"
            anchors.centerIn: parent
            text: compactLabel.text
            color: Theme.overlayText
            font.pixelSize: root.styleSettings.fontSize ?? 13
            font.weight: Font.DemiBold
            lineHeight: 1.2
        }
    }
}
