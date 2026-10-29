pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../../components" as Components
import "../../../theme"

ColumnLayout {
    id: panel
    objectName: "cprExportPanel"
    required property var controller
    required property var exportController
    required property Item exportItem
    spacing: 10
    Components.PanelHeading { title: qsTrId("cpr.exportTitle"); explanation: qsTrId("cpr.exportHint") }
    Components.AppComboBox {
        objectName: "cprExportScope"
        Layout.fillWidth: true
        model: [qsTrId("cpr.curved"), qsTrId("cpr.cross"), qsTrId("cpr.combined")]
        currentIndex: ["curved", "cross", "combined"].indexOf(panel.controller.exportScope)
        enabled: !(panel.exportController?.busy ?? false)
        onActivated: panel.controller.setExportScope(["curved", "cross", "combined"][currentIndex])
    }
    Components.AppCheckBox {
        id: anonymous
        objectName: "cprExportAnonymous"
        Layout.fillWidth: true
        text: qsTrId("text.0141")
        checked: true
    }
    Components.AppButton {
        objectName: "cprExportPng"
        Layout.fillWidth: true
        text: qsTrId("text.0461")
        enabled: panel.exportController?.canExportPng ?? false
        onClicked: panel.exportController.exportPng(panel.exportItem, Screen.devicePixelRatio, anonymous.checked)
    }
    Text {
        Layout.fillWidth: true
        text: panel.exportController?.message ?? ""
        color: panel.exportController?.isError ? Theme.warningColor : Theme.textSecondary
        wrapMode: Text.Wrap
        font.pixelSize: 12
    }
}
