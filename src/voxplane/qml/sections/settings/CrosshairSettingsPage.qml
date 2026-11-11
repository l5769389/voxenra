pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../center/viewportArea" as Views
import "../../theme"
SettingsSplit {
    id: root
    required property var settingsController
    readonly property var values: settingsController.values.crosshair
    readonly property var planes: [{key: "axial", title: qsTrId("text.0767"), horizontal: "coronal", vertical: "sagittal"}, {key: "coronal", title: qsTrId("text.0768"), horizontal: "axial", vertical: "sagittal"}, {key: "sagittal", title: qsTrId("text.0769"), horizontal: "axial", vertical: "coronal"}]
    Component.onCompleted: {
        const groups = settingsController.values.layout.settingsCollapsedGroups
        if (groups.includes("crosshair-style")) {
            const migrated = groups.filter(key => key !== "crosshair-style")
            for (const plane of planes) {
                const key = "crosshair-style-" + plane.key
                if (!migrated.includes(key)) migrated.push(key)
            }
            settingsController.setValue("layout", "settingsCollapsedGroups", migrated)
        }
    }
    Repeater {
        model: root.planes
        delegate: SettingsSection {
            sectionKey: "crosshair-style-" + modelData.key
            settingsController: root.settingsController
            id: section
            required property var modelData
            Layout.fillWidth: true
            title: modelData.title
            SettingColor { Layout.fillWidth: true; title: qsTrId("text.0770"); settingName: "crosshair-" + section.modelData.key + "Color"; value: root.values[section.modelData.key + "Color"]; onEdited: color => root.settingsController.setValue("crosshair", section.modelData.key + "Color", color) }
            SettingSlider { Layout.fillWidth: true; title: qsTrId("text.0771"); settingName: "crosshair-" + section.modelData.key + "Width"; value: root.values[section.modelData.key + "Width"]; onEdited: value => root.settingsController.setValue("crosshair", section.modelData.key + "Width", value) }
        }
    }
    preview: Component {
        ColumnLayout {
            spacing: 10
            Text { text: qsTrId("text.0772"); color: Theme.textMuted; font.pixelSize: 12 }
            Repeater {
                model: root.planes
                delegate: Rectangle {
                    id: card
                    required property var modelData
                    objectName: "crosshairPreview-" + modelData.key
                    Layout.fillWidth: true; Layout.preferredHeight: 100
                    color: Theme.canvasBackground; radius: 4
                    Views.CrosshairLayer {
                        anchors.fill: parent
                        crosshairPosition: Qt.point(width / 2, height / 2 + 8)
                        rotationDegrees: 0
                        crosshairStyle: ({centerGap: 14, lineWidth: 1, horizontalWidth: root.values[card.modelData.horizontal + "Width"], verticalWidth: root.values[card.modelData.vertical + "Width"], horizontalColor: root.values[card.modelData.horizontal + "Color"], verticalColor: root.values[card.modelData.vertical + "Color"]})
                    }
                    Text { anchors.left: parent.left; anchors.top: parent.top; anchors.margins: 10; text: card.modelData.title; color: Theme.textMuted; font.pixelSize: 11 }
                }
            }
            Text { Layout.fillWidth: true; text: qsTrId("text.0773"); color: Theme.textMuted; font.pixelSize: 11; wrapMode: Text.Wrap }
        }
    }
}
