pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../components" as Components
import "../../theme"

ColumnLayout {
    id: page
    required property var settingsController
    readonly property var updater: appController.updateController
    spacing: 12
    SettingsSection {
        sectionKey: "updates-general"
        settingsController: page.settingsController
        Layout.fillWidth: true
        title: qsTrId("updates.title")
        description: qsTrId("updates.settingsHint")
        Components.AppCheckBox {
            objectName: "settingsAutomaticUpdates"
            Layout.fillWidth: true
            text: qsTrId("updates.enable")
            checked: page.settingsController.values.updates.enabled
            onClicked: page.settingsController.setValue("updates", "enabled", checked)
        }
        Text {
            Layout.fillWidth: true
            text: page.updater.message
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            font.pixelSize: 13
            color: page.updater.state === "error" ? Theme.dangerColor : Theme.textSecondary
        }
        RowLayout {
            Components.AppButton {
                objectName: "settingsCheckUpdate"
                text: qsTrId("updates.check")
                enabled: !page.updater.busy && page.updater.state !== "ready"
                onClicked: page.updater.check()
            }
            Components.AppButton {
                objectName: "settingsViewUpdate"
                visible: page.updater.hasUpdate
                text: qsTrId("updates.details")
                checked: true
                onClicked: page.updater.show()
            }
            Components.AppButton {
                visible: page.updater.hasLog
                text: qsTrId("updates.logs")
                onClicked: page.updater.openLog()
            }
        }
    }
}
