pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../components" as Components
import "../../theme"

ColumnLayout {
    id: page
    required property var settingsController
    readonly property var shortcuts: appController.shortcutController
    spacing: 12
    Component.onDestruction: shortcuts.cancelRecording()
    SettingsSection {
        sectionKey: "input-mouse"
        settingsController: page.settingsController
        Layout.fillWidth: true
        title: qsTrId("input.mouse")
        description: qsTrId("input.mouseHint")
        Components.AppCheckBox {
            objectName: "reverseWheel"
            Layout.fillWidth: true
            text: qsTrId("input.reverseWheel")
            checked: page.settingsController.values.input.reverseWheel
            onToggled: page.settingsController.setValue("input", "reverseWheel", checked)
        }
        Repeater {
            model: ["leftButton", "rightButton", "middleButton"]
            delegate: RowLayout {
                required property string modelData
                Layout.fillWidth: true
                Text { Layout.fillWidth: true; text: qsTrId("input." + parent.modelData); color: Theme.textPrimary; wrapMode: Text.Wrap }
                Components.AppComboBox {
                    objectName: "mouseBinding-" + parent.modelData
                    Layout.preferredWidth: 190
                    enabled: parent.modelData !== "leftButton"
                    readonly property var keys: ["selected", "window", "pan", "zoom", "none"]
                    model: [qsTrId("input.selected"), qsTrId("text.0285"), qsTrId("input.action.pan"), qsTrId("input.action.zoom"), qsTrId("input.none")]
                    currentIndex: parent.modelData === "leftButton" ? 0 : keys.indexOf(page.settingsController.values.input[parent.modelData])
                    onActivated: page.settingsController.setValue("input", parent.modelData, keys[currentIndex])
                }
            }
        }
        Repeater {
            model: ["windowSensitivity", "zoomSensitivity"]
            delegate: SettingSlider {
                required property string modelData
                Layout.fillWidth: true
                settingName: modelData
                title: qsTrId("input." + modelData)
                value: page.settingsController.values.input[modelData]
                from: .25; to: 3; stepSize: .25; suffix: "×"
                onEdited: value => page.settingsController.setValue("input", modelData, value)
            }
        }
    }
    SettingsSection {
        sectionKey: "input-shortcuts"
        settingsController: page.settingsController
        Layout.fillWidth: true
        title: qsTrId("input.shortcuts")
        description: qsTrId("input.shortcutHint")
        Repeater {
            model: page.shortcuts.bindings
            delegate: RowLayout {
                id: row
                required property var modelData
                Layout.fillWidth: true
                Text { Layout.fillWidth: true; Layout.minimumWidth: 0; text: qsTrId(row.modelData.labelId); wrapMode: Text.Wrap; color: Theme.textPrimary }
                Components.AppButton {
                    objectName: "shortcutRecord-" + row.modelData.action
                    Layout.preferredWidth: 160
                    compact: true
                    checked: page.shortcuts.recordingAction === row.modelData.action
                    text: checked ? qsTrId("input.recording") : row.modelData.display || qsTrId("input.record")
                    onClicked: page.shortcuts.beginRecording(row.modelData.action)
                }
                Components.AppButton {
                    objectName: "shortcutClear-" + row.modelData.action
                    Layout.preferredWidth: 32
                    minimumButtonWidth: 32
                    compact: true
                    iconName: "close"; iconSize: 16
                    Accessible.name: qsTrId("input.clear")
                    onClicked: { page.shortcuts.cancelRecording(); page.shortcuts.assign(row.modelData.action, "") }
                    Components.AppToolTip { visible: parent.hovered; text: qsTrId("input.clear") }
                }
            }
        }
        Components.AppButton { objectName: "resetShortcuts"; text: qsTrId("text.0843"); onClicked: { page.shortcuts.cancelRecording(); page.settingsController.resetSection("shortcuts") } }
    }
    SettingsSection {
        sectionKey: "input-fixed"
        settingsController: page.settingsController
        Layout.fillWidth: true
        title: qsTrId("input.fixed")
        description: qsTrId("input.fixedScope")
        Repeater {
            model: page.shortcuts.fixedBindings
            delegate: RowLayout {
                id: fixedRow
                required property var modelData
                Layout.fillWidth: true
                Text { Layout.fillWidth: true; wrapMode: Text.Wrap; text: qsTrId(fixedRow.modelData.labelId); color: Theme.textPrimary }
                Rectangle {
                    objectName: "fixedShortcutBadge-" + fixedRow.modelData.action
                    Layout.preferredWidth: Math.max(100, keyText.implicitWidth + 24)
                    Layout.preferredHeight: 30
                    color: Theme.selectionBackground
                    border.color: Theme.selectionBorder
                    radius: 5
                    Accessible.role: Accessible.StaticText
                    Accessible.name: keyText.text
                    Text {
                        id: keyText
                        anchors.centerIn: parent
                        text: fixedRow.modelData.display
                        color: Theme.primaryColor
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                    }
                }
            }
        }
    }
}
