pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../components" as Components
import "../../theme"

ColumnLayout {
    id: root
    required property var settingsController
    readonly property var values: settingsController.values.initialDisplay
    readonly property var templates: [{presetId: "", label: qsTrId("initialDisplay.dicom"), title: qsTrId("initialDisplay.dicom")}].concat(
        settingsController.windowTemplates.filter(entry => entry.enabled).map(entry => Object.assign({}, entry, {
            title: entry.label + " · WW " + entry.width + " / WL " + entry.center
        })))
    spacing: 14
    SettingsSection {
        Layout.fillWidth: true
        settingsController: root.settingsController
        sectionKey: "initial-display"
        title: qsTrId("initialDisplay.title")
        description: qsTrId("initialDisplay.help")
        GridLayout {
            id: layout
            Layout.fillWidth: true
            columns: width >= 680 ? 2 : 1
            columnSpacing: 18
            rowSpacing: 14
            PresetPreview {
                Layout.row: layout.columns === 2 ? 0 : 1
                Layout.column: layout.columns === 2 ? 1 : 0
                Layout.fillWidth: true
                Layout.preferredWidth: 750
                settingsController: root.settingsController
                kind: "initialDisplay"
            }
            ColumnLayout {
                Layout.row: 0
                Layout.column: 0
                Layout.fillWidth: true
                Layout.preferredWidth: 260
                Layout.alignment: Qt.AlignTop
                Layout.maximumWidth: layout.columns === 2 ? 280 : Infinity
                Text { text: qsTrId("initialDisplay.zoom"); color: Theme.textSecondary; font.pixelSize: 12 }
                Components.AppComboBox {
                    objectName: "setting-initialDisplay-zoom"
                    Layout.fillWidth: true
                    model: [qsTrId("initialDisplay.fit"), qsTrId("initialDisplay.pixel")]
                    currentIndex: root.values.zoom === "pixel" ? 1 : 0
                    onActivated: index => root.settingsController.setValue("initialDisplay", "zoom", ["fit", "pixel"][index])
                }
                Text { text: qsTrId("initialDisplay.windowMode"); color: Theme.textSecondary; font.pixelSize: 12 }
                Components.AppComboBox {
                    objectName: "setting-initialDisplay-windowMode"
                    Layout.fillWidth: true
                    model: [qsTrId("initialDisplay.dicom"), qsTrId("initialDisplay.preset")]
                    currentIndex: root.values.windowMode === "preset" ? 1 : 0
                    onActivated: index => root.settingsController.setValue("initialDisplay", "windowMode", ["dicom", "preset"][index])
                }
                Text {
                    Layout.fillWidth: true
                    visible: root.values.windowMode === "dicom"
                    text: qsTrId("initialDisplay.sourceHint")
                    wrapMode: Text.Wrap
                    color: Theme.textMuted
                    font.pixelSize: 12
                }
                Repeater {
                    model: ["ctPreset", "mrPreset"]
                    delegate: ColumnLayout {
                        id: selector
                        required property string modelData
                        Layout.fillWidth: true
                        visible: root.values.windowMode === "preset"
                        readonly property var selected: root.templates.find(entry => entry.presetId === root.values[modelData]) ?? root.templates[0]
                        Text {
                            text: selector.modelData === "ctPreset" ? qsTrId("initialDisplay.ctPreset") : qsTrId("initialDisplay.mrPreset")
                            color: Theme.textSecondary; font.pixelSize: 12
                        }
                        Components.AppComboBox {
                            objectName: "setting-initialDisplay-" + selector.modelData
                            Layout.fillWidth: true
                            model: root.templates
                            textRole: "title"
                            displayText: selector.selected.label
                            minimumPopupWidth: 400
                            currentIndex: Math.max(0, root.templates.findIndex(entry => entry.presetId === root.values[selector.modelData]))
                            onActivated: index => root.settingsController.setValue("initialDisplay", selector.modelData, root.templates[index].presetId)
                        }
                        Text {
                            objectName: "initialWindowValues-" + selector.modelData
                            Layout.fillWidth: true
                            text: selector.selected.presetId ? qsTrId("initialDisplay.windowValues").arg(String(selector.selected.width)).arg(String(selector.selected.center)) : qsTrId("initialDisplay.sourceHint")
                            wrapMode: Text.Wrap
                            color: Theme.textSecondary
                            font.pixelSize: 12
                        }
                    }
                }
            }
        }
    }
}
