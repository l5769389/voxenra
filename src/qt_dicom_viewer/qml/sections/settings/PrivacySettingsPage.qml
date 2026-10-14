pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../components" as Components
import "../../theme"
ColumnLayout {
    id: page
    required property var settingsController
    spacing: 12
    SettingsSection {
        sectionKey: "privacy-identity"
        settingsController: page.settingsController
        Layout.fillWidth: true
        title: qsTrId("privacy.title")
        helpText: qsTrId("privacy.hint")
        Components.AppCheckBox {
            objectName: "privacyHideIdentity"
            Layout.fillWidth: true
            text: qsTrId("privacy.hideIdentity")
            checked: page.settingsController.values.privacy.hideIdentity
            onToggled: page.settingsController.setValue("privacy", "hideIdentity", checked)
        }
    }
    SettingsSection {
        sectionKey: "privacy-recent"
        settingsController: page.settingsController
        Layout.fillWidth: true
        title: qsTrId("privacy.recent")
        helpText: qsTrId("privacy.recentHint")
        RowLayout {
            Layout.fillWidth: true
            Components.AppButton {
                objectName: "clearRecentWorkspaces"
                text: qsTrId("privacy.clearRecent")
                enabled: appController.workspaceDocumentController.recentWorkspaces.length > 0
                onClicked: appController.workspaceDocumentController.clearRecent()
            }
            Item { Layout.fillWidth: true }
        }
    }
}
