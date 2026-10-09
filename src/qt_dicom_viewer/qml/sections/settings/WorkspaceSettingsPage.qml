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
        sectionKey: "workspace-exit"
        settingsController: page.settingsController
        Layout.fillWidth: true
        title: qsTrId("text.0866")
        description: qsTrId("text.0867")
        Components.AppComboBox {
            id: behavior
            objectName: "workspaceExitBehavior"
            Layout.fillWidth: true
            Layout.maximumWidth: 320
            textRole: "label"
            valueRole: "key"
            model: [
                {key: "ask", label: qsTrId("text.0868")},
                {key: "save", label: qsTrId("text.0869")},
                {key: "discard", label: qsTrId("text.0870")}
            ]
            currentIndex: model.findIndex(item => item.key === page.settingsController.values.workspace.exitBehavior)
            Accessible.name: qsTrId("text.0871")
            onActivated: page.settingsController.setValue("workspace", "exitBehavior", currentValue)
        }
        Components.HelpButton {
            objectName: "workspaceExitDescription"
            Layout.alignment: Qt.AlignRight
            explanation: ({
                ask: qsTrId("text.0872"),
                save: qsTrId("text.0873"),
                discard: qsTrId("text.0874")
            })[page.settingsController.values.workspace.exitBehavior]
        }
    }
    SettingsSection {
        sectionKey: "workspace-recovery"
        settingsController: page.settingsController
        Layout.fillWidth: true
        title: qsTrId("text.0626")
        description: qsTrId("text.0875")
        Components.AppCheckBox {
            objectName: "settingsWorkspaceAutomaticRecovery"
            Layout.fillWidth: true
            text: qsTrId("text.0627")
            checked: page.settingsController.values.workspace.automaticRecovery
            onClicked: page.settingsController.setValue("workspace", "automaticRecovery", checked)
        }
        Text {
            Layout.fillWidth: true
            text: qsTrId("text.0876")
            color: Theme.textMuted
            font.pixelSize: 12
            wrapMode: Text.Wrap
        }
    }
}
