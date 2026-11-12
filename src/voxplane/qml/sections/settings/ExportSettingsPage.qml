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
        sectionKey: "export-directory"
        settingsController: page.settingsController
        Layout.fillWidth: true
        title: qsTrId("settings.sharedExportDirectory")
        description: qsTrId("export.directoryHint")
        RowLayout {
            Layout.fillWidth: true
            Components.AppTextField {
                objectName: "exportDirectoryField"
                Layout.fillWidth: true
                text: page.settingsController.exportDirectory
                selectByMouse: true
                onEditingFinished: {
                    page.settingsController.setValue("export", "directory", text)
                    text = Qt.binding(function() { return page.settingsController.exportDirectory })
                }
            }
            Components.AppButton {
                objectName: "chooseExportDirectory"
                text: qsTrId("text.0847")
                onClicked: page.settingsController.chooseExportDirectory()
            }
        }
        Text {
            Layout.fillWidth: true
            text: I18n.format(qsTrId("export.defaultLocation"), {path: page.settingsController.defaultExportDirectory})
            textFormat: Text.PlainText
            color: Theme.textMuted
            wrapMode: Text.WrapAnywhere
            font.pixelSize: 12
        }
    }
    SettingsSection {
        sectionKey: "export-screenshot"
        settingsController: page.settingsController
        Layout.fillWidth: true
        title: qsTrId("screenshot.settingsTitle")
        description: qsTrId("preset.defaultsHint")
        ScreenshotSettingsPage { Layout.fillWidth: true; settingsController: page.settingsController }
    }
}
