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
        sectionKey: "export-report"
        settingsController: page.settingsController
        Layout.fillWidth: true
        title: qsTrId("report.settingsTitle")
        description: qsTrId("preset.defaultsHint")
        GridLayout {
            id: reportLayout
            Layout.fillWidth: true
            columns: width >= 680 ? 2 : 1
            columnSpacing: 18
            rowSpacing: 14
            PresetPreview {
                Layout.row: reportLayout.columns === 2 ? 0 : 1
                Layout.column: reportLayout.columns === 2 ? 1 : 0
                Layout.fillWidth: true
                Layout.preferredWidth: 750
                Layout.alignment: Qt.AlignTop
                settingsController: page.settingsController
                kind: "report"
            }
            ReportSettingsContent {
                Layout.row: 0
                Layout.column: 0
                Layout.fillWidth: true
                Layout.preferredWidth: 220
                Layout.alignment: Qt.AlignTop
                Layout.maximumWidth: reportLayout.columns === 2 ? 220 : Infinity
                settingsController: page.settingsController
                options: page.settingsController.values.report
                onEdited: options => page.settingsController.setExportOptions("report", options)
            }
        }
    }
    Components.AppButton {
        objectName: "reportSharedDirectory"
        text: qsTrId("settings.sharedExportDirectory")
        onClicked: page.settingsController.selectCategory("export")
    }
}
