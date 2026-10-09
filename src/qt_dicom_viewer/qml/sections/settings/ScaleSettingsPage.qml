pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../components" as Components
import "../center/viewportArea" as Views
import "../../theme"
SettingsSplit {
    id: root
    required property var settingsController
    readonly property var values: settingsController.values.scale
    SettingsSection {
        sectionKey: "scale-style"
        settingsController: root.settingsController
        Layout.fillWidth: true
        title: qsTrId("text.0836")
        Components.AppCheckBox { objectName: "setting-scale-enabled"; text: qsTrId("text.0837"); checked: root.values.enabled; onClicked: root.settingsController.setValue("scale", "enabled", checked) }
        RowLayout {
            Layout.fillWidth: true
            Text { Layout.fillWidth: true; text: qsTrId("text.0838"); color: Theme.textSecondary; font.pixelSize: 12 }
            Components.AppComboBox {
                objectName: "setting-scale-lengthMm"
                Layout.preferredWidth: 130
                model: ["1 mm", "10 mm", "20 mm", "50 mm", "10 cm"]
                currentIndex: [1, 10, 20, 50, 100].indexOf(root.values.lengthMm)
                onActivated: index => root.settingsController.setValue("scale", "lengthMm", [1, 10, 20, 50, 100][index])
            }
        }
        SettingColor { Layout.fillWidth: true; title: qsTrId("text.0839"); settingName: "scale-color"; value: root.values.color; onEdited: color => root.settingsController.setValue("scale", "color", color) }
        Components.HelpButton { Layout.alignment: Qt.AlignRight; explanation: qsTrId("text.0840") }
    }
    preview: Component {
        ColumnLayout {
            spacing: 10
            Text { text: qsTrId("text.0841"); color: Theme.textMuted; font.pixelSize: 12 }
            Rectangle {
                Layout.fillWidth: true; Layout.preferredHeight: 120
                color: Theme.canvasBackground; radius: 4
                Views.ScaleBar { anchors.left: parent.left; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; calibrated: true; pixelsPerMm: 2; options: root.values }
            }
        }
    }
}
