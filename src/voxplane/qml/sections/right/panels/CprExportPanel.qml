pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic as Basic
import "../../../components" as Components
import "../../../theme"

ColumnLayout {
    id: panel
    objectName: "cprExportPanel"
    required property var controller
    required property var exportController
    required property Item exportItem
    spacing: 10
    Components.DelayedActivity { id: feedback; active: panel.visible && (panel.exportController?.busy ?? false) }
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
    Basic.ProgressBar {
        objectName: "cprExportProgress"
        Layout.fillWidth: true
        visible: feedback.showing
        value: panel.exportController?.progress ?? 0
        indeterminate: value === 0
    }
    Text {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        text: panel.exportController?.message ?? ""
        color: panel.exportController?.isError ? Theme.warningColor : Theme.textSecondary
        wrapMode: Text.Wrap
        font.pixelSize: 12
    }
    Components.AppLinkButton {
        objectName: "cprExportResultPath"
        Layout.fillWidth: true
        text: panel.exportController?.resultPath ?? ""
        visible: text !== ""
        tooltip: (Qt.platform.os === "osx" ? qsTrId("text.1014") : qsTrId("text.1015")) + "\n" + text
        onClicked: panel.exportController.openResultLocation()
    }
    Components.AppButton {
        objectName: "cprExportCancel"
        text: qsTrId("text.0656")
        visible: feedback.showing
        onClicked: panel.exportController.cancel()
    }
}
