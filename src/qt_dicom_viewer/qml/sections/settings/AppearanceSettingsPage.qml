pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../components" as Components
import "../../theme"

ColumnLayout {
    id: page
    required property var settingsController
    readonly property var language: appController.languageController
    spacing: 12
    SettingsSection {
        sectionKey: "appearance-theme"
        settingsController: page.settingsController
        Layout.fillWidth: true
        title: qsTrId("appearance.theme")
        GridLayout {
            Layout.fillWidth: true
            columns: page.width >= 540 ? 3 : page.width >= 340 ? 2 : 1
            columnSpacing: 12
            rowSpacing: 12
            Repeater {
                model: ["dark", "graphite", "light"]
                delegate: Components.AppButton {
                    id: choice
                    required property string modelData
                    readonly property var previewPalette: Theme.previewColors(modelData)
                    objectName: "themeChoice-" + modelData
                    Layout.fillWidth: true
                    Layout.minimumWidth: 136
                    Layout.maximumWidth: 220
                    Layout.preferredHeight: 92
                    checked: page.settingsController.values.appearance.theme === modelData
                    Accessible.name: modelData === "dark" ? qsTrId("appearance.dark")
                        : modelData === "graphite" ? qsTrId("appearance.graphite") : qsTrId("appearance.light")
                    onClicked: page.settingsController.setValue("appearance", "theme", modelData)
                    contentItem: ColumnLayout {
                        spacing: 8
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 36
                            radius: 4
                            color: choice.previewPalette.panelBackground
                            border.color: choice.previewPalette.borderStrong
                            Rectangle { x: 8; y: 8; width: 24; height: 20; radius: 2; color: choice.previewPalette.selectionBackground }
                            Rectangle { x: 38; y: 8; width: parent.width - 46; height: 20; radius: 2; color: choice.previewPalette.canvasBackground }
                        }
                        Text {
                            Layout.fillWidth: true
                            text: choice.Accessible.name
                            color: Theme.textPrimary
                            font.pixelSize: 13
                            horizontalAlignment: Text.AlignHCenter
                        }
                    }
                }
            }
        }
    }
    SettingsSection {
        sectionKey: "appearance-language"
        settingsController: page.settingsController
        Layout.fillWidth: true
        title: qsTrId("appearance.language")
        description: qsTrId("appearance.languageHint")
        Components.AppComboBox {
            id: languages
            objectName: "languageChoice"
            Layout.fillWidth: true
            Layout.maximumWidth: 320
            model: page.language.languages
            textRole: "name"
            valueRole: "locale"
            currentIndex: model.findIndex(item => item.locale === page.language.locale)
            onActivated: page.language.selectLanguage(currentValue)
        }
        Flow {
            Layout.fillWidth: true
            spacing: 8
            Components.AppButton { objectName: "openLanguageDirectory"; baseBorderWidth: 1; compact: true; text: qsTrId("appearance.openPacks"); onClicked: page.language.openDirectory() }
            Components.AppButton { objectName: "reloadLanguagePacks"; baseBorderWidth: 1; compact: true; text: qsTrId("appearance.reloadPacks"); onClicked: page.language.reload() }
        }
        Text { Layout.fillWidth: true; text: qsTrId("appearance.packsHint"); color: Theme.textMuted; font.pixelSize: 12; wrapMode: Text.Wrap }
        Text { objectName: "languagePackStatus"; Layout.fillWidth: true; Layout.minimumHeight: 36; text: page.language.message; color: Theme.textSecondary; font.pixelSize: 12; wrapMode: Text.Wrap }
    }
}
