pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../components" as Components
import "../../theme"
ColumnLayout {
    id: root
    required property var settingsController
    property string editingId: ""
    spacing: 24
    function clearEditor() { editingId = ""; name.text = ""; ww.text = "400"; wl.text = "40" }
    SettingsSection {
        Layout.fillWidth: true
        title: qsTrId("windowFile.title")
        description: qsTrId("windowFile.hint")
        Text {
            objectName: "windowPresetsPath"
            Layout.fillWidth: true
            text: root.settingsController.windowPresetsPath
            textFormat: Text.PlainText
            color: Theme.textSecondary
            font.pixelSize: 12
            wrapMode: Text.WrapAnywhere
        }
        RowLayout {
            Layout.fillWidth: true
            Components.AppButton {
                objectName: "openWindowPresetsLocation"
                text: qsTrId("windowFile.open")
                iconName: "folder"
                enabled: root.settingsController.windowPresetsPath !== ""
                onClicked: root.settingsController.openWindowPresetsLocation()
            }
            Components.AppButton {
                objectName: "reloadWindowPresets"
                text: qsTrId("windowFile.reload")
                iconName: "reset"
                enabled: root.settingsController.windowPresetsPath !== ""
                onClicked: { if (root.settingsController.reloadWindowPresets()) root.clearEditor() }
            }
        }
    }
    SettingsSection {
        Layout.fillWidth: true
        title: qsTrId("text.0778")
        description: qsTrId("text.0779")
        RowLayout {
            Layout.fillWidth: true; spacing: 12
            Text { Layout.fillWidth: true; text: qsTrId("text.0528"); color: Theme.textSubtle; font.pixelSize: 11 }
            Text { Layout.minimumWidth: 78; Layout.maximumWidth: 78; Layout.fillWidth: true; objectName: "windowHeaderWW"; text: qsTrId("text.0780"); horizontalAlignment: Text.AlignRight; color: Theme.textSubtle; font.pixelSize: 11 }
            Text { Layout.minimumWidth: 78; Layout.maximumWidth: 78; Layout.fillWidth: true; objectName: "windowHeaderWL"; text: qsTrId("text.0781"); horizontalAlignment: Text.AlignRight; color: Theme.textSubtle; font.pixelSize: 11 }
            Item { Layout.minimumWidth: 96; Layout.maximumWidth: 96; Layout.preferredHeight: 1 }
        }
        Repeater {
            model: root.settingsController.windowTemplates
            delegate: ColumnLayout {
                id: entry
                required property var modelData
                Layout.fillWidth: true; spacing: 2
                RowLayout {
                    Layout.fillWidth: true; spacing: 12
                    Components.AppCheckBox {
                        id: enabledBox
                        objectName: "windowEnabled-" + entry.modelData.presetId
                        Layout.fillWidth: true; Layout.minimumWidth: 72
                        text: entry.modelData.label
                        contentItem: Text {
                            text: enabledBox.text; textFormat: Text.PlainText
                            color: Theme.textSecondary; font.pixelSize: 13
                            verticalAlignment: Text.AlignVCenter
                            leftPadding: enabledBox.indicator.width + enabledBox.spacing
                            wrapMode: Text.Wrap
                        }
                        checked: entry.modelData.enabled
                        onClicked: root.settingsController.enableWindowTemplate(entry.modelData.presetId, checked)
                    }
                    Text { Layout.minimumWidth: 78; Layout.maximumWidth: 78; Layout.fillWidth: true; objectName: "windowWW-" + entry.modelData.presetId; text: entry.modelData.width; horizontalAlignment: Text.AlignRight; color: Theme.textSecondary; font.pixelSize: 12 }
                    Text { Layout.minimumWidth: 78; Layout.maximumWidth: 78; Layout.fillWidth: true; objectName: "windowWL-" + entry.modelData.presetId; text: entry.modelData.center; horizontalAlignment: Text.AlignRight; color: Theme.textSecondary; font.pixelSize: 12 }
                    RowLayout {
                        Layout.minimumWidth: 96; Layout.maximumWidth: 96; spacing: 4
                        Components.AppButton {
                            objectName: "windowEdit-" + entry.modelData.presetId
                            visible: !entry.modelData.builtin; text: qsTrId("text.0782"); compact: true
                            Layout.preferredWidth: 46; Layout.preferredHeight: 28
                            onClicked: { root.editingId = entry.modelData.presetId; name.text = entry.modelData.label; ww.text = entry.modelData.width; wl.text = entry.modelData.center }
                        }
                        Components.AppButton {
                            objectName: "windowDelete-" + entry.modelData.presetId
                            visible: !entry.modelData.builtin; text: qsTrId("text.0761"); compact: true; actionRole: "danger"
                            Layout.preferredWidth: 46; Layout.preferredHeight: 28
                            onClicked: { root.settingsController.deleteWindowTemplate(entry.modelData.presetId); if (root.editingId === entry.modelData.presetId) root.clearEditor() }
                        }
                        Text { visible: entry.modelData.builtin; Layout.fillWidth: true; text: qsTrId("text.0783"); horizontalAlignment: Text.AlignHCenter; color: Theme.textSubtle; font.pixelSize: 11 }
                    }
                }
                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.borderSubtle }
            }
        }
    }
    SettingsSection {
        Layout.fillWidth: true
        title: root.editingId ? qsTrId("text.0784") : qsTrId("text.0785")
        GridLayout {
            Layout.fillWidth: true
            columns: root.width >= 420 ? 3 : 1; columnSpacing: 12; rowSpacing: 10
            ColumnLayout {
                Layout.fillWidth: true
                Text { text: qsTrId("text.0528"); color: Theme.textMuted; font.pixelSize: 11 }
                Components.AppTextField { id: name; objectName: "windowTemplateName"; Layout.fillWidth: true; placeholderText: qsTrId("text.0786"); maximumLength: 40 }
            }
            ColumnLayout {
                Layout.fillWidth: true; Layout.minimumWidth: root.width >= 420 ? 100 : 0; Layout.maximumWidth: root.width >= 420 ? 100 : Infinity
                Text { text: qsTrId("text.0780"); color: Theme.textMuted; font.pixelSize: 11 }
                Components.AppTextField { id: ww; objectName: "windowTemplateWidth"; Layout.fillWidth: true; text: "400" }
            }
            ColumnLayout {
                Layout.fillWidth: true; Layout.minimumWidth: root.width >= 420 ? 100 : 0; Layout.maximumWidth: root.width >= 420 ? 100 : Infinity
                Text { text: qsTrId("text.0781"); color: Theme.textMuted; font.pixelSize: 11 }
                Components.AppTextField { id: wl; objectName: "windowTemplateCenter"; Layout.fillWidth: true; text: "40" }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Text { text: root.settingsController.windowTemplates.length + " / 100"; color: Theme.textSubtle; font.pixelSize: 11 }
            Item { Layout.fillWidth: true }
            Components.AppButton {
                objectName: "cancelWindowTemplate"
                visible: !!root.editingId
                text: qsTrId("text.0539")
                onClicked: root.clearEditor()
            }
            Components.AppButton {
                objectName: "saveWindowTemplate"
                actionRole: "primary"
                text: root.editingId ? qsTrId("text.0787") : qsTrId("text.0788")
                onClicked: {
                    if (root.settingsController.saveWindowTemplate(root.editingId, name.text, ww.text.trim() ? Number(ww.text) : NaN, wl.text.trim() ? Number(wl.text) : NaN)) root.clearEditor()
                }
            }
        }
    }
}
