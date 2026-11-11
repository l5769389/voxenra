pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../components" as Components
import "../../theme"
ColumnLayout {
    id: root
    required property var settingsController
    property string modality: "gray"
    spacing: 12
    RowLayout {
        Layout.fillWidth: true
        spacing: 6
        Repeater {
            model: [{key: "gray", title: qsTrId("text.0774")}, {key: "pet", title: "PET"}]
            delegate: Components.AppButton {
                required property var modelData
                objectName: "colorMapModality-" + modelData.key
                text: modelData.title
                checkable: true
                checked: root.modality === modelData.key
                onClicked: root.modality = modelData.key
            }
        }
        Item { Layout.fillWidth: true }
    }
    Repeater {
        model: [{key: "gray", title: qsTrId("text.0775")}, {key: "pet", title: qsTrId("text.0776")}]
        delegate: SettingsSection {
            id: group
            required property var modelData
            Layout.fillWidth: true
            visible: root.modality === modelData.key
            title: group.modelData.title
            GridLayout {
                Layout.fillWidth: true
                columns: Math.max(1, Math.min(4, Math.floor((group.width - 12) / 180)))
                columnSpacing: 8; rowSpacing: 8
                Repeater {
                    model: root.settingsController.colorMaps
                    delegate: Components.AppButton {
                        id: preset
                        required property var modelData
                        objectName: "colorMap-" + group.modelData.key + "-" + modelData.key
                        Layout.fillWidth: true
                        Layout.preferredHeight: 58
                        compact: true
                        checkable: true
                        autoExclusive: true
                        checked: root.settingsController.values.colormap[group.modelData.key] === modelData.key
                        baseBorderWidth: 1
                        onClicked: root.settingsController.setValue("colormap", group.modelData.key, modelData.key)
                        contentItem: ColumnLayout {
                            spacing: 6
                            GradientStrip { Layout.fillWidth: true; Layout.preferredHeight: 18; colors: preset.modelData.colors }
                            RowLayout {
                                Text { Layout.fillWidth: true; text: preset.modelData.label; color: Theme.textPrimary; font.pixelSize: 12 }
                                Text { text: preset.checked ? "✓" : ""; color: Theme.primaryColor; font.pixelSize: 15 }
                            }
                        }
                    }
                }
            }
        }
    }
    Text { Layout.fillWidth: true; text: qsTrId("text.0777"); color: Theme.textMuted; font.pixelSize: 12; wrapMode: Text.Wrap }
}
