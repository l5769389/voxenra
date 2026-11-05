pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../components" as Components
import "../../theme"
import "../center/viewportArea/measurementLayer" as Measurements

SettingsSplit {
    id: root
    required property var settingsController
    readonly property var values: settingsController.values.measurement
    previewMaximumWidth: 380
    SettingsSection {
        sectionKey: "measurement-cards"
        settingsController: root.settingsController
        Layout.fillWidth: true
        title: qsTrId("measurement.cardSettings")
        description: qsTrId("measurement.linkHelp")
        Components.AppCheckBox {
            objectName: "setting-measurement-linkLabelToShape"
            text: qsTrId("measurement.linkLabel")
            checked: root.values.linkLabelToShape
            onClicked: root.settingsController.setValue("measurement", "linkLabelToShape", checked)
        }
        SettingSlider { Layout.fillWidth: true; title: qsTrId("measurement.metricFont"); settingName: "measurement-fontSize"; from: 10; to: 20; stepSize: 1; value: root.values.fontSize; onEdited: value => root.settingsController.setValue("measurement", "fontSize", value) }
        SettingSlider { Layout.fillWidth: true; title: qsTrId("measurement.transparency"); settingName: "measurement-cardTransparency"; from: 0; to: 100; stepSize: 1; suffix: "%"; value: root.values.cardTransparency; onEdited: value => root.settingsController.setValue("measurement", "cardTransparency", value) }
        RowLayout {
            Layout.fillWidth: true
            Text { Layout.fillWidth: true; text: qsTrId("measurement.precision"); color: Theme.textSecondary; font.pixelSize: 12 }
        Components.AppComboBox {
            objectName: "setting-measurement-decimalPlaces"
            Layout.fillWidth: true
            Layout.maximumWidth: 220
            Accessible.name: qsTrId("measurement.precision")
            model: [qsTrId("measurement.integer"), qsTrId("measurement.oneDecimal"),
                    qsTrId("measurement.twoDecimals"), qsTrId("measurement.threeDecimals")]
            currentIndex: root.values.decimalPlaces
            onActivated: index => root.settingsController.setValue("measurement", "decimalPlaces", index)
        }
        }
    }
    SettingsSection {
        sectionKey: "measurement-lines"
        settingsController: root.settingsController
        Layout.fillWidth: true
        title: qsTrId("text.0855")
        description: qsTrId("text.0856")
        SettingColor { Layout.fillWidth: true; title: qsTrId("text.0857"); settingName: "measurement-editingColor"; value: root.values.editingColor; onEdited: color => root.settingsController.setValue("measurement", "editingColor", color) }
        Components.AppCheckBox { objectName: "setting-measurement-editingDash"; text: qsTrId("text.0858"); checked: root.values.editingDash; onClicked: root.settingsController.setValue("measurement", "editingDash", checked) }
        SettingColor { Layout.fillWidth: true; title: qsTrId("text.0859"); settingName: "measurement-completedColor"; value: root.values.completedColor; onEdited: color => root.settingsController.setValue("measurement", "completedColor", color) }
        Components.AppCheckBox { objectName: "setting-measurement-completedDash"; text: qsTrId("text.0860"); checked: root.values.completedDash; onClicked: root.settingsController.setValue("measurement", "completedDash", checked) }
        SettingSlider { Layout.fillWidth: true; title: qsTrId("text.0771"); settingName: "measurement-lineWidth"; value: root.values.lineWidth; onEdited: value => root.settingsController.setValue("measurement", "lineWidth", value) }
    }
    SettingsSection {
        sectionKey: "measurement-arrows"
        settingsController: root.settingsController
        Layout.fillWidth: true
        title: qsTrId("text.0861")
        Components.AppCheckBox {
            objectName: "setting-measurement-annotationFollowsCompleted"
            text: qsTrId("measurement.followCompleted")
            checked: root.values.annotationFollowsCompleted
            onClicked: root.settingsController.setValue("measurement", "annotationFollowsCompleted", checked)
        }
        SettingColor { Layout.fillWidth: true; visible: !root.values.annotationFollowsCompleted; swatchColors: Theme.annotationSwatches; title: qsTrId("text.0862"); settingName: "measurement-annotationColor"; value: root.values.annotationColor; onEdited: color => root.settingsController.setValue("measurement", "annotationColor", color) }
        SettingSlider { Layout.fillWidth: true; title: qsTrId("text.0863"); settingName: "measurement-annotationSize"; from: 8; to: 28; stepSize: 1; value: root.values.annotationSize; onEdited: value => root.settingsController.setValue("measurement", "annotationSize", value) }
    }
    preview: Component {
        ColumnLayout {
            spacing: 10
            MeasurementCardPreview { Layout.fillWidth: true; settingsController: root.settingsController }
            Text { text: qsTrId("text.0841"); color: Theme.textMuted; font.pixelSize: 12 }
            Canvas {
                id: preview
                objectName: "measurementStylePreview"
                Layout.fillWidth: true; Layout.preferredHeight: 180
                property var options: root.values
                onOptionsChanged: requestPaint()
                onWidthChanged: requestPaint()
                onPaint: {
                    const ctx = getContext("2d")
                    ctx.clearRect(0, 0, width, height)
                    ctx.fillStyle = Theme.canvasBackground; ctx.fillRect(0, 0, width, height)
                    const rows = [
                        {y: 48, editing: true, label: qsTrId("text.0857")},
                        {y: 108, editing: false, label: qsTrId("text.0859")},
                        {y: 164, editing: false, reference: true, label: qsTrId("measurement.cprReference")}
                    ]
                    for (const row of rows) {
                        ctx.save()
                        ctx.font = "11px sans-serif"; ctx.fillStyle = Theme.overlayText
                        ctx.fillText(row.label, 16, row.y - 26)
                        ctx.globalAlpha = row.reference ? Theme.referencePathOpacity : 1
                        ctx.strokeStyle = ctx.fillStyle = Theme.drawingLineColor(options, row.editing)
                        ctx.lineWidth = options.lineWidth
                        ctx.setLineDash(Theme.drawingLineDashed(options, row.editing)
                            ? [4, 2] : [])
                        ctx.beginPath(); ctx.moveTo(22, row.y); ctx.lineTo(width - 22, row.y); ctx.stroke()
                        ctx.setLineDash([])
                        for (const x of [22, width - 22]) {
                            ctx.beginPath(); ctx.arc(x, row.y, 3, 0, Math.PI * 2); ctx.fill()
                        }
                        if (!row.reference) {
                            ctx.font = options.fontSize + "px sans-serif"; ctx.textAlign = "center"
                            ctx.fillText(root.settingsController.formatMeasurement(32.456, options.decimalPlaces)
                                + " mm", width / 2, row.y - 7)
                        }
                        ctx.restore()
                    }
                }
            }
            Rectangle {
                Layout.fillWidth: true; Layout.preferredHeight: 100
                color: Theme.canvasBackground; radius: 4
                Measurements.LengthMeasurementItem {
                    anchors.fill: parent; preferences: root.settingsController.values
                    measurement: ({type: "arrow", label: ""})
                    mappedPoints: [Qt.point(28, 72), Qt.point(width - 30, 30)]
                    isDraft: false; isSelected: false
                }
                Text { anchors.left: parent.left; anchors.top: parent.top; anchors.margins: 12; text: qsTrId("text.0377"); color: Theme.textMuted; font.pixelSize: 11 }
            }
            Text { Layout.fillWidth: true; text: qsTrId("text.0865"); color: Theme.textMuted; font.pixelSize: 11; wrapMode: Text.Wrap }
        }
    }
}
