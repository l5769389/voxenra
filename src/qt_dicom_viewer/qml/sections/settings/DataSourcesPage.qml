pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../../components" as Components
import "../../theme"

Basic.ScrollView {
    id: page
    required property var pacsController
    objectName: "settingsScroll"
    contentWidth: availableWidth
    rightPadding: 12
    clip: true
    Basic.ScrollBar.vertical: Components.AppScrollBar {}
    ColumnLayout {
        width: Math.min(page.availableWidth, 1000)
        spacing: 12
        Text {
            Layout.fillWidth: true
            Layout.margins: 16
            Layout.bottomMargin: 0
            text: qsTrId("text.0746")
            color: Theme.textPrimary
            font.pixelSize: 18
            font.bold: true
        }
        Text {
            Layout.fillWidth: true
            Layout.leftMargin: 16
            Layout.rightMargin: 16
            text: qsTrId("text.0747")
            color: Theme.textMuted
            font.pixelSize: 13
            wrapMode: Text.Wrap
        }
        SettingsSection {
            Layout.fillWidth: true; Layout.leftMargin: 16; Layout.rightMargin: 16
            title: qsTrId("text.0748")
            description: qsTrId("text.0749")
            RowLayout {
                Layout.fillWidth: true; spacing: 18
                Components.AppCheckBox {
                    objectName: "enableLocalSource"; text: qsTrId("text.0750")
                    checked: page.pacsController.localEnabled; enabled: !page.pacsController.busy
                    onClicked: page.pacsController.setSources(checked, page.pacsController.pacsEnabled)
                }
                Components.AppCheckBox {
                    objectName: "enablePacsSource"; text: qsTrId("text.0494")
                    checked: page.pacsController.pacsEnabled; enabled: !page.pacsController.busy
                    onClicked: page.pacsController.setSources(page.pacsController.localEnabled, checked)
                }
                Item { Layout.fillWidth: true }
            }
        }
        SettingsSection {
            Layout.fillWidth: true; Layout.leftMargin: 16; Layout.rightMargin: 16
            title: qsTrId("text.0751")
        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: I18n.format(qsTrId("pacs.default"), {name: page.pacsController.defaultName})
                color: Theme.textPrimary
                font.pixelSize: 14
                font.bold: true
            }
            Components.AppButton {
                objectName: "pacsAddProfile"
                text: qsTrId("text.0753")
                actionRole: "primary"
                enabled: !page.pacsController.busy
                onClicked: profileDialog.edit(null)
            }
        }
        Repeater {
            model: page.pacsController.profiles
            delegate: Rectangle {
                id: card
                required property var modelData
                Layout.fillWidth: true
                Layout.leftMargin: 16
                Layout.rightMargin: 16
                implicitHeight: cardContent.implicitHeight + 28
                color: Theme.cardBackground
                border.color: modelData.isDefault ? Theme.borderStrong : Theme.borderSubtle
                radius: Theme.controlRadius
                ColumnLayout {
                    id: cardContent
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 9
                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            Layout.fillWidth: true
                            text: card.modelData.name
                            color: Theme.textPrimary
                            font.pixelSize: 15
                            font.bold: true
                            elide: Text.ElideRight
                        }
                        Text {
                            visible: card.modelData.isDefault
                            text: qsTrId("text.0754")
                            color: Theme.primaryColor
                            font.pixelSize: 11
                        }
                        Components.AppCheckBox {
                            text: qsTrId("text.0755")
                            checked: card.modelData.enabled
                            enabled: !page.pacsController.busy
                            onClicked: page.pacsController.setProfileEnabled(card.modelData.id, checked)
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: card.modelData.protocol === "dimse"
                            ? card.modelData.called_ae + " @ " + card.modelData.host + ":" + card.modelData.port
                            : card.modelData.url
                        color: Theme.textMuted
                        font.pixelSize: 12
                        wrapMode: Text.WrapAnywhere
                    }
                    Text {
                        Layout.fillWidth: true
                        text: card.modelData.protocol === "dimse"
                            ? "DIMSE · " + card.modelData.calling_ae + " ← " + card.modelData.listen_host + ":" + card.modelData.listen_port
                            : "DICOMweb  ·  " + (card.modelData.auth === "none" ? qsTrId("text.0756") : card.modelData.auth === "basic" ? "Basic" : "Bearer") + (card.modelData.needsSecret ? qsTrId("text.0757") : "")
                        color: card.modelData.needsSecret ? Theme.warningColor : Theme.textSubtle
                        font.pixelSize: 11
                        wrapMode: Text.Wrap
                    }
                    Text {
                        objectName: "pacsTestResult-" + card.modelData.id
                        Layout.fillWidth: true
                        visible: !!card.modelData.testResult.message
                        text: card.modelData.testResult.message ?? ""
                        color: card.modelData.testResult.state === "error" ? Theme.dangerColor
                            : card.modelData.testResult.state === "success" ? Theme.successColor : Theme.textSecondary
                        wrapMode: Text.Wrap; font.pixelSize: 12
                    }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 7
                        Components.AppButton {
                            objectName: "pacsTest-" + card.modelData.id
                            text: card.modelData.testResult.state === "testing" ? qsTrId("text.0500") : qsTrId("text.0758")
                            compact: true
                            enabled: !page.pacsController.busy
                            onClicked: page.pacsController.testProfile(card.modelData.id)
                        }
                        Components.AppButton {
                            objectName: "pacsEdit-" + card.modelData.id
                            text: qsTrId("text.0759")
                            compact: true
                            enabled: !page.pacsController.busy
                            onClicked: profileDialog.edit(card.modelData)
                        }
                        Components.AppButton {
                            text: qsTrId("text.0760")
                            compact: true
                            enabled: card.modelData.enabled && !card.modelData.isDefault && !page.pacsController.busy
                            onClicked: page.pacsController.setDefault(card.modelData.id)
                        }
                        Components.AppButton {
                            objectName: "pacsDelete-" + card.modelData.id
                            text: qsTrId("text.0761")
                            compact: true
                            actionRole: "danger"
                            enabled: !page.pacsController.busy
                            onClicked: {
                                deleteDialog.profileId = card.modelData.id;
                                deleteDialog.profileName = card.modelData.name;
                                deleteDialog.open();
                            }
                        }
                    }
                }
            }
        }
        Rectangle {
            visible: page.pacsController.profiles.length === 0
            Layout.fillWidth: true
            implicitHeight: 88
            color: Theme.cardBackground
            border.color: Theme.borderSubtle
            radius: Theme.controlRadius
            Text {
                anchors.centerIn: parent
                width: parent.width - 32
                text: qsTrId("text.0762")
                horizontalAlignment: Text.AlignHCenter
                color: Theme.textMuted
                font.pixelSize: 13
                lineHeight: 1.6
                wrapMode: Text.Wrap
            }
        }
        }
        Text {
            objectName: "pacsSettingsMessage"
            Layout.fillWidth: true
            Layout.margins: 16
            visible: page.pacsController.message !== "" && !page.pacsController.profiles.some(row => row.testResult.message === page.pacsController.message)
            text: page.pacsController.message
            color: page.pacsController.isError ? Theme.dangerColor : Theme.successColor
            font.pixelSize: 12
            wrapMode: Text.Wrap
        }
    }

    PacsProfileDialog {
        id: profileDialog
        pacsController: page.pacsController
    }
    Components.AppDialog {
        id: deleteDialog
        objectName: "deletePacsDialog"
        title: qsTrId("text.0763")
        property string profileId: ""
        property string profileName: ""
        parent: Basic.Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(370, parent.width - 32)
        padding: 16
        modal: true

        contentItem: ColumnLayout {
            spacing: 12
            Text {
                Layout.fillWidth: true
                text: I18n.format(qsTrId("pacs.deleteConfirm"), {name: deleteDialog.profileName})
                color: Theme.textPrimary
                wrapMode: Text.Wrap
                font.pixelSize: 15
            }
            Text {
                Layout.fillWidth: true
                text: qsTrId("text.0765")
                color: Theme.textMuted
                font.pixelSize: 12
            }

        }
        footer: Components.AppDialogFooter {
            Components.AppButton {
                objectName: "cancelDeletePacs"
                text: qsTrId("text.0539")
                onClicked: deleteDialog.reject()
            }
            Components.AppButton {
                objectName: "confirmDeletePacs"
                text: qsTrId("text.0766")
                actionRole: "danger"
                onClicked: {
                    page.pacsController.deleteProfile(deleteDialog.profileId)
                    deleteDialog.accept()
                }
            }
        }
    }
}
