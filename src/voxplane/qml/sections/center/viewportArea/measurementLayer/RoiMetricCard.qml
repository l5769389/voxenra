pragma ComponentBehavior: Bound
import QtQuick
import "../../../../components" as Components
import QtQuick.Layouts
import QtQuick.Controls.Basic as Basic
import "../../../../theme"

Rectangle {
    id: root
    property var visibleMetrics: ({})
    property var settingsController: null
    readonly property int decimalPlaces: settingsController?.values.measurement.decimalPlaces ?? 2
    property int metricFontSize: settingsController?.values.measurement.fontSize ?? 13
    readonly property real cardAlpha: 1 - (settingsController?.values.measurement.cardTransparency ?? 8) / 100
    required property var measurement
    required property color accentColor
    readonly property var metrics: measurement?.metrics ?? ({})
    readonly property var secondary: measurement?.secondaryMetrics ?? null
    readonly property string unitSuffix: metrics.unit ? " " + metrics.unit : ""
    function format(value) {
        return settingsController ? settingsController.formatMeasurement(value, decimalPlaces) : "—"
    }
    // Reserve the geometry value column from font/precision, never from live
    // ROI values. Draft delegates are recreated during editing, so a per-card
    // width cache would still jump between draft/committed states. Oversized
    // values elide with the full value available in the tooltip and accessible
    // name.
    FontMetrics {
        id: geometryFontMetrics
        font.pixelSize: root.metricFontSize
    }
    readonly property string widestDigit: {
        // Reading font establishes the dependency for live font-size changes.
        if (geometryFontMetrics.font.pixelSize <= 0)
            return "0"
        let digit = "0"
        for (let i = 1; i <= 9; ++i) {
            if (geometryFontMetrics.advanceWidth(String(i)) > geometryFontMetrics.advanceWidth(digit))
                digit = String(i)
        }
        return digit
    }
    function numberSample(integerDigits) {
        return widestDigit.repeat(integerDigits) + (decimalPlaces > 0 ? "." + widestDigit.repeat(decimalPlaces) : "")
    }
    TextMetrics {
        id: dimensionsMetrics
        font.pixelSize: root.metricFontSize
        text: root.numberSample(3) + " × " + root.numberSample(3) + " mm"
    }
    TextMetrics {
        id: areaMetrics
        font.pixelSize: root.metricFontSize
        text: root.numberSample(6) + " mm²"
    }
    readonly property real dimensionsWidth: Math.ceil(dimensionsMetrics.advanceWidth)
    readonly property real areaWidth: Math.ceil(areaMetrics.advanceWidth)
    readonly property var geometryRows: [
        {key: "dimensions", label: measurement?.type === "ellipse" ? "D1 × D2" : "W × H", value: format(metrics.width_mm) + " × " + format(metrics.height_mm) + " mm", reservedWidth: dimensionsWidth},
        {key: "area", label: "Area", value: format(metrics.area_mm2) + " mm²", reservedWidth: areaWidth}
    ].filter(row => root.visibleMetrics[row.key] !== false)
    // Stacked values share one column, so its reservation is the widest row.
    readonly property real geometryReservedWidth: root.geometryRows.reduce((widest, row) => Math.max(widest, row.reservedWidth), 0)
    readonly property bool showIntensity: ["mean", "std", "minimum", "maximum", "count"]
        .some(key => root.visibleMetrics[key] !== false)
    function intensityRows(values, prefix, suffix) {
        const count = Number(values.pixel_count ?? 0)
        const rows = count > 0 ? [
            {key: "mean", label: prefix + "Mean", value: format(values.mean) + suffix},
            {key: "std", label: prefix + "SD", value: format(values.std) + suffix},
            {key: "minimum", label: prefix + "Min", value: format(values.minimum) + suffix},
            {key: "maximum", label: prefix + "Max", value: format(values.maximum) + suffix}
        ] : []
        rows.push({key: "count", label: prefix + "Pixels", value: String(count)})
        return rows
    }
    readonly property var rows: (measurement?.type === "freehand"
        ? [{key: "perimeter", label: "Perimeter", value: format(metrics.perimeter_mm) + " mm"}] : [])
        .concat(intensityRows(metrics, "", unitSuffix))
        .concat(secondary ? intensityRows(secondary, "CT ", " HU") : [])
        .filter(row => root.visibleMetrics[row.key] !== false)
    readonly property string emptySampleText: {
        if (!showIntensity) return ""
        const missingPrimary = Number(metrics.pixel_count ?? 0) === 0
        const missingSecondary = secondary && Number(secondary.pixel_count ?? 0) === 0
        if (missingPrimary && (!secondary || missingSecondary)) return qsTrId("measurement.noValidPixels")
        if (missingPrimary) return "PET: " + qsTrId("measurement.noValidPixels")
        if (missingSecondary) return "CT: " + qsTrId("measurement.noValidPixels")
        return ""
    }
    TextMetrics {
        id: geometryLabelMetrics
        font.pixelSize: root.metricFontSize
        text: root.visibleMetrics.dimensions !== false ? "Size" : "Area"
    }
    implicitWidth: Math.max(238, root.geometryRows.length > 0
        ? Math.ceil(geometryLabelMetrics.advanceWidth) + root.geometryReservedWidth + 8 + 20
        : 0)
    implicitHeight: content.implicitHeight + 20
    height: implicitHeight
    radius: 6
    color: Qt.rgba(0.035, 0.065, 0.095, root.cardAlpha)
    border.width: 1
    border.color: Qt.rgba(accentColor.r, accentColor.g, accentColor.b, 0.55)

    ColumnLayout {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 10
        spacing: 5
        RowLayout {
            id: geometryFlow
            Layout.fillWidth: true
            visible: root.geometryRows.length > 0
            spacing: 8
            Text {
                objectName: "roiGeometryLabel"
                text: geometryLabelMetrics.text
                color: Theme.overlayMuted
                font.pixelSize: root.metricFontSize
            }
            ColumnLayout {
                id: geometryStack
                Layout.fillWidth: true
                Layout.preferredWidth: root.geometryReservedWidth
                spacing: 2
                Repeater {
                    model: root.geometryRows
                    delegate: Text {
                        id: geometryValue
                        required property var modelData
                        objectName: "roiGeometry-" + modelData.key
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        elide: Text.ElideRight
                        horizontalAlignment: Text.AlignRight
                        text: modelData.value
                        font.pixelSize: root.metricFontSize
                        color: Theme.overlayText
                        Accessible.name: modelData.label + " " + modelData.value
                        Components.AppToolTip {
                            text: geometryValue.modelData.label + " " + geometryValue.modelData.value
                            requested: hover.hovered
                        }
                        HoverHandler { id: hover }
                    }
                }
            }
        }
        Text {
            objectName: "roiNoValidSamples"
            Layout.fillWidth: true
            visible: text.length > 0
            text: root.emptySampleText
            color: Theme.overlayMuted
            font.pixelSize: root.metricFontSize
            wrapMode: Text.Wrap
            Accessible.name: text
        }
        Repeater {
            model: root.rows
            RowLayout {
                id: metricRow
                required property var modelData
                Layout.fillWidth: true
                spacing: 8
                Text { Layout.minimumWidth: 0; Layout.preferredWidth: implicitWidth; wrapMode: Text.Wrap; text: metricRow.modelData.label; color: Theme.overlayMuted; font.pixelSize: root.metricFontSize }
                Text {
                    Layout.fillWidth: true
                    text: metricRow.modelData.value
                    color: Theme.overlayText
                    font.pixelSize: root.metricFontSize
                    horizontalAlignment: Text.AlignRight
                    wrapMode: Text.Wrap
                    Layout.minimumWidth: 0
                }
            }
        }
    }
}
