pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../components" as Components
import "../theme"

Basic.Dialog {
    id: dialog
    Components.DelayedActivity { id: feedback; active: dialog.visible && dialog.controller.scanning }
    objectName: "importTaskDialog"
    required property var controller
    parent: Basic.Overlay.overlay
    anchors.centerIn: parent
    // A separate popup window stays above native VTK hosts as well as QML views.
    popupType: Basic.Popup.Window
    // Native popup geometry must not inherit changing text/layout size hints.
    implicitWidth: 460
    implicitHeight: 260
    width: Math.min(implicitWidth, parent ? parent.width - 32 : implicitWidth)
    height: Math.min(implicitHeight, parent ? parent.height - 32 : implicitHeight)
    modal: false
    // The OS supplies the window frame and the only caption close control.
    title: qsTrId("text.0611")
    focus: true
    padding: 16
    topPadding: 8
    bottomPadding: 8
    spacing: 0
    closePolicy: controller.scanning ? Basic.Popup.NoAutoClose : Basic.Popup.CloseOnEscape
    background: Rectangle {
        objectName: "importTaskSurface"
        color: Theme.panelBackgroundStrong
    }
    header: Item {
        implicitHeight: 72
        RowLayout {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 12
            Rectangle {
                Layout.preferredWidth: 36
                Layout.preferredHeight: 36
                radius: 18
                color: dialog.controller.importError ? Theme.warningSurface : Theme.infoSurface
                Components.AppIcon {
                    anchors.centerIn: parent
                    iconName: "folder"
                    iconSize: 22
                    iconColor: dialog.controller.importError ? Theme.warningColor : Theme.infoColor
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                spacing: 4
                Text {
                    Layout.fillWidth: true
                    text: dialog.controller.scanning ? qsTrId("text.0612")
                        : dialog.controller.importError ? qsTrId("text.0613") : qsTrId("text.0614")
                    color: Theme.textPrimary
                    font.pixelSize: 17
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }
                Text {
                    Layout.fillWidth: true
                    text: dialog.controller.scanning ? qsTrId("text.0615")
                        : dialog.controller.importError ? qsTrId("text.0616") : qsTrId("text.0617")
                    color: Theme.textMuted
                    font.pixelSize: 12
                    elide: Text.ElideRight
                }
            }
        }
    }
    onClosed: controller.closeImportTask()
    Connections {
        target: dialog.contentItem.Window.window
        function onClosing(event) {
            // Keep progress and its cancel action reachable while work is running.
            if (dialog.visible && dialog.controller.scanning) event.accepted = false
        }
    }
    Connections {
        target: dialog.controller
        function onImportTaskChanged() {
            if (dialog.controller.importTaskOpen && !dialog.visible) dialog.open()
            else if (!dialog.controller.importTaskOpen && dialog.visible) dialog.close()
        }
    }

    contentItem: ColumnLayout {
        implicitWidth: 0
        implicitHeight: 0
        spacing: 12
        Basic.ScrollView {
            id: messageArea
            objectName: "importTaskMessageArea"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumWidth: 0
            Layout.minimumHeight: 40
            clip: true
            background: null
            contentWidth: availableWidth
            Basic.ScrollBar.horizontal.policy: Basic.ScrollBar.AlwaysOff
            Basic.ScrollBar.vertical: Components.AppScrollBar {}
            TextEdit {
                objectName: "importTaskMessage"
                width: messageArea.availableWidth
                rightPadding: messageArea.effectiveScrollBarWidth
                readOnly: true
                selectByMouse: true
                text: !dialog.controller.scanning || feedback.showing ? dialog.controller.statusMessage : ""
                textFormat: TextEdit.PlainText
                color: Theme.textPrimary
                font.pixelSize: 13
                wrapMode: TextEdit.Wrap
            }
        }
        Basic.ProgressBar {
            objectName: "importTaskProgress"
            Layout.fillWidth: true
            Layout.preferredHeight: 4
            visible: feedback.showing
            indeterminate: dialog.controller.importProgress < 0
            value: Math.max(0, dialog.controller.importProgress)
            background: Rectangle {
                color: Theme.controlBackground
                radius: 2
            }
            contentItem: Item {
                id: progressTrack
                property real phase: 0
                clip: true
                NumberAnimation on phase {
                    running: dialog.visible && dialog.controller.scanning && dialog.controller.importProgress < 0
                    from: 0; to: 1; duration: 1200; loops: Animation.Infinite
                }
                Rectangle {
                    x: dialog.controller.importProgress < 0 ? progressTrack.width * 0.72 * progressTrack.phase : 0
                    width: progressTrack.width * (dialog.controller.importProgress < 0 ? 0.28
                        : Math.max(0, Math.min(1, dialog.controller.importProgress)))
                    height: progressTrack.height
                    radius: 2
                    color: Theme.primaryColor
                }
            }
        }
        Text {
            Layout.fillWidth: true
            visible: dialog.controller.scanning
            text: qsTrId("text.0618")
            color: Theme.textMuted
            font.pixelSize: 12
            wrapMode: Text.Wrap
        }
    }
    footer: Components.AppDialogFooter {
        separatorVisible: false
        leading: Components.AppButton {
            objectName: "importTaskChoose"
            text: qsTrId("text.0619")
            visible: dialog.controller.importError && !dialog.controller.scanning
            compact: true
            onClicked: dialog.controller.openImportDialog()
        }
        Components.AppButton {
            objectName: "importTaskClose"
            minimumButtonWidth: 80
            text: dialog.controller.scanning ? qsTrId("text.0620") : qsTrId("common.ok")
            actionRole: !dialog.controller.scanning && !dialog.controller.importError ? "primary" : "neutral"
            compact: true
            onClicked: {
                if (dialog.controller.scanning) dialog.controller.cancelImport()
                else dialog.close()
            }
        }
        Components.AppButton {
            objectName: "importTaskRetry"
            minimumButtonWidth: 80
            text: qsTrId("text.0009")
            actionRole: "primary"
            visible: dialog.controller.importError && !dialog.controller.scanning
            compact: true
            onClicked: dialog.controller.retryImport()
        }
    }
}
