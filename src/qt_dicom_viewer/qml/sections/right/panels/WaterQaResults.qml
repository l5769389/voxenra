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
    readonly property var settingsController: controller?.settingsController ?? null
    readonly property int decimalPlaces: settingsController?.values.measurement.decimalPlaces ?? 2
    readonly property var result: controller ? controller.currentResult : ({})
    readonly property bool ready: result.rois !== undefined
    readonly property bool editing: controller ? controller.dragging : false
    spacing: 10

    RowLayout {
        Layout.fillWidth: true
        Components.AppButton {
            objectName: "recalculateQa"
            Layout.fillWidth: true
            text: qsTrId("analysis.recalculate")
            enabled: !!panel.controller && panel.controller.status !== "calculating" && !panel.editing
            onClicked: panel.controller.analyze()
        }
        Components.AppButton {
            id: provenanceButton
            text: "ⓘ"
            Accessible.description: qsTrId("mtf.details")
            onClicked: provenancePopup.open()
        }
    }
    AnalysisInfoPopup {
        id: provenancePopup
        anchorItem: provenanceButton
        explanation: (panel.controller?.provenance ?? "") + "\n" + qsTrId("analysis.savedHint")
        warnings: []
    }

    function metric(value) {
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
            Layout.fillWidth: true
            text: qsTrId("text.1072")
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
            visible: panel.ready
            text: panel.ready ? "Ø " + panel.metric(panel.result.phantom.radius_mm*2) + " mm" : ""
            color: Theme.textMuted
            font.pixelSize: 11
        }
    }
    Text {
        objectName: "waterQaStatus"
        Layout.fillWidth: true
        text: panel.controller ? panel.controller.statusText : qsTrId("text.1074")
        visible: text.length > 0
        color: Theme.textSecondary
        wrapMode: Text.Wrap
        font.pixelSize: 12
    }

    Repeater {
        model: [
            { field: "roiDiameterMm", label: qsTrId("text.1075"), minimum: 2},
            { field: "edgeClearanceMm", label: qsTrId("text.1076"), minimum: 0}
        ]
        delegate: RowLayout {
            id: setting
            required property var modelData
            Layout.fillWidth: true
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
                objectName: "waterQaSetting-" + setting.modelData.field
                Layout.preferredWidth: 92
                implicitHeight: 30
                from: setting.modelData.minimum
                to: 100
                value: panel.controller ? panel.controller[setting.modelData.field] : 20
                enabled: !!panel.controller && panel.controller.available
                editable: true
                leftPadding: 24
                rightPadding: 24
                onValueModified: {
                    if (setting.modelData.field === "roiDiameterMm")
                        panel.controller.setRoiDiameterMm(value)
                    else
                        panel.controller.setEdgeClearanceMm(value)
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
        text: panel.ready ? qsTrId("text.1077") : qsTrId("text.1078")
        enabled: !!panel.controller && panel.controller.available && panel.controller.status !== "calculating"
        onClicked: panel.controller.analyze()
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
        visible: panel.ready
        columns: 2
        uniformCellWidths: true
        columnSpacing: 8
        rowSpacing: 10
        Repeater {
            model: panel.ready ? [
                {key: "water_ct_hu", label: qsTrId("text.1079")},
                {key: "noise_hu", label: qsTrId("text.1080")},
                {key: "uniformity_hu", label: qsTrId("text.1081")},
                {key: "consistency_range_hu", label: qsTrId("text.1082")},
                {key: "horizontal_difference_hu", label: qsTrId("text.1083")},
                {key: "vertical_difference_hu", label: qsTrId("text.1084")}
            ] : []
            delegate: ColumnLayout {
                id: metric
                required property var modelData
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                spacing: 4
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    Text {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        wrapMode: Text.Wrap
                        text: metric.modelData.label
                        color: Theme.textSecondary
                        font.pixelSize: 12
                    }
                    Item { Layout.fillWidth: true }
                }
                Text {
                    Layout.fillWidth: true
                    objectName: "waterQaMetric-" + metric.modelData.key
                    text: panel.editing ? "—" : panel.metric(panel.result[metric.modelData.key]) + " HU"
                    color: Theme.textPrimary
                    font.pixelSize: 16
                    font.weight: Font.DemiBold
                }
            }
        }
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
                model: ["ROI", qsTrId("text.0173"), "SD", qsTrId("text.1086")]
                Text {
                    required property string modelData
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    text: modelData
                    color: Theme.textMuted
                    font.pixelSize: 10
                    horizontalAlignment: Text.AlignHCenter
                }
            }
            Item { Layout.preferredWidth: 60 }
        }
        Repeater {
            model: panel.ready ? panel.result.rois : []
            delegate: RowLayout {
                id: row
                required property var modelData
                objectName: "waterQaRow-" + modelData.key
                Layout.fillWidth: true
                spacing: 4
                Repeater {
                    model: panel.editing ? [row.modelData.label, "—", "—", "—"]
                        : [row.modelData.label, panel.metric(row.modelData.mean_hu),
                        panel.metric(row.modelData.std_hu), panel.metric(row.modelData.delta_center_hu)]
                    Text {
                        id: cell
                        required property string modelData
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        Layout.minimumWidth: 0
                        elide: Text.ElideRight
                        text: modelData
                        color: Theme.textSecondary
                        font.pixelSize: 12
                        horizontalAlignment: Text.AlignHCenter
                        Components.AppToolTip { text: cell.text; visible: cell.truncated && cellHover.hovered }
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
                    Accessible.name: qsTrId("qa.copyRoi") + " " + row.modelData.label
                    onClicked: panel.controller.copyRoi(row.modelData.key)
                    Components.AppToolTip { text: qsTrId("qa.copyRoi"); visible: copyButton.hovered }
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
                    Accessible.description: row.modelData.removable ? "" : qsTrId("qa.protectedRoi")
                    onClicked: panel.controller.deleteRoi(row.modelData.key)
                    Components.AppToolTip { text: qsTrId("qa.deleteRoi"); visible: deleteButton.hovered }
                }
            }
        }
        Text {
            Layout.fillWidth: true
            text: qsTrId("qa.copyHelp")
            color: Theme.textMuted
            font.pixelSize: 10
            wrapMode: Text.Wrap
        }
    }
}
