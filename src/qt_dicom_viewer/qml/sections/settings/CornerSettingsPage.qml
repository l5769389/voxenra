pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import QtQuick.Controls.Basic as Basic
import "../../components" as Components
import "../../theme"

ColumnLayout {
    id: root
    required property var settingsController
    readonly property var values: settingsController.values.corners
    spacing: 12
    CornerLayoutEditor {
        Layout.fillWidth: true
        settingsController: root.settingsController
    }
    SettingsSection {
        sectionKey: "corner-appearance"
        settingsController: root.settingsController
        Layout.fillWidth: true
        title: qsTrId("text.0793")
        Components.AppCheckBox { objectName: "setting-corners-enabled"; text: qsTrId("text.0794"); checked: root.values.enabled; onClicked: root.settingsController.setValue("corners", "enabled", checked) }
        SettingSlider { Layout.fillWidth: true; title: qsTrId("text.0795"); settingName: "corners-fontSize"; from: 10; to: 20; stepSize: 1; value: root.values.fontSize; onEdited: value => root.settingsController.setValue("corners", "fontSize", value) }
        SettingSlider { Layout.fillWidth: true; title: qsTrId("text.0796"); settingName: "corners-lineHeight"; from: 1; to: 1.8; stepSize: 0.1; suffix: qsTrId("text.0797"); value: root.values.lineHeight; onEdited: value => root.settingsController.setValue("corners", "lineHeight", value) }
        RowLayout {
            Layout.fillWidth: true
            Text { Layout.fillWidth: true; text: qsTrId("text.0798"); color: Theme.textSecondary; font.pixelSize: 12 }
            Components.AppComboBox {
                objectName: "setting-corners-colorMode"
                Layout.preferredWidth: 180
                model: [{label: qsTrId("text.0799"), value: "auto"}, {label: qsTrId("text.0800"), value: "custom"}]
                textRole: "label"; valueRole: "value"
                currentIndex: root.values.colorMode === "auto" ? 0 : 1
                onActivated: index => root.settingsController.setValue("corners", "colorMode", index === 0 ? "auto" : "custom")
            }
        }
        SettingColor { Layout.fillWidth: true; enabled: root.values.colorMode === "custom"; title: qsTrId("text.0800"); settingName: "corners-color"; value: root.values.color; onEdited: color => root.settingsController.setValue("corners", "color", color) }
    }
}
