pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../components" as Components
GridLayout {
    id: root
    required property var settingsController
    columns: width >= 680 ? 2 : 1
    columnSpacing: 18
    rowSpacing: 14
    PresetPreview {
        Layout.row: root.columns === 2 ? 0 : 1
        Layout.column: root.columns === 2 ? 1 : 0
        Layout.fillWidth: true
        Layout.alignment: Qt.AlignTop
        Layout.preferredWidth: 750
        settingsController: root.settingsController
        kind: "screenshot"
    }
    ColumnLayout {
        Layout.row: 0
        Layout.column: 0
        Layout.fillWidth: true
        Layout.preferredWidth: 220
        Layout.alignment: Qt.AlignTop
        Layout.maximumWidth: root.columns === 2 ? 220 : Infinity
        Components.ScreenshotOptions {
            Layout.fillWidth: true
            options: root.settingsController.values.screenshot
            onEdited: options => root.settingsController.setExportOptions("screenshot", options)
        }
        ExportPresetPicker {
            Layout.fillWidth: true
            settingsController: root.settingsController
            kind: "screenshot"
            options: root.settingsController.values.screenshot
            onSelected: options => root.settingsController.setExportOptions("screenshot", options)
        }
    }
}
