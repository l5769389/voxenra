pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../components" as Components
import "../theme"

Components.AppDialog {
    id: dialog
    objectName: "applicationUpdateDialog"
    required property var controller
    width: Math.min(560, parent ? parent.width - 32 : 560)
    height: Math.min(controller.hasUpdate ? 520 : 260, parent ? parent.height - 48 : 520)
    title: controller.hasUpdate ? I18n.format(qsTrId("updates.newVersion"), {version: controller.latestVersion}) : qsTrId("updates.title")
    subtitle: I18n.format(qsTrId("app.version"), {version: controller.currentVersion})
    onRejected: controller.dismiss()
    contentItem: ColumnLayout {
        spacing: 12
        Text {
            objectName: "applicationUpdateStatus"
            visible: dialog.controller.state !== "available" || !dialog.controller.supportsInstallation
            Layout.fillWidth: true
            text: dialog.controller.message
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            color: dialog.controller.state === "error" ? Theme.dangerColor : Theme.textSecondary
            font.pixelSize: 13
        }
        Basic.ProgressBar {
            objectName: "applicationUpdateProgress"
            Layout.fillWidth: true
            visible: dialog.controller.busy
            indeterminate: dialog.controller.state !== "downloading"
            value: dialog.controller.progress
            background: Rectangle { implicitHeight: 5; color: Theme.controlBackground; radius: 2 }
            contentItem: Item {
                implicitHeight: 5
                Rectangle { width: parent.width * (dialog.controller.state === "downloading" ? dialog.controller.progress : 0.25); height: parent.height; radius: 2; color: Theme.primaryColor }
            }
        }
        Text {
            Layout.fillWidth: true
            visible: dialog.controller.state === "downloading"
            text: Math.round(dialog.controller.progress * 100) + "%"
            color: Theme.textMuted
            font.pixelSize: 12
        }
        Text {
            Layout.fillWidth: true
            visible: dialog.controller.hasUpdate
            text: qsTrId("updates.releaseNotes")
            font.pixelSize: 13
            font.weight: Font.DemiBold
            color: Theme.textPrimary
        }
        Basic.ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: dialog.controller.hasUpdate
            clip: true
            contentWidth: availableWidth
            Basic.ScrollBar.horizontal.policy: Basic.ScrollBar.AlwaysOff
            Basic.ScrollBar.vertical: Components.AppScrollBar {}
            Basic.TextArea {
                objectName: "applicationReleaseNotes"
                width: parent.width
                text: dialog.controller.releaseNotes || qsTrId("updates.noNotes")
                // Release text is data; no HTML, embedded resources or executable links.
                textFormat: Text.PlainText
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.Wrap
                color: Theme.textSecondary
                font.pixelSize: 13
                background: Rectangle { color: "transparent" }
            }
        }
        Item { Layout.fillHeight: true; visible: !dialog.controller.hasUpdate }
        Text {
            Layout.fillWidth: true
            visible: dialog.controller.hasUpdate && dialog.controller.supportsInstallation
            text: qsTrId("updates.dialogHint")
            wrapMode: Text.Wrap
            color: Theme.textMuted
            font.pixelSize: 12
        }
    }
    footer: Components.AppDialogFooter {
        leading: Components.AppButton {
            visible: dialog.controller.hasLog
            text: qsTrId("updates.logs")
            onClicked: dialog.controller.openLog()
        }
        Components.AppButton {
            objectName: "applicationUpdateCancel"
            text: qsTrId("updates.cancel")
            onClicked: dialog.reject()
        }
        Components.AppButton {
            objectName: "applicationUpdateAction"
            visible: dialog.controller.hasUpdate
            enabled: !dialog.controller.busy
            text: dialog.controller.canInstall ? (dialog.controller.state === "ready" ? qsTrId("updates.restart") : qsTrId("updates.install")) : qsTrId("updates.downloadPage")
            checked: true
            onClicked: dialog.controller.canInstall ? dialog.controller.install() : dialog.controller.openDownloads()
        }
        Components.AppButton {
            visible: !dialog.controller.hasUpdate && !dialog.controller.busy
            text: qsTrId("updates.check")
            onClicked: dialog.controller.check()
        }
    }
}
