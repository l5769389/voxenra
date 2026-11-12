pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic as Basic
import "../../../components" as Components
import "../../../theme"
import "../../settings" as Settings

ColumnLayout {
    id: panel
    objectName: "cprExportPanel"
    required property var controller
    required property var exportController
    required property Item exportItem
    property Item tabExportItem: exportItem
    property var settingsController: null
    property var screenshotDraft: ({})
    Component.onCompleted: screenshotDraft = Object.assign({}, settingsController?.values?.screenshot ?? {})
    ScreenshotPreviewDialog { preview: panel.exportController.screenshotPreview }
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
    Components.ScreenshotOptions {
        Layout.fillWidth: true
        options: panel.screenshotDraft
        enabled: !panel.exportController?.busy
        onEdited: options => panel.screenshotDraft = options
    }
    Settings.ExportPresetPicker {
        Layout.fillWidth: true
        visible: !!panel.settingsController
        settingsController: panel.settingsController
        kind: "screenshot"
        options: panel.screenshotDraft
        onSelected: options => panel.screenshotDraft = options
    }
    Components.AppButton {
        objectName: "cprExportPng"
        Layout.fillWidth: true
        text: qsTrId("screenshot.export")
        enabled: panel.exportController?.canExportPng ?? false
        onClicked: panel.exportController.previewScreenshot(panel.exportItem, panel.tabExportItem, panel.screenshotDraft)
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
