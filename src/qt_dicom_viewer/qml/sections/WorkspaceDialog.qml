pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import QtQuick.Controls.Basic as Basic
import "../components" as Components
import "../theme"

Basic.Dialog {
    id: dialog
    objectName: "workspaceDocumentDialog"
    property var controller: null
    readonly property bool working: controller?.busy ?? false
    readonly property bool restoring: controller?.restoring ?? false
    onRestoringChanged: if (restoring) close()
    readonly property bool missing: controller?.hasMissingSources ?? false
    readonly property bool recovery: controller?.recoveryAvailable ?? false
    readonly property bool named: !!controller?.path
    readonly property bool manualProgress: working && controller?.recoveryState !== "saving"
    signal manualRequested()
    // Keep a native window above VTK hosts, with the OS caption as the only close control.
    popupType: Basic.Popup.Window
    title: qsTrId("text.0622")
    implicitWidth: 460
    implicitHeight: 300
    width: Math.min(implicitWidth, parent ? parent.width - 24 : implicitWidth)
    height: Math.min(implicitHeight, parent ? parent.height - 24 : implicitHeight)
    padding: 16
    spacing: 0
    modal: true
    focus: true
    closePolicy: working ? Basic.Popup.NoAutoClose : Basic.Popup.CloseOnEscape
    background: Rectangle { color: Theme.panelBackgroundStrong }
    readonly property var nativeWindow: contentItem.Window.window
    readonly property bool hasNativeWindow: !!nativeWindow && nativeWindow !== parent?.Window.window
    function configureNativeWindow() {
        if (visible && hasNativeWindow && typeof appController !== "undefined")
            appController.configureNativeDialogWindow(nativeWindow)
    }
    onOpened: configureNativeWindow()
    onNativeWindowChanged: configureNativeWindow()
    Binding {
        target: dialog.hasNativeWindow ? dialog.nativeWindow : null
        property: "color"
        value: Theme.panelBackgroundStrong
        when: dialog.hasNativeWindow
    }
    Connections {
        target: dialog.contentItem.Window.window
        function onClosing(event) {
            if (dialog.visible && dialog.working) event.accepted = false
        }
    }
    header: Item { implicitHeight: 0 }
    contentItem: ColumnLayout {
        implicitWidth: 0
        implicitHeight: 0
        spacing: 10
        RowLayout {
            Layout.fillWidth: true
            Layout.minimumHeight: 50
            Layout.preferredHeight: 50
            Layout.maximumHeight: 50
            spacing: 12
            Item {
                Layout.alignment: Qt.AlignTop
                Layout.preferredWidth: 24
                Layout.preferredHeight: 24
                Components.AppIcon {
                    anchors.centerIn: parent
                    iconName: "workspace"
                    iconSize: 22
                    iconColor: Theme.primaryColor
                    visible: !dialog.manualProgress
                }
                Basic.BusyIndicator {
                    objectName: "workspaceDocumentProgress"
                    anchors.fill: parent
                    visible: dialog.manualProgress
                    running: visible && dialog.visible
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                spacing: 6
                RowLayout {
                    Layout.fillWidth: true
                    Layout.minimumHeight: 24
                    Layout.maximumHeight: 24
                    spacing: 8
                    Text {
                        objectName: "workspaceName"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: dialog.controller?.workspaceName ?? qsTrId("text.0401")
                        textFormat: Text.PlainText
                        color: Theme.textPrimary
                        font.pixelSize: 16
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }
                    Text {
                        objectName: "workspaceSaveState"
                        Layout.preferredWidth: 96
                        text: dialog.controller?.dirty ? qsTrId("text.0623") : qsTrId("text.0624")
                        opacity: dialog.named ? 1 : 0
                        horizontalAlignment: Text.AlignRight
                        color: dialog.controller?.dirty ? Theme.iconActive : Theme.textMuted
                        font.pixelSize: 12
                    }
                }
                Text {
                    id: location
                    objectName: "workspaceDocumentPath"
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.minimumHeight: 20
                    Layout.maximumHeight: 20
                    text: dialog.controller?.path || qsTrId("text.0625")
                    textFormat: Text.PlainText
                    elide: Text.ElideMiddle
                    color: Theme.textSecondary
                    font.pixelSize: 12
                    HoverHandler { id: pathHover }
                    Components.AppToolTip {
                        visible: pathHover.hovered && dialog.named
                        text: location.text
                    }
                }
            }
        }
        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.dividerColor }
        ColumnLayout {
            objectName: "workspaceRecoveryArea"
            Layout.fillWidth: true
            Layout.minimumHeight: 52
            Layout.preferredHeight: 52
            Layout.maximumHeight: 52
            spacing: 2
            RowLayout {
                Layout.fillWidth: true
                Layout.minimumHeight: 26
                Layout.maximumHeight: 26
                spacing: 8
                Components.AppCheckBox {
                    objectName: "workspaceAutomaticRecovery"
                    text: qsTrId("text.0626")
                    padding: 0
                    implicitHeight: 26
                    checked: dialog.controller?.automaticRecovery ?? false
                    enabled: !!dialog.controller && !dialog.working
                    Accessible.name: qsTrId("text.0627")
                    onClicked: {
                        if (!dialog.controller.setAutomaticRecovery(checked))
                            checked = Qt.binding(() => dialog.controller.automaticRecovery)
                    }
                }
                Item { Layout.fillWidth: true }
                Components.WorkspaceSaveIndicator {
                    objectName: "workspaceRecoveryStatus"
                    Layout.preferredWidth: 20
                    Layout.preferredHeight: 20
                    controller: dialog.controller
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.minimumHeight: 24
                Layout.maximumHeight: 24
                spacing: 8
                Text {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    text: dialog.controller?.automaticRecovery
                        ? qsTrId("text.0628")
                        : qsTrId("text.0629")
                    color: Theme.textMuted
                    font.pixelSize: 12
                    elide: Text.ElideRight
                }
                Components.AppLinkButton {
                    id: recoveryLink
                    objectName: "workspaceRecoveryLocation"
                    Layout.preferredWidth: 76
                    Layout.preferredHeight: 24
                    text: qsTrId("text.0630")
                    Accessible.name: qsTrId("text.0630")
                    Accessible.description: dialog.controller?.recoveryPath ?? ""
                    tooltip: ""
                    enabled: !!dialog.controller
                    onHoveredChanged: {
                        if (hovered) { closeRecoveryCard.stop(); openRecoveryCard.restart() }
                        else { openRecoveryCard.stop(); closeRecoveryCard.restart() }
                    }
                    onClicked: recoveryCard.open()
                    Timer {
                        id: openRecoveryCard
                        interval: 350
                        onTriggered: if (recoveryLink.hovered && dialog.visible) recoveryCard.open()
                    }
                    Timer {
                        id: closeRecoveryCard
                        interval: 250
                        onTriggered: if (!recoveryLink.hovered && !recoveryCard.hovered) recoveryCard.close()
                    }
                    Components.RecoveryLocationPopup {
                        id: recoveryCard
                        controller: dialog.controller
                        onHoveredChanged: {
                            if (hovered) closeRecoveryCard.stop()
                            else closeRecoveryCard.restart()
                        }
                    }
                    Connections {
                        target: dialog
                        function onClosed() { openRecoveryCard.stop(); closeRecoveryCard.stop(); recoveryCard.close() }
                    }
                }
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 70
            spacing: 6
            Basic.ScrollView {
                id: messageArea
                objectName: "workspaceDocumentMessageArea"
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumWidth: 0
                Layout.minimumHeight: 36
                clip: true
                contentWidth: availableWidth
                Basic.ScrollBar.horizontal.policy: Basic.ScrollBar.AlwaysOff
                Basic.ScrollBar.vertical: Components.AppScrollBar {}
                TextEdit {
                    objectName: "workspaceDocumentMessage"
                    width: messageArea.availableWidth
                    rightPadding: 12
                    readOnly: true
                    selectByMouse: true
                    selectionColor: Theme.selectionBackground
                    selectedTextColor: Theme.textPrimary
                    text: dialog.controller?.message || (dialog.missing
                        ? qsTrId("text.0632")
                        : dialog.recovery ? qsTrId("text.0633")
                        : qsTrId("text.0634"))
                    textFormat: TextEdit.PlainText
                    wrapMode: TextEdit.Wrap
                    color: dialog.controller?.isError ? Theme.dangerColor : Theme.textMuted
                    font.pixelSize: 12
                }
            }
            // Reserve this slot so recovery actions never move the footer or resize the window.
            Item {
                Layout.fillWidth: true
                Layout.minimumHeight: 28
                Layout.maximumHeight: 28
                Components.AppLinkButton {
                    objectName: "workspaceManualLink"
                    height: parent.height
                    text: qsTrId("text.0635")
                    tooltip: qsTrId("text.0636")
                    visible: !dialog.missing && !dialog.recovery
                    enabled: !dialog.working
                    onClicked: dialog.manualRequested()
                }
                Components.AppButton {
                    objectName: "reopenClosedTab"
                    anchors.right: newWorkspaceButton.left
                    anchors.rightMargin: 8
                    height: parent.height
                    text: qsTrId("workspace.reopenClosed")
                    compact: true
                    visible: !dialog.missing && !dialog.recovery && (dialog.controller?.closedTabCount ?? 0) > 0
                    enabled: dialog.controller?.canReopenClosed ?? false
                    onClicked: dialog.controller.reopenLastClosed()
                }
                Components.AppButton {
                    id: newWorkspaceButton
                    objectName: "newWorkspace"
                    anchors.right: parent.right
                    height: parent.height
                    text: qsTrId("workspace.new.action")
                    iconName: "add"
                    compact: true
                    visible: !dialog.missing && !dialog.recovery
                    enabled: dialog.controller?.canCreateNew ?? false
                    onClicked: dialog.controller.newWorkspace()
                }
                RowLayout {
                    anchors.fill: parent
                    spacing: 8
                    visible: dialog.missing || dialog.recovery
                    Components.AppButton {
                        objectName: dialog.missing ? "locateWorkspaceSources" : "recoverWorkspace"
                        text: dialog.missing ? qsTrId("text.0637") : qsTrId("text.0638")
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.preferredWidth: 1
                        compact: true
                        actionRole: "primary"
                        enabled: !dialog.working
                        onClicked: {
                            if (dialog.missing) dialog.controller.locateMissing()
                            else {
                                dialog.close()
                                dialog.controller.recover()
                            }
                        }
                    }
                    Components.AppButton {
                        objectName: dialog.missing ? "skipWorkspaceSources" : "discardWorkspaceRecovery"
                        text: dialog.missing ? qsTrId("text.0639") : qsTrId("text.0640")
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.preferredWidth: 1
                        compact: true
                        actionRole: dialog.missing ? "neutral" : "danger"
                        enabled: !dialog.working
                        onClicked: {
                            if (dialog.missing) dialog.controller.skipMissing()
                            else {
                                dialog.close()
                                dialog.controller.discardRecovery()
                            }
                        }
                    }
                }
            }
        }
    }
    footer: Components.AppDialogFooter {
        leading: Item {
            implicitWidth: 132
            implicitHeight: 32
            Components.AppButton {
                objectName: "openWorkspace"
                anchors.fill: parent
                text: qsTrId("text.0641")
                visible: !dialog.restoring
                enabled: !!dialog.controller && !dialog.working
                normalColor: "transparent"
                baseBorderWidth: 1
                compact: true
                onClicked: dialog.controller.open()
            }
            Components.AppButton {
                objectName: "cancelWorkspaceRestore"
                anchors.fill: parent
                text: qsTrId("text.0642")
                visible: dialog.restoring
                compact: true
                onClicked: dialog.controller.cancel()
            }
        }
        Item {
            Layout.preferredWidth: 100
            Layout.preferredHeight: 32
            Components.AppButton {
                objectName: "saveWorkspaceAs"
                anchors.fill: parent
                text: qsTrId("text.0643")
                compact: true
                visible: dialog.named
                enabled: !!dialog.controller && !dialog.working
                onClicked: dialog.controller.saveAs()
            }
        }
        Components.AppButton {
            objectName: "saveWorkspace"
            text: dialog.named ? qsTrId("text.0644") : qsTrId("text.0645")
            actionRole: "primary"
            Layout.preferredWidth: 128
            compact: true
            enabled: !!dialog.controller && !dialog.working
            onClicked: dialog.controller.save()
        }
    }
}
