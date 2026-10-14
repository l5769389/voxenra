pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../components" as Components
import "../theme"

Components.AppDialog {
    id: dialog
    objectName: "exportDialog"
    property var controller: null
    property var settingsController: null
    signal manualRequested()
    parent: Basic.Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(560, parent ? parent.width - 32 : 560)
    height: Math.min(560, parent ? parent.height - 32 : 560)
    closeEnabled: !!controller && !controller.busy
    closeButtonName: "exportDialogClose"
    modal: true
    title: controller && controller.anonymousLocked ? qsTrId("text.0646") : qsTrId("text.0647")
    padding: 16
    onClosed: { if (controller) controller.closeDialog() }

    Connections {
        target: dialog.controller
        function onDialogChanged() {
            if (dialog.controller.dialogOpen) {
                format.currentIndex = 0
                anonymous.checked = true
                dialog.open()
            } else {
                dialog.close()
            }
        }
    }

    contentItem: Basic.ScrollView {
        id: exportScroll
        clip: true
        contentWidth: availableWidth
        Basic.ScrollBar.horizontal.policy: Basic.ScrollBar.AlwaysOff
        Basic.ScrollBar.vertical: Components.AppScrollBar {}
        ColumnLayout {
            width: exportScroll.availableWidth
            spacing: 14
            Text {
                Layout.fillWidth: true
                text: I18n.format(qsTrId("export.seriesCount"), {count: dialog.controller ? dialog.controller.instanceCount : 0})
                color: Theme.textMuted
                font.pixelSize: 13
            }
            RowLayout {
                Layout.fillWidth: true
                Text { text: qsTrId("text.0650"); color: Theme.textPrimary; font.pixelSize: 13 }
                Components.AppComboBox {
                    id: format
                    objectName: "exportFormat"
                    Layout.fillWidth: true
                    model: ["DICOM (.dcm)", "PNG (.png)"]
                    enabled: dialog.controller && !dialog.controller.busy
                }
            }
            Text {
                Layout.fillWidth: true
                visible: dialog.controller?.containsFrameGroups ?? false
                text: qsTrId("mr.frameExportNotice")
                color: Theme.textMuted
                font.pixelSize: 12
                wrapMode: Text.Wrap
            }
            Components.AppCheckBox {
                id: anonymous
                objectName: "exportAnonymous"
                text: qsTrId("text.0141")
                checked: true
                enabled: dialog.controller && !dialog.controller.busy && !dialog.controller.anonymousLocked
            }
            Components.AppLinkButton {
                objectName: "seriesExportManualLink"
                Layout.fillWidth: true
                text: qsTrId("text.0651")
                enabled: !dialog.controller?.busy
                tooltip: qsTrId("text.0652")
                onClicked: {
                    dialog.close()
                    dialog.manualRequested()
                }
            }
            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.dividerColor }
            Text { text: qsTrId("text.0653"); color: Theme.textPrimary; font.pixelSize: 13 }
            Text {
                objectName: "exportDestination"
                Layout.fillWidth: true
                text: dialog.settingsController ? dialog.settingsController.exportDirectory : ""
                textFormat: Text.PlainText
                color: Theme.textMuted
                font.pixelSize: 12
                wrapMode: Text.WrapAnywhere
            }
            Components.AppButton {
                text: qsTrId("text.0654")
                normalColor: "transparent"
                baseBorderWidth: 1
                baseBorderColor: Theme.controlBorder
                compact: true
                enabled: dialog.controller && !dialog.controller.busy
                onClicked: dialog.settingsController.chooseExportDirectory()
            }
            Basic.ProgressBar {
                objectName: "exportProgress"
                Layout.fillWidth: true
                visible: dialog.controller && dialog.controller.busy
                from: 0
                to: dialog.controller ? Math.max(1, dialog.controller.totalCount) : 1
                value: dialog.controller ? dialog.controller.completedCount : 0
                indeterminate: dialog.controller && dialog.controller.totalCount === 0
            }
            Text {
                objectName: "exportMessage"
                Layout.fillWidth: true
                visible: text !== ""
                text: dialog.controller ? dialog.controller.message : ""
                textFormat: Text.PlainText
                color: Theme.textPrimary
                font.pixelSize: 13
                wrapMode: Text.Wrap
            }
            Components.AppLinkButton {
                objectName: "exportOutputDirectory"
                Layout.fillWidth: true
                visible: text !== ""
                text: dialog.controller ? dialog.controller.outputDirectory : ""
                tooltip: qsTrId("text.0655") + text
                onClicked: dialog.controller.openOutputDirectory()
            }

        }
    }
    footer: Components.AppDialogFooter {
        Components.AppButton {
            objectName: "cancelExport"
            text: dialog.controller && dialog.controller.busy ? qsTrId("text.0656")
                : dialog.controller?.outputDirectory ? qsTrId("text.0864") : qsTrId("text.0539")
            onClicked: {
                if (dialog.controller.busy) dialog.controller.cancelExport()
                else dialog.reject()
            }
        }
        Components.AppButton {
            objectName: "startExport"
            text: dialog.controller?.outputDirectory ? qsTrId("export.again") : qsTrId("text.0657")
            actionRole: "primary"
            enabled: dialog.controller && !dialog.controller.busy && dialog.controller.instanceCount > 0
            onClicked: dialog.controller.startExport(format.currentIndex === 0 ? "dicom" : "png", anonymous.checked)
        }
    }
}
