pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../../components" as Components
import "../../../theme"

ColumnLayout {
    id: panel
    objectName: "standalonePetVolumePanel"
    required property var controller
    spacing: 12
    Text { text: qsTrId("text.0577"); color: Theme.textPrimary; font.pixelSize: 14; font.bold: true }
    Text { text: qsTrId("text.1097"); color: Theme.textSecondary }
    Components.AppComboBox {
        objectName: "pet3dUnit"
        Layout.fillWidth: true
        model: panel.controller?.petUnitOptions ?? []
        textRole: "label"
        currentIndex: model.findIndex(o => o.unitId === panel.controller?.petUnitId)
        onActivated: panel.controller.setPetUnit(model[currentIndex].unitId)
    }
    Text { text: qsTrId("text.1098") + (panel.controller?.petUnit ?? ""); color: Theme.textSecondary }
    Components.AppNumberField {
        editContext: [panel.controller, panel.controller?.loadState ?? "", panel.controller?.petUnitId ?? ""]
        enabled: panel.controller?.loadState === "ready"
        objectName: "pet3dUpper"
        Layout.fillWidth: true
        commitOnFinish: true
        numberValue: panel.controller?.petUpper ?? 1
        minimum: 0.000001; maximum: 1e15; decimals: 6
        onEdited: value => panel.controller.setPetUpper(value)
    }
    Text { text: qsTrId("text.1099") + (panel.controller?.petUnit ?? ""); color: Theme.textSecondary }
    Components.AppNumberField {
        editContext: [panel.controller, panel.controller?.loadState ?? "", panel.controller?.petUnitId ?? ""]
        enabled: panel.controller?.loadState === "ready"
        objectName: "pet3dThreshold"
        Layout.fillWidth: true
        commitOnFinish: true
        numberValue: panel.controller?.petThreshold ?? 0
        minimum: 0; maximum: (panel.controller?.petUpper ?? 1) * .999999; decimals: 6
        onEdited: value => panel.controller.setPetThreshold(value)
    }
    Text { text: I18n.format(qsTrId("volume.opacity"), {value: Math.round((panel.controller?.petOpacity ?? 0) * 100)}); color: Theme.textSecondary }
    Components.AppSlider {
        objectName: "pet3dOpacity"
        Layout.fillWidth: true
        from: 0; to: 1; value: panel.controller?.petOpacity ?? .8
        onMoved: panel.controller.setPetOpacity(value)
    }
    Text { text: qsTrId("text.1101"); color: Theme.textSecondary }
    Components.AppComboBox {
        objectName: "pet3dPalette"
        Layout.fillWidth: true
        model: panel.controller?.colorMapOptions ?? []
        textRole: "label"
        currentIndex: model.findIndex(o => o.colorMap === panel.controller?.petPalette)
        onActivated: panel.controller.setPetPalette(model[currentIndex].colorMap)
    }
}
