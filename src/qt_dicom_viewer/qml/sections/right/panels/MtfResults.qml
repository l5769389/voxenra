pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../../../theme"
import "../../../components" as Components

ColumnLayout {
    id: panel
    objectName: "mtfResults"
    property var controller: null
    readonly property var settingsController: controller?.settingsController ?? null
    readonly property int decimalPlaces: settingsController?.values.measurement.decimalPlaces ?? 2
    readonly property string frequencyUnit: controller?.frequencyUnit ?? "lp/mm"
    readonly property var result: controller ? controller.currentResult : ({})
    readonly property bool rampMode: controller?.measurementMethod === "ramp"
    readonly property bool ready: rampMode ? result.ramp !== undefined : result.x !== undefined && result.y !== undefined
    readonly property var qualityWarnings: controller?.warnings ?? []
    property bool rampDetailsExpanded: false
    spacing: 14
    onVisibleChanged: { if (!visible && infoPopup) infoPopup.close() }

    Components.AppButton {
        objectName: "recalculateAnalysis"
        Layout.fillWidth: true
        text: qsTrId("analysis.recalculate")
        enabled: !!panel.controller && panel.controller.status !== "calculating" && panel.controller.status !== "editing"
        onClicked: panel.controller.recalculate()
    }

    function metric(value, missing) {
        return value === null || value === undefined || !settingsController ? missing
            : settingsController.formatMeasurement(value, decimalPlaces)
    }

    component SelectorButton: Components.AppButton {
        id: selector
        required property string value
        required property string label
        property bool selected: false
        Accessible.name: label
        Accessible.checkable: true
        Accessible.checked: selected
        Accessible.onPressAction: selector.click()
        Layout.fillWidth: true
        Layout.preferredWidth: 1
        Layout.alignment: Qt.AlignVCenter
        implicitHeight: 32
        contentItem: Text {
            text: selector.label
            color: selector.selected ? Theme.textPrimary : Theme.textSecondary
            font.pixelSize: 12
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            wrapMode: Text.Wrap
        }
        checked: selected
        baseBorderWidth: 1
        baseBorderColor: Theme.controlBorder
        cornerRadius: 5
    }

    component AnalysisSelector: RowLayout {
        Layout.fillWidth: true
        spacing: 6
        Text {
            objectName: "mtfAnalysisMethodLabel"
            Layout.preferredWidth: 52
            Layout.fillHeight: true
            text: qsTrId("text.1142")
            color: Theme.textMuted
            font.pixelSize: 11
            verticalAlignment: Text.AlignVCenter
        }
        Repeater {
            model: panel.controller ? panel.controller.analysisMethods : []
            delegate: SelectorButton {
                required property var modelData
                objectName: "mtfAnalysisMethod-" + modelData.value
                value: modelData.value
                label: modelData.label
                selected: panel.controller?.analysisMethod === value
                onClicked: panel.controller?.setAnalysisMethod(value)
            }
        }
    }

    component AxisSelector: RowLayout {
        Layout.fillWidth: true
        spacing: 6
        Text {
            objectName: "mtfAxesLabel"
            Layout.preferredWidth: 52
            Layout.fillHeight: true
            text: qsTrId("mtf.axes")
            color: Theme.textMuted
            font.pixelSize: 11
            verticalAlignment: Text.AlignVCenter
        }
        SelectorButton {
            objectName: "mtfAxis-x"
            Accessible.name: qsTrId("analysis.axisX")
            value: "x"
            label: "X"
            selected: panel.controller?.showX ?? true
            onClicked: panel.controller?.setShowX(!selected)
        }
        SelectorButton {
            objectName: "mtfAxis-y"
            Accessible.name: qsTrId("analysis.axisY")
            value: "y"
            label: "Y"
            selected: panel.controller?.showY ?? false
            onClicked: panel.controller?.setShowY(!selected)
        }
    }

    Rectangle {
        Layout.fillWidth: true
        implicitHeight: 1
        color: Theme.dividerColor
    }
    RoiGeometryEditor {
        Layout.fillWidth: true
        controller: panel.controller
    }
    RowLayout {
        Layout.fillWidth: true
        visible: !panel.rampMode
        spacing: 6
        Text {
            objectName: "mtfMeasurementMethodLabel"
            Layout.preferredWidth: 52
            Layout.fillHeight: true
            text: qsTrId("text.1141")
            color: Theme.textMuted
            font.pixelSize: 11
            verticalAlignment: Text.AlignVCenter
        }
        Repeater {
            model: panel.controller ? panel.controller.measurementMethods : []
            delegate: SelectorButton {
                required property var modelData
                objectName: "mtfMeasurementMethod-" + modelData.value
                value: modelData.value
                label: modelData.label
                selected: panel.controller?.measurementMethod === value
                onClicked: panel.controller?.setMeasurementMethod(value)
            }
        }
    }
    Text {
        objectName: "fwhmTargetLabel"
        Layout.fillWidth: true
        visible: panel.rampMode
        text: qsTrId("fwhm.targetLabel")
        color: Theme.textSecondary
        font.pixelSize: 12
    }
    AxisSelector { visible: !panel.rampMode }
    RowLayout {
        Layout.fillWidth: true
        visible: panel.rampMode
        spacing: 6
        Text {
            Layout.preferredWidth: 52
            text: qsTrId("ramp.direction")
            color: Theme.textMuted
            font.pixelSize: 11
        }
        Repeater {
            model: [{value: "x", label: qsTrId("ramp.horizontal")}, {value: "y", label: qsTrId("ramp.vertical")}]
            delegate: SelectorButton {
                required property var modelData
                objectName: "rampDirection-" + modelData.value
                value: modelData.value
                label: modelData.label
                selected: panel.controller?.rampDirection === value
                onClicked: panel.controller?.setRampDirection(value)
            }
        }
    }
    Text {
        objectName: "mtfStatus"
        Accessible.role: Accessible.StaticText
        Accessible.name: text
        Layout.fillWidth: true
        visible: text.length > 0
        text: panel.controller ? panel.controller.statusText : qsTrId("text.1143")
        color: Theme.textSecondary
        font.pixelSize: 12
        wrapMode: Text.Wrap
    }
    Text {
        objectName: "mtfError"
        Accessible.role: Accessible.StaticText
        Accessible.name: text
        Layout.fillWidth: true
        visible: text.length > 0
        text: panel.controller ? panel.controller.error : ""
        color: Theme.chartY
        font.pixelSize: 12
        wrapMode: Text.Wrap
    }
    MtfChart {
        Layout.fillWidth: true
        visible: panel.ready && !panel.rampMode
        result: panel.result
        frequencyUnit: panel.frequencyUnit
        showX: panel.controller?.showX ?? true
        showY: panel.controller?.showY ?? true
        onXToggled: panel.controller?.setShowX(!panel.controller.showX)
        onYToggled: panel.controller?.setShowY(!panel.controller.showY)
    }
    RowLayout {
        Layout.fillWidth: true
        Text {
            objectName: "mtfActualMethod"
            Accessible.role: Accessible.StaticText
            Accessible.name: text
            Layout.fillWidth: true
            text: !panel.ready ? "" : panel.controller?.actualAnalysisMethod === "gaussian_equivalent" ? qsTrId("mtf.usedEquivalent")
                : panel.controller?.actualAnalysisMethod === "tukey_fft" ? qsTrId("mtf.usedWeighted")
                : panel.controller?.actualAnalysisMethod === "gaussian" ? qsTrId("mtf.usedGaussian")
                : panel.controller?.actualAnalysisMethod === "half_height" ? qsTrId("ramp.usedHalfHeight")
                : qsTrId("mtf.usedDirect")
            color: Theme.textSecondary
            font.pixelSize: 11
            wrapMode: Text.Wrap
        }
        Components.AppButton {
            id: infoButton
            objectName: "mtfInfoButton"
            Layout.preferredWidth: 22
            Layout.preferredHeight: 22
            Layout.minimumWidth: 22
            Layout.minimumHeight: 22
            implicitWidth: 22
            implicitHeight: 22
            minimumButtonWidth: 22
            leftPadding: 0
            rightPadding: 0
            topPadding: 0
            bottomPadding: 0
            iconName: "info"
            iconSize: 16
            normalColor: "transparent"
            baseBorderWidth: 0
            textColor: panel.qualityWarnings.length ? Theme.warningColor : Theme.textSecondary
            Accessible.name: qsTrId("mtf.details")
            Accessible.description: panel.qualityWarnings.join("\n")
            cornerRadius: Theme.controlRadius
            onClicked: infoPopup.open()
            Components.AppToolTip { text: qsTrId("mtf.details"); visible: infoButton.hovered }
        }
    }
    AnalysisInfoPopup {
        id: infoPopup
        anchorItem: infoButton
        explanation: (panel.rampMode ? qsTrId("ramp.info")
            : panel.controller?.actualAnalysisMethod === "gaussian_equivalent" ? qsTrId("mtf.equivalentHint")
            : panel.controller?.actualAnalysisMethod === "tukey_fft" ? qsTrId("mtf.weightedHint")
            : panel.controller?.analysisMethod === "gaussian" ? qsTrId("mtf.gaussianHint") : qsTrId("mtf.directHint")) + "\n\n" + (panel.controller?.provenance ?? "") + "\n" + qsTrId("analysis.savedHint")
        warnings: panel.qualityWarnings
    }
    Connections {
        target: panel.controller
        function onStateChanged() { if (!panel.ready) infoPopup.close() }
    }
    GridLayout {
        objectName: "rampMetrics"
        Accessible.role: Accessible.StaticText
        Accessible.name: panel.controller?.roiMetricLabel ?? ""
        Layout.fillWidth: true
        visible: panel.ready && panel.rampMode
        columns: 2
        columnSpacing: 8
        rowSpacing: 10
        Text {
            Layout.fillWidth: true
            text: "FWHM · mm"
            horizontalAlignment: Text.AlignHCenter
            font.pixelSize: 11
            color: Theme.textMuted
        }
        Text {
            Layout.fillWidth: true
            text: qsTrId("ramp.thicknessHeader").arg(panel.controller?.rampAngle ?? 23)
            horizontalAlignment: Text.AlignHCenter
            font.pixelSize: 11
            color: Theme.textMuted
        }
        Text {
            objectName: "rampFwhmMetric"
            Layout.fillWidth: true
            text: panel.metric(panel.result.ramp?.fwhm, qsTrId("text.1144"))
            horizontalAlignment: Text.AlignHCenter
            font.pixelSize: 14
            color: Theme.chartX
        }
        Text {
            objectName: "rampThicknessMetric"
            Layout.fillWidth: true
            text: panel.metric(panel.result.ramp?.thickness, qsTrId("text.1144"))
            horizontalAlignment: Text.AlignHCenter
            font.pixelSize: 14
            color: Theme.chartX
        }
    }
    GridLayout {
        objectName: "mtfMetrics"
        Accessible.role: Accessible.StaticText
        Accessible.name: panel.controller?.roiMetricLabel ?? ""
        Layout.fillWidth: true
        visible: panel.ready && !panel.rampMode
        columns: 3
        columnSpacing: 4
        rowSpacing: 12
        Text { text: "" }
        Repeater {
            model: ["MTF50\n" + panel.frequencyUnit, "MTF10\n" + panel.frequencyUnit]
            Text {
                required property string modelData
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                text: modelData
                color: Theme.textMuted
                font.pixelSize: 11
                horizontalAlignment: Text.AlignHCenter
            }
        }
        Repeater {
            // 只显示方向选择器勾选的方向；至少一个方向由控制器保证。
            model: {
                if (!panel.ready || panel.rampMode)
                    return []
                const axes = []
                if (panel.controller?.showX ?? true)
                    axes.push(["X", panel.result.x, Theme.chartX])
                if (panel.controller?.showY ?? true)
                    axes.push(["Y", panel.result.y, Theme.chartY])
                const cells = []
                for (const [name, axis, color] of axes) {
                    cells.push({text: name, color: color, axisCell: true})
                    for (const key of ["mtf50", "mtf10"]) {
                        const missing = (axis.unreliable_metrics ?? []).indexOf(key) >= 0 ? "—" : qsTrId("text.0589")
                        cells.push({text: panel.metric(axis[key], missing), color: color, axisCell: false})
                    }
                }
                return cells
            }
            Text {
                required property var modelData
                required property int index
                objectName: "mtfMetric-" + index
                Layout.fillWidth: !modelData.axisCell
                Layout.preferredWidth: modelData.axisCell ? 14 : 1
                text: modelData.text
                color: modelData.color
                font.pixelSize: 12
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
            }
        }
    }
    Components.AppButton {
        objectName: "rampDetailsToggle"
        Layout.fillWidth: true
        visible: panel.rampMode
        text: (panel.rampDetailsExpanded ? "▾  " : "▸  ") + qsTrId("ramp.details")
        fontPixelSize: 12
        textColor: Theme.textSecondary
        normalColor: "transparent"
        checked: panel.rampDetailsExpanded
        onClicked: panel.rampDetailsExpanded = !panel.rampDetailsExpanded
    }
    AnalysisSelector { visible: panel.rampMode && panel.rampDetailsExpanded }
    RampProfileChart {
        Layout.fillWidth: true
        visible: panel.ready && panel.rampMode && panel.rampDetailsExpanded
        result: panel.result.ramp ?? null
    }

}
