pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic as Basic
import "../../../components" as Components
import "../../../theme"

ColumnLayout {
    id: panel
    objectName: "associatedImportPanel"
    property var controller: null
    property var regionController: null
    property var toolController: null
    spacing: 10
    Components.PanelHeading {
        objectName: "ImportPanelHeading"
        title: qsTrId("seg.importTitle")
        explanation: qsTrId("seg.importHelp")
    }

    Components.AppButton {
        objectName: "importSegmentation"
        Layout.fillWidth: true
        text: qsTrId("seg.import")
        actionRole: "primary"
        enabled: !!panel.controller && !panel.controller.busy
        onClicked: panel.controller.importSegmentation()
    }
    Basic.ProgressBar {
        Layout.fillWidth: true
        visible: panel.controller?.busy ?? false
        indeterminate: true
    }
    Text {
        objectName: "segmentationImportMessage"
        Layout.fillWidth: true
        text: panel.controller?.operation === "import" ? panel.controller.message : ""
        textFormat: Text.PlainText
        visible: text !== ""
        color: panel.controller?.isError ? Theme.dangerColor : Theme.textSecondary
        font.pixelSize: 12
        wrapMode: Text.Wrap
    }
    Components.AppButton {
        visible: panel.controller?.busy ?? false
        text: qsTrId("text.0656")
        onClicked: panel.controller.cancel()
    }
    Components.AppButton {
        objectName: "manageImportedSegments"
        Layout.fillWidth: true
        text: qsTrId("seg.manage")
        visible: (panel.regionController?.items.length ?? 0) > 0
        onClicked: panel.toolController.activateTool("segmentation")
    }

}
