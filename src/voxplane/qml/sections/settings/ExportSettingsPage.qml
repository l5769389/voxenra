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
        title: qsTrId("text.0653")
        description: qsTrId("text.0846")
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
        sectionKey: "export-qa-report"
        settingsController: page.settingsController
        Layout.fillWidth: true
        title: qsTrId("qa.reportSettings")
        description: qsTrId("qa.reportNameHint")
        Text {
            Layout.fillWidth: true
            text: qsTrId("qa.reportSoftwareName")
            color: Theme.textSecondary
            font.pixelSize: 12
        }
        Components.AppTextField {
            objectName: "reportSoftwareName"
            Layout.fillWidth: true
            maximumLength: 80
            placeholderText: qsTrId("qa.reportNameEmpty")
            Accessible.name: qsTrId("qa.reportSoftwareName")
            text: page.settingsController.values.export.reportSoftwareName
            selectByMouse: true
            onEditingFinished: {
                page.settingsController.setValue("export", "reportSoftwareName", text)
                text = Qt.binding(function() { return page.settingsController.values.export.reportSoftwareName })
            }
        }
    }
    SettingsSection {
        sectionKey: "export-formats"
        settingsController: page.settingsController
        Layout.fillWidth: true
        title: qsTrId("text.0849")
        description: qsTrId("text.0850")
        Text {
            Layout.fillWidth: true
            text: qsTrId("text.0851")
            color: Theme.textMuted
            wrapMode: Text.Wrap
            font.pixelSize: 12
        }
    }
}
