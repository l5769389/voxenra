pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../../components" as Components
import "../../../theme"

ColumnLayout {
    id: panel
    objectName: "petColorPanel"
    required property var controller
    property bool fusionTarget: false
    property bool showAllPalettes: false
    readonly property var commonPalettes: ["grayscale-inverted", "grayscale", "hotIron", "hotMetal", "pet", "rainbow"]
    readonly property alias shortcutCount: palette.shortcutCount
    function selectShortcutIndex(index) { palette.selectShortcutIndex(index) }
    spacing: 12

    Text { text: qsTrId("text.0309"); color: Theme.textPrimary; font.pixelSize: 14; font.bold: true }
    RowLayout {
        Layout.fillWidth: true
        Components.AppButton {
            objectName: "paletteTarget-pet"
            Layout.fillWidth: true
            text: panel.controller.isFusion ? "PET / MIP" : "PET"
            checkable: true
            checked: !panel.fusionTarget
            onClicked: panel.fusionTarget = false
        }
        Components.AppButton {
            objectName: "paletteTarget-fusion"
            visible: panel.controller.isFusion
            Layout.fillWidth: true
            text: qsTrId("text.1042")
            checkable: true
            checked: panel.fusionTarget
            onClicked: panel.fusionTarget = true
        }
    }
    PseudoColorPanel {
        id: palette
        Layout.fillWidth: true
        description: panel.fusionTarget
            ? qsTrId("text.1043")
            : qsTrId("text.1044")
        viewportController: QtObject {
            readonly property var colorMapOptions: panel.controller.petController.colorMapOptions.filter(
                entry => panel.showAllPalettes || panel.commonPalettes.includes(entry.colorMap) || palette.favorites.includes(entry.colorMap)
                    || entry.colorMap === activeColorMap)
            readonly property string activeColorMap: panel.fusionTarget
                ? panel.controller.fusionColorMap : panel.controller.petColorMap
            function applyColorMap(value) {
                if (panel.fusionTarget) panel.controller.setFusionColorMap(value)
                else panel.controller.setPetColorMap(value)
            }
        }
    }
    Components.AppButton {
        objectName: "toggleMorePetColors"
        Layout.fillWidth: true
        compact: true
        text: panel.showAllPalettes ? qsTrId("text.1045") : qsTrId("text.1046")
        onClicked: panel.showAllPalettes = !panel.showAllPalettes
    }
}
