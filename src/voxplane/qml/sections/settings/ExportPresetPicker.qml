pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../components" as Components
import "../../theme"

ColumnLayout {
    id: root
    required property var settingsController
    required property string kind
    property var options: ({})
    signal selected(var options)
    readonly property var entries: settingsController?.values?.exportPresets?.[kind] ?? []
    readonly property var chosen: chooser.currentIndex > 0 ? entries[chooser.currentIndex - 1] ?? null : null
    spacing: 8
    RowLayout {
        visible: root.entries.length > 0
        Layout.fillWidth: true
        Components.AppComboBox {
            id: chooser
            objectName: root.kind + "PresetPicker"
            Layout.fillWidth: true
            Accessible.name: qsTrId("preset.choose")
            model: [qsTrId("preset.choose")].concat(root.entries.map(entry => entry.name))
            onActivated: if (root.chosen) root.selected(JSON.parse(JSON.stringify(root.chosen.options)))
        }
        Components.AppButton {
            objectName: root.kind + "DeletePreset"
            text: qsTrId("preset.delete")
            enabled: !!root.chosen
            onClicked: {
                const id = root.chosen.id
                if (root.settingsController.deleteExportPreset(root.kind, id)) chooser.currentIndex = 0
            }
        }
    }
    RowLayout {
        Layout.fillWidth: true
        Components.AppTextField {
            id: nameField
            objectName: root.kind + "PresetName"
            Layout.fillWidth: true
            maximumLength: 40
            placeholderText: qsTrId("preset.name")
            Accessible.name: placeholderText
        }
        Components.AppButton {
            objectName: root.kind + "SavePreset"
            text: qsTrId("preset.saveAs")
            enabled: nameField.text.trim().length > 0
            onClicked: {
                if (root.settingsController.saveExportPreset(root.kind, nameField.text, root.options)) {
                    nameField.clear()
                    chooser.currentIndex = root.entries.length
                }
            }
        }
    }
    Text {
        Layout.fillWidth: true
        visible: !!root.settingsController?.message && !!root.settingsController?.messageIsError
        text: root.settingsController?.message ?? ""
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: Theme.textSecondary
        font.pixelSize: 12
    }
}
