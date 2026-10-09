pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../../components" as Components
import "../../../theme"

ColumnLayout {
    id: panel
    objectName: "petVolumePanel"
    required property var controller
    readonly property var display: controller?.isFusionVolume === true ? controller : ({
        sceneLabel: "", volumeMode: "fusion", ctPreset: "bone", ctOpacity: 0,
        petUpper: 1, petThreshold: 0, petUnit: "", petOpacity: 0,
        colorMapOptions: [], petPalette: "hotIron"
    })
    spacing: 12
    Components.PanelHeading {
        objectName: "PetVolumePanelHeading"
        title: qsTrId("text.0578")
        explanation: qsTrId("text.1126")
    }

    ColumnLayout {
        Layout.fillWidth: true
        visible: panel.display.volumeMode !== "pet"
        Text { text: qsTrId("text.1127"); color: Theme.textPrimary; font.bold: true }
        Components.AppComboBox {
            objectName: "fusionVolumeCtPreset"
            Layout.fillWidth: true
            model: [{label:qsTrId("text.0005"), value:"bone"}, {label:qsTrId("text.1128"), value:"general"}, {label:qsTrId("text.0006"), value:"lung"}]
            textRole: "label"
            currentIndex: model.findIndex(x => x.value === panel.display.ctPreset)
            onActivated: panel.controller.setCtPreset(model[currentIndex].value)
        }
        Text { text: I18n.format(qsTrId("volume.ctOpacity"), {value: Math.round(panel.display.ctOpacity * 100)}); color: Theme.textMuted }
        Components.AppSlider {
            objectName: "fusionVolumeCtOpacity"
            Layout.fillWidth: true
            from: 0; to: 1; value: panel.display.ctOpacity
            onMoved: panel.controller.setCtOpacity(value)
        }
    }
    ColumnLayout {
        Layout.fillWidth: true
        visible: panel.display.volumeMode !== "ct"
        Text { text: qsTrId("text.1130"); color: Theme.textPrimary; font.bold: true }
        Text {
            Layout.fillWidth: true
            text: I18n.format(qsTrId("pet.range"), {upper: Number(panel.display.petUpper.toPrecision(4)), unit: panel.display.petUnit})
            color: Theme.textMuted; wrapMode: Text.Wrap
        }
        RowLayout {
            Layout.fillWidth: true
            Text { text: qsTrId("text.1132"); color: Theme.textMuted }
            Components.AppNumberField {
                objectName: "fusionVolumePetThreshold"
                Layout.fillWidth: true
                numberValue: panel.display.petThreshold
                minimum: 0; maximum: panel.display.petUpper * .99; decimals: 3
                onEdited: value => panel.controller.setPetThreshold(value)
            }
            Text { text: panel.display.petUnit; color: Theme.textMuted; font.pixelSize: 11 }
        }
        Text { text: I18n.format(qsTrId("volume.petOpacity"), {value: Math.round(panel.display.petOpacity * 100)}); color: Theme.textMuted }
        Components.AppSlider {
            objectName: "fusionVolumePetOpacity"
            Layout.fillWidth: true
            from: 0; to: 1; value: panel.display.petOpacity
            onMoved: panel.controller.setPetOpacity(value)
        }
        Components.AppComboBox {
            objectName: "fusionVolumePetPalette"
            Layout.fillWidth: true
            model: panel.display.colorMapOptions
            textRole: "label"
            currentIndex: model.findIndex(x => x.colorMap === panel.display.petPalette)
            onActivated: panel.controller.setPetPalette(model[currentIndex].colorMap)
        }
    }

}
