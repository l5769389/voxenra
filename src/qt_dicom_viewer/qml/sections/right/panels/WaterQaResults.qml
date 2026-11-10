pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic as Basic
import "../../../theme"
import "../../../components" as Components

ColumnLayout {
    id: panel
    objectName: "waterQaResults"
    property var controller: null
    property Item exportItem: null
    readonly property var settingsController: controller?.settingsController ?? null
    readonly property int decimalPlaces: settingsController?.values.measurement.decimalPlaces ?? 2
    readonly property var result: controller ? controller.displayResult : ({})
    readonly property bool ready: result.rois !== undefined
    readonly property bool editing: !!controller && (controller.dragging || controller.status !== "ready")
    readonly property string inputContext: (controller?.frameToken ?? "") + "|" + (controller?.status ?? "")
    readonly property bool inputReady: !!controller && controller.available
        && controller.frameToken.length > 0 && !["waiting", "calculating"].includes(controller.status)
    readonly property string group: controller?.activeGroup ?? "uniformity"
    property bool parametersExpanded: false
    spacing: 10

    RowLayout {
        Layout.fillWidth: true
        Components.AppButton {
            objectName: "qaWaterTab"
            Layout.fillWidth: true
            text: qsTrId("qa.waterTab")
            Accessible.role: Accessible.RadioButton
            Accessible.checkable: true
            Accessible.checked: checked
            checked: panel.group !== "air"
            onClicked: panel.controller.setActiveGroup("uniformity")
        }
        Components.AppButton {
            objectName: "qaAirTab"
            Layout.fillWidth: true
            text: qsTrId("qa.airTab")
            Accessible.role: Accessible.RadioButton
            Accessible.checkable: true
            Accessible.checked: checked
            checked: panel.group === "air"
            onClicked: panel.controller.setActiveGroup("air")
        }
    }
    RowLayout {
        Layout.fillWidth: true
        visible: panel.group !== "air"
        Repeater {
            model: [{key:"uniformity", label:qsTrId("qa.uniformityGroup")},
                    {key:"noise", label:qsTrId("qa.noiseGroup")}]
            Components.AppButton {
                required property var modelData
                objectName: "qaGroup-" + modelData.key
                Layout.fillWidth: true
                Accessible.role: Accessible.RadioButton
                Accessible.checkable: true
                Accessible.checked: checked
                checked: panel.group === modelData.key
                text: modelData.label
                onClicked: panel.controller.setActiveGroup(modelData.key)
            }
        }
    }
    Text {
        Layout.fillWidth: true
        visible: panel.group === "air"
        text: panel.controller?.placingAir ? qsTrId("qa.placeAir") : qsTrId("qa.airHint")
        color: Theme.textSecondary
        wrapMode: Text.Wrap
        font.pixelSize: 12
    }
    Components.AppButton {
        objectName: "qaAddAir"
        Layout.fillWidth: true
        visible: panel.group === "air"
        text: qsTrId("qa.addAir")
        checked: panel.controller?.placingAir ?? false
        enabled: panel.ready && !panel.editing
        onClicked: {
            panel.controller.placeAirRoi()
            if (panel.controller.placingAir && panel.exportItem) panel.exportItem.forceActiveFocus()
        }
    }
    function metric(value) {
        if (value === null || value === undefined) return "—"
        return settingsController ? settingsController.formatMeasurement(value, decimalPlaces) : "—"
    }

    signal manualRequested()

    component ActionButton: Components.AppButton {
        compact: true
        momentary: true
        fontPixelSize: 12
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 4
        Text {
            objectName: "waterQaModeTitle"
            Layout.fillWidth: true
            text: panel.ready && !panel.result.phantom ? qsTrId("qa.circularRois") : qsTrId("text.1072")
            color: Theme.textPrimary
            font.pixelSize: 14
            font.weight: Font.DemiBold
        }
        Components.ToolbarAction {
            buttonObjectName: "waterQaManualButton"
            Layout.preferredWidth: 26
            Layout.preferredHeight: 26
            label: qsTrId("text.1073")
            iconName: "manual"
            iconSize: 18
            onTriggered: panel.manualRequested()
        }
        Text {
            objectName: "waterQaPhantomSize"
            visible: panel.ready && !!panel.result.phantom
            text: panel.ready && panel.result.phantom ? "Ø " + panel.metric(panel.result.phantom.radius_mm*2) + " mm" : ""
            color: Theme.textMuted
            font.pixelSize: 11
        }
    }
    Text {
        objectName: "waterQaStatus"
        Layout.fillWidth: true
        text: panel.controller ? panel.controller.statusText : qsTrId("text.1074")
        visible: text.length > 0 && !panel.ready
        color: Theme.textSecondary
        wrapMode: Text.Wrap
        font.pixelSize: 12
    }


    Text {
        objectName: "waterQaError"
        Layout.fillWidth: true
        visible: text.length > 0
        text: panel.controller ? panel.controller.error : ""
        color: Theme.warningColor
        wrapMode: Text.Wrap
        font.pixelSize: 12
    }
    GridLayout {
        objectName: "waterQaMetrics"
        Layout.fillWidth: true
        visible: panel.ready && panel.group !== "air" && !!panel.result.phantom
        columns: 2
        uniformCellWidths: true
        columnSpacing: 8
        rowSpacing: 10
        Repeater {
            model: panel.ready ? [
                {key: "water_ct_hu", label: qsTrId("text.1079")},
                {key: "noise_hu", label: qsTrId("qa.noiseSd")},
                {key: "noise_percent", label: qsTrId("qa.noisePercent")},
                {key: "uniformity_hu", label: qsTrId("text.1081")},
                {key: "consistency_range_hu", label: qsTrId("text.1082")},
                {key: "horizontal_difference_hu", label: qsTrId("text.1083")},
                {key: "vertical_difference_hu", label: qsTrId("text.1084")}
            ].filter(item => (panel.group === "noise" ? ["noise_hu", "noise_percent"].includes(item.key) : !["noise_hu", "noise_percent"].includes(item.key))
                && panel.result[item.key] !== null && panel.result[item.key] !== undefined) : []
            delegate: ColumnLayout {
                id: metric
                required property var modelData
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                spacing: 4
                Text {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    objectName: "waterQaMetricLabel-" + metric.modelData.key
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    text: metric.modelData.label
                    color: Theme.textSecondary
                    font.pixelSize: 12
                }
                Text {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    objectName: "waterQaMetric-" + metric.modelData.key
                    text: panel.editing ? "—" : panel.metric(panel.result[metric.modelData.key]) + (metric.modelData.key === "noise_percent" ? " %" : " HU")
                    color: Theme.textPrimary
                    font.pixelSize: 16
                    font.weight: Font.DemiBold
                }
            }
        }
    }

    Components.AppButton {
        objectName: "qaParameters"
        Layout.fillWidth: true
        text: qsTrId("qa.parameters")
        iconName: panel.parametersExpanded ? "chevron-up" : "chevron-down"
        onClicked: panel.parametersExpanded = !panel.parametersExpanded
    }
    ColumnLayout {
        Layout.fillWidth: true
        visible: panel.parametersExpanded
    Repeater {
        model: [
            { field: "activeDiameterMm", label: qsTrId("qa.activeDiameter"), minimum: 2},
            { field: "edgeClearanceMm", label: qsTrId("text.1076"), minimum: 0}
        ]
        delegate: RowLayout {
            id: setting
            required property var modelData
            Layout.fillWidth: true
            visible: setting.modelData.field !== "edgeClearanceMm" || panel.group === "uniformity"
            spacing: 8
            Text {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                wrapMode: Text.Wrap
                text: setting.modelData.label
                color: Theme.textSecondary
                font.pixelSize: 12
            }
            Basic.SpinBox {
                id: number
                objectName: "waterQaSetting-" + (setting.modelData.field === "activeDiameterMm" ? "roiDiameterMm" : setting.modelData.field)
                Layout.preferredWidth: 92
                implicitHeight: 30
                from: setting.modelData.minimum * 10
                to: setting.modelData.field === "activeDiameterMm"
                    ? Math.max(20, Math.floor((panel.controller?.maximumRoiDiameterMm ?? 100)*10)) : 1000
                value: Math.round((panel.controller ? panel.controller[setting.modelData.field] : 20)*10)
                enabled: panel.inputReady && (setting.modelData.field !== "edgeClearanceMm"
                    || !panel.ready || (!!panel.result.phantom && panel.result.rois.some(r => ["left", "right", "top", "bottom"].includes(r.key))))
                editable: true
                live: false
                readonly property var editContext: [panel.controller, panel.inputContext, panel.group]
                stepSize: 10
                function modelValue() { return Math.round((panel.controller ? panel.controller[setting.modelData.field] : 20)*10) }
                textFromValue: function(value, locale) { return Number(value/10).toLocaleString(locale, "f", 1) }
                valueFromText: function(text, locale) { return Math.round(Number.fromLocaleString(locale, text)*10) }
                validator: DoubleValidator { bottom: number.from/10; top: number.to/10; decimals: 1; locale: number.locale.name }
                function discardDraft() {
                    value = Qt.binding(function() { return number.modelValue() })
                    contentItem.text = textFromValue(modelValue(), locale)
                }
                onEditContextChanged: discardDraft()
                onEnabledChanged: if (!enabled) discardDraft()
                onVisibleChanged: if (!visible) discardDraft()
                Accessible.description: qsTrId("numeric.commitHint")
                Components.AppToolTip { requested: number.hovered; text: number.Accessible.description }
                leftPadding: 24
                rightPadding: 24
                onValueModified: {
                    // Disabling can finish the TextInput before enabledChanged arrives.
                    if (!enabled || !visible || !panel.inputReady) { discardDraft(); return }
                    if (setting.modelData.field === "activeDiameterMm")
                        panel.controller.setActiveDiameterMm(value/10)
                    else
                        panel.controller.setEdgeClearanceMm(value/10)
                }
                contentItem: TextInput {
                    text: number.textFromValue(number.value, number.locale)
                    color: number.enabled ? Theme.textPrimary : Theme.textDisabled
                    font.pixelSize: 12
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    readOnly: !number.editable
                    validator: number.validator
                    inputMethodHints: Qt.ImhDigitsOnly
                    selectByMouse: true
                    Keys.onEscapePressed: event => { number.discardDraft(); event.accepted = true }
                }
                up.indicator: Rectangle {
                    x: number.width-width
                    width: 22; height: number.height
                    color: number.up.pressed ? Theme.selectionBackground : "transparent"
                    Text { anchors.centerIn: parent; text: "+"; color: Theme.textSecondary }
                }
                down.indicator: Rectangle {
                    width: 22; height: number.height
                    color: number.down.pressed ? Theme.selectionBackground : "transparent"
                    Text { anchors.centerIn: parent; text: "−"; color: Theme.textSecondary }
                }
                background: Rectangle {
                    radius: 5
                    color: Theme.controlBackground
                    border.width: 1
                    border.color: number.visualFocus ? Theme.focusBorder : Theme.inputBorder
                }
            }
        }
    }

    ActionButton {
        objectName: "waterQa-analyze"
        Layout.fillWidth: true
        visible: panel.group !== "air"
        text: qsTrId("qa.regenerateGroup")
        enabled: !!panel.controller && panel.controller.available
            && !["calculating", "waiting"].includes(panel.controller.status) && !panel.controller.dragging
        onClicked: panel.controller.regenerateRois()
    }
        Text {
            Layout.fillWidth: true
            visible: panel.group !== "air"
            text: qsTrId("qa.samplingBasis")
            color: Theme.textMuted
            font.pixelSize: 11
            wrapMode: Text.Wrap
        }
    }
    Text {
        Layout.fillWidth: true
        visible: text.length > 0
        text: panel.group === "air" && panel.ready && panel.result.rois.some(r => r.group === "air" && r.maximum_hu > -300)
            ? qsTrId("qa.airContents") : panel.controller?.notice ?? ""
        color: Theme.textMuted
        font.pixelSize: 11
        wrapMode: Text.Wrap
    }
    ColumnLayout {
        objectName: "waterQaRoiTable"
        Layout.fillWidth: true
        visible: panel.ready
        spacing: 8
        RowLayout {
            Layout.fillWidth: true
            spacing: 2
            Text {
                text: qsTrId("text.1085")
                color: Theme.textSecondary
                font.pixelSize: 12
            }
            Item { Layout.fillWidth: true }
            Text { text: "HU"; color: Theme.textMuted; font.pixelSize: 10 }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 4
            Repeater {
                model: panel.group === "uniformity" ? ["ROI", qsTrId("text.0173"), "SD", qsTrId("text.1086")]
                    : ["ROI", qsTrId("text.0173"), "SD"]
                Text {
                    required property string modelData
                    required property int index
                    Layout.fillWidth: true
                    Layout.preferredWidth: panel.group !== "uniformity" && index === 1 ? 1.3 : 1
                    text: modelData
                    color: Theme.textMuted
                    font.pixelSize: 10
                    horizontalAlignment: Text.AlignHCenter
                }
            }
            Item { Layout.preferredWidth: panel.group === "noise" ? 28 : 60 }
        }
        Repeater {
            model: panel.ready ? panel.result.rois.filter(r => (r.group ?? "uniformity") === panel.group) : []
            delegate: RowLayout {
                id: row
                required property var modelData
                objectName: "waterQaRow-" + modelData.key
                Layout.fillWidth: true
                spacing: 4
                Repeater {
                    model: (panel.editing ? [row.modelData.label, "—", "—", "—"]
                        : [row.modelData.label, panel.metric(row.modelData.mean_hu),
                        panel.metric(row.modelData.std_hu), panel.metric(row.modelData.delta_center_hu)])
                            .slice(0, panel.group === "uniformity" ? 4 : 3)
                    Text {
                        id: cell
                        required property string modelData
                        required property int index
                        objectName: "waterQaCell-" + row.modelData.key + "-" + index
                        Layout.fillWidth: true
                        Layout.preferredWidth: panel.group !== "uniformity" && index === 1 ? 1.3 : 1
                        Layout.minimumWidth: 0
                        elide: Text.ElideRight
                        text: modelData
                        color: Theme.textSecondary
                        font.pixelSize: 12
                        horizontalAlignment: Text.AlignHCenter
                        Components.AppToolTip { text: cell.text; requested: cell.truncated && cellHover.hovered }
                        HoverHandler { id: cellHover }
                    }
                }
                Components.AppButton {
                    id: copyButton
                    objectName: "waterQaCopy-" + row.modelData.key
                    Layout.preferredWidth: 28
                    implicitHeight: 28
                    minimumButtonWidth: 28
                    leftPadding: 0; rightPadding: 0; topPadding: 0; bottomPadding: 0
                    iconName: "copy"
                    iconSize: 15
                    enabled: !panel.editing
                    visible: panel.group !== "noise"
                    Accessible.name: qsTrId("qa.copyRoi") + " " + row.modelData.label
                    onClicked: panel.controller.copyRoi(row.modelData.key)
                    Components.AppToolTip { text: qsTrId("qa.copyRoi"); requested: copyButton.hovered }
                }
                Components.AppButton {
                    id: deleteButton
                    objectName: "waterQaDelete-" + row.modelData.key
                    Layout.preferredWidth: 28
                    implicitHeight: 28
                    minimumButtonWidth: 28
                    leftPadding: 0; rightPadding: 0; topPadding: 0; bottomPadding: 0
                    iconName: "delete"
                    iconSize: 15
                    enabled: !panel.editing && row.modelData.removable
                    Accessible.name: qsTrId("qa.deleteRoi") + " " + row.modelData.label
                    onClicked: panel.controller.deleteRoi(row.modelData.key)
                    Components.AppToolTip { text: qsTrId("qa.deleteRoi"); requested: deleteButton.hovered }
                }
            }
        }

    }

    Components.AppButton {
        id: calculateButton
        objectName: "recalculateQa"
        Layout.fillWidth: true
        text: panel.controller?.status === "calculating" ? qsTrId("qa.calculating") : qsTrId("qa.calculate")
        enabled: panel.inputReady && !panel.controller.dragging
        onClicked: panel.controller.analyze()
        Components.AppToolTip { text: qsTrId("qa.calculateHint"); requested: calculateButton.hovered }
    }
    Text {
        objectName: "qaReportMessage"
        Layout.fillWidth: true
        text: panel.controller?.reportMessage ?? ""
        visible: text.length > 0
        wrapMode: Text.Wrap
        color: panel.controller?.reportError ? Theme.warningColor : Theme.textSecondary
    }
    Components.AppButton {
        Layout.fillWidth: true
        visible: !!panel.controller?.reportMessage && !panel.controller?.reportError
        text: qsTrId("qa.reportLocation")
        onClicked: panel.controller.openReportLocation()
    }
}
