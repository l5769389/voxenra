pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../../components" as Components
import "../../theme"

Components.AppDialog {
    id: dialog
    objectName: "pacsProfileDialog"
    title: profileId ? qsTrId("text.0877") : qsTrId("text.0878")
    closeEnabled: true
    required property var pacsController
    property string profileId: ""
    property string saveError: ""
    property bool profileEnabled: true
    property bool existingSecret: false
    readonly property bool isDimse: protocolField.currentIndex === 1
    parent: Basic.Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(540, parent.width - 40)
    height: Math.min(665, parent.height - 36)
    padding: 16
    modal: true
    focus: true

    function edit(profile) {
        saveError = "";
        profileId = profile ? profile.id : "";
        profileEnabled = profile ? profile.enabled : true;
        existingSecret = profile ? !profile.needsSecret && profile.auth !== "none" : false;
        nameField.text = profile ? profile.name : "";
        urlField.text = profile ? profile.url : "";
        authField.currentIndex = profile ? ["none", "basic", "bearer"].indexOf(profile.auth) : 0;
        usernameField.text = profile ? profile.username : "";
        secretField.text = "";
        timeoutField.text = profile ? String(profile.timeout) : "15";
        protocolField.currentIndex = profile && profile.protocol === "dimse" ? 1 : 0;
        hostField.text = profile ? profile.host || "" : "";
        portField.text = profile ? String(profile.port || 104) : "104";
        calledAeField.text = profile ? profile.called_ae || "" : "";
        callingAeField.text = profile ? profile.calling_ae || "VOXENRA" : "VOXENRA";
        listenHostField.text = profile ? profile.listen_host || "127.0.0.1" : "127.0.0.1";
        listenPortField.text = profile ? String(profile.listen_port || 11112) : "11112";
        pacsController.clearDraftTest();
        open();
    }
    function values() {
        return {
            id: profileId,
            name: nameField.text,
            protocol: isDimse ? "dimse" : "dicomweb",
            host: hostField.text,
            port: portField.text,
            called_ae: calledAeField.text,
            calling_ae: callingAeField.text,
            listen_host: listenHostField.text,
            listen_port: listenPortField.text,
            url: urlField.text,
            enabled: profileEnabled,
            auth: ["none", "basic", "bearer"][authField.currentIndex],
            username: usernameField.text,
            secret: secretField.text,
            timeout: timeoutField.text
        };
    }
    onClosed: {
        if (pacsController.busy && pacsController.operation === "test") pacsController.cancel()
        secretField.text = ""
    }
    function save() {
        if (pacsController.busy) return
        if (pacsController.saveProfile(values())) accept()
        else saveError = pacsController.message
    }

    contentItem: ColumnLayout {
        spacing: 12

        Basic.ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            id: profileScroll
            objectName: "pacsProfileScroll"
            contentWidth: availableWidth
            Basic.ScrollBar.horizontal.policy: Basic.ScrollBar.AlwaysOff
            rightPadding: 12
            Basic.ScrollBar.vertical: Components.AppScrollBar {}
            clip: true
            ColumnLayout {
                width: profileScroll.availableWidth
                spacing: 8
                Text {
                    id: nameLabel
                    text: qsTrId("text.0879")
                    color: Theme.textMuted
                    font.pixelSize: 12
                }
                Components.AppTextField {
                    id: nameField
                    objectName: "pacsProfileName"
                    Accessible.name: nameLabel.text
                    Layout.fillWidth: true
                    placeholderText: qsTrId("text.0880")
                    enabled: !dialog.pacsController.busy
                    onTextEdited: dialog.pacsController.clearDraftTest()
                    onAccepted: dialog.save()
                }
                Text {
                    text: qsTrId("dimse.protocol")
                    color: Theme.textMuted
                    font.pixelSize: 12
                }
                Components.AppComboBox {
                    id: protocolField
                    objectName: "pacsProfileProtocol"
                    Accessible.name: qsTrId("dimse.protocol")
                    Layout.fillWidth: true
                    model: ["DICOMweb", qsTrId("dimse.protocolName")]
                    enabled: !dialog.pacsController.busy
                    onActivated: { dialog.saveError = ""; dialog.pacsController.clearDraftTest() }
                }
                RowLayout {
                    visible: dialog.isDimse
                    Layout.fillWidth: true
                    spacing: 12
                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.preferredWidth: 300
                        Text { text: qsTrId("dimse.host"); color: Theme.textMuted; font.pixelSize: 12 }
                        Components.AppTextField {
                            id: hostField
                            objectName: "pacsProfileHost"
                            Accessible.name: qsTrId("dimse.host")
                            Layout.fillWidth: true
                            placeholderText: "192.168.1.10"
                            
                            enabled: !dialog.pacsController.busy
                            onTextEdited: dialog.pacsController.clearDraftTest()
                            onAccepted: dialog.save()
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.preferredWidth: 200
                        Text { text: qsTrId("dimse.port"); color: Theme.textMuted; font.pixelSize: 12 }
                        Components.AppTextField {
                            id: portField
                            objectName: "pacsProfilePort"
                            Accessible.name: qsTrId("dimse.port")
                            Layout.fillWidth: true
                            placeholderText: "104"
                            validator: IntValidator { bottom: 1; top: 65535 }
                            enabled: !dialog.pacsController.busy
                            onTextEdited: dialog.pacsController.clearDraftTest()
                            onAccepted: dialog.save()
                        }
                    }
                }
                RowLayout {
                    visible: dialog.isDimse
                    Layout.fillWidth: true
                    spacing: 12
                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.preferredWidth: 200
                        Text { text: qsTrId("dimse.calledAe"); color: Theme.textMuted; font.pixelSize: 12 }
                        Components.AppTextField {
                            id: calledAeField
                            objectName: "pacsProfileCalledAe"
                            Accessible.name: qsTrId("dimse.calledAe")
                            Layout.fillWidth: true
                            placeholderText: "PACS"
                            
                            enabled: !dialog.pacsController.busy
                            onTextEdited: dialog.pacsController.clearDraftTest()
                            onAccepted: dialog.save()
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.preferredWidth: 200
                        Text { text: qsTrId("dimse.callingAe"); color: Theme.textMuted; font.pixelSize: 12 }
                        Components.AppTextField {
                            id: callingAeField
                            objectName: "pacsProfileCallingAe"
                            Accessible.name: qsTrId("dimse.callingAe")
                            Layout.fillWidth: true
                            placeholderText: "VOXENRA"
                            
                            enabled: !dialog.pacsController.busy
                            onTextEdited: dialog.pacsController.clearDraftTest()
                            onAccepted: dialog.save()
                        }
                    }
                }
                RowLayout {
                    visible: dialog.isDimse
                    Layout.fillWidth: true
                    spacing: 12
                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.preferredWidth: 300
                        Text { text: qsTrId("dimse.listenHost"); color: Theme.textMuted; font.pixelSize: 12 }
                        Components.AppTextField {
                            id: listenHostField
                            objectName: "pacsProfileListenHost"
                            Accessible.name: qsTrId("dimse.listenHost")
                            Layout.fillWidth: true
                            placeholderText: "0.0.0.0"
                            
                            enabled: !dialog.pacsController.busy
                            onTextEdited: dialog.pacsController.clearDraftTest()
                            onAccepted: dialog.save()
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.preferredWidth: 200
                        Text { text: qsTrId("dimse.listenPort"); color: Theme.textMuted; font.pixelSize: 12 }
                        Components.AppTextField {
                            id: listenPortField
                            objectName: "pacsProfileListenPort"
                            Accessible.name: qsTrId("dimse.listenPort")
                            Layout.fillWidth: true
                            placeholderText: "11112"
                            validator: IntValidator { bottom: 1; top: 65535 }
                            enabled: !dialog.pacsController.busy
                            onTextEdited: dialog.pacsController.clearDraftTest()
                            onAccepted: dialog.save()
                        }
                    }
                }
                Text {
                    visible: dialog.isDimse
                    Layout.fillWidth: true
                    text: qsTrId("dimse.setupHint")
                    color: Theme.textSubtle
                    wrapMode: Text.Wrap
                    font.pixelSize: 11
                }
                Text {
                    id: urlLabel
                    visible: !dialog.isDimse
                    text: qsTrId("text.0881")
                    color: Theme.textMuted
                    font.pixelSize: 12
                    Layout.topMargin: 4
                }
                Components.AppTextField {
                    id: urlField
                    visible: !dialog.isDimse
                    objectName: "pacsProfileUrl"
                    Accessible.name: urlLabel.text
                    Layout.fillWidth: true
                    placeholderText: "http://127.0.0.1:8042/dicom-web"
                    enabled: !dialog.pacsController.busy
                    onTextEdited: dialog.pacsController.clearDraftTest()
                    onAccepted: dialog.save()
                }
                Text {
                    Layout.fillWidth: true
                    text: qsTrId("text.0882")
                    visible: !dialog.isDimse
                    color: Theme.textSubtle
                    wrapMode: Text.Wrap
                    font.pixelSize: 11
                }
                Text {
                    id: authLabel
                    visible: !dialog.isDimse
                    text: qsTrId("text.0883")
                    color: Theme.textMuted
                    font.pixelSize: 12
                    Layout.topMargin: 4
                }
                Components.AppComboBox {
                    id: authField
                    visible: !dialog.isDimse
                    objectName: "pacsProfileAuth"
                    Accessible.name: authLabel.text
                    Layout.fillWidth: true
                    model: [qsTrId("text.0756"), qsTrId("text.0884"), qsTrId("text.0885")]
                    enabled: !dialog.pacsController.busy
                    onActivated: dialog.pacsController.clearDraftTest()
                }
                Text {
                    visible: !dialog.isDimse && authField.currentIndex === 1
                    id: usernameLabel
                    text: qsTrId("text.0886")
                    color: Theme.textMuted
                    font.pixelSize: 12
                }
                Components.AppTextField {
                    id: usernameField
                    objectName: "pacsProfileUsername"
                    Accessible.name: usernameLabel.text
                    visible: !dialog.isDimse && authField.currentIndex === 1
                    Layout.fillWidth: true
                    enabled: !dialog.pacsController.busy
                    onTextEdited: dialog.pacsController.clearDraftTest()
                    onAccepted: dialog.save()
                }
                Text {
                    visible: !dialog.isDimse && authField.currentIndex > 0
                    id: secretLabel
                    text: authField.currentIndex === 1 ? qsTrId("text.0887") : qsTrId("text.0888")
                    color: Theme.textMuted
                    font.pixelSize: 12
                }
                Components.AppTextField {
                    id: secretField
                    objectName: "pacsProfileSecret"
                    Accessible.name: secretLabel.text
                    visible: !dialog.isDimse && authField.currentIndex > 0
                    Layout.fillWidth: true
                    echoMode: TextInput.Password
                    placeholderText: dialog.existingSecret ? qsTrId("text.0889") : qsTrId("text.0890")
                    enabled: !dialog.pacsController.busy
                    onTextEdited: dialog.pacsController.clearDraftTest()
                    onAccepted: dialog.save()
                }
                Text {
                    visible: !dialog.isDimse && authField.currentIndex > 0
                    Layout.fillWidth: true
                    text: qsTrId("text.0891")
                    color: Theme.textSubtle
                    font.pixelSize: 11
                    wrapMode: Text.Wrap
                }
                Text {
                    id: timeoutLabel
                    text: qsTrId("text.0892")
                    color: Theme.textMuted
                    font.pixelSize: 12
                    Layout.topMargin: 4
                }
                Components.AppTextField {
                    id: timeoutField
                    objectName: "pacsProfileTimeout"
                    Accessible.name: timeoutLabel.text
                    Layout.fillWidth: true
                    validator: IntValidator {
                        bottom: 3
                        top: 120
                    }
                    enabled: !dialog.pacsController.busy
                    onTextEdited: dialog.pacsController.clearDraftTest()
                    onAccepted: dialog.save()
                }

            }
        }
        Text {
            Layout.fillWidth: true
            text: qsTrId("numeric.formSaveHint")
            color: Theme.textMuted
            font.pixelSize: 11
            wrapMode: Text.Wrap
        }
        Text {
            objectName: "pacsProfileMessage"
            Layout.fillWidth: true
            visible: text !== ""
            text: dialog.saveError || dialog.pacsController.draftTestResult.message || ""
            color: dialog.saveError || dialog.pacsController.draftTestResult.state === "error" ? Theme.dangerColor
                : dialog.pacsController.draftTestResult.state === "success" ? Theme.successColor : Theme.textSecondary
            wrapMode: Text.Wrap; font.pixelSize: 12
        }

    }
    footer: Components.AppDialogFooter {
        leading: Components.AppButton {
            objectName: "pacsTestDraft"
            text: dialog.pacsController.busy ? qsTrId("text.0500") : qsTrId("text.0758")
            enabled: !dialog.pacsController.busy
            onClicked: { dialog.saveError = ""; dialog.pacsController.testDraft(dialog.values()) }
        }
        Components.AppButton {
            objectName: "pacsCancelProfile"
            text: qsTrId("text.0539")
            onClicked: dialog.reject()
        }
        Components.AppButton {
            objectName: "pacsSaveProfile"
            text: qsTrId("text.0893")
            actionRole: "primary"
            enabled: !dialog.pacsController.busy
            onClicked: dialog.save()
        }
    }
}
