pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic as Basic
import "../../../components" as Components
import "../../../theme"

ColumnLayout {
    id: root
    objectName: "exportPanel"
    property var exportController: null
    property Item exportItem: null
    readonly property var report: exportController?.measurementReport ?? null
    readonly property var dicomResults: exportController?.dicomResults ?? null
    signal manualRequested()
    spacing: 10
    Text {
        text: qsTrId("text.0315")
        color: Theme.textPrimary
        font.pixelSize: 13
        font.weight: Font.DemiBold
    }
    Components.AppCheckBox {
        id: anonymous
        objectName: "viewportExportAnonymous"
        text: qsTrId("text.0141")
        checked: true
        enabled: !!root.exportController && !root.exportController.busy
    }
    RowLayout {
        Layout.fillWidth: true
        spacing: 6
        Components.AppButton {
            objectName: "exportPng"
            Layout.fillWidth: true
            text: qsTrId("text.0461")
            normalColor: Theme.primaryButtonBackground
            hoverColor: Theme.primaryButtonHover
            pressedColor: Theme.primaryButtonPressed
            disabledColor: Theme.primaryButtonDisabled
            textColor: Theme.textOnPrimary
            compact: true
            enabled: root.exportController?.canExportPng ?? false
            onClicked: root.exportController.exportPng(root.exportItem, Screen.devicePixelRatio, anonymous.checked)
        }
        Components.AppButton {
            objectName: "exportDicom"
            Layout.fillWidth: true
            text: qsTrId("text.1013")
            normalColor: "transparent"
            baseBorderWidth: 1
            baseBorderColor: Theme.primaryButtonBorder
            textColor: Theme.iconActive
            compact: true
            enabled: !!root.exportController && !root.exportController.busy
            onClicked: root.exportController.exportDicom(anonymous.checked)
        }
    }
    Text {
        objectName: "pngUnavailableReason"
        Layout.fillWidth: true
        visible: !!root.exportController && !root.exportController.busy && !root.exportController.canExportPng
        text: qsTrId("text.0460")
        wrapMode: Text.Wrap
        font.pixelSize: 12
        color: Theme.textMuted
    }
    Basic.ProgressBar {
        Layout.fillWidth: true
        visible: !!root.exportController && root.exportController.busy
        value: root.exportController ? root.exportController.progress : 0
        indeterminate: value === 0
    }
    Text {
        objectName: "exportMessage"
        Layout.fillWidth: true
        text: root.exportController ? root.exportController.message : ""
        textFormat: Text.PlainText
        visible: text !== ""
        wrapMode: Text.WrapAnywhere
        font.pixelSize: 12
        color: root.exportController && root.exportController.isError ? Theme.dangerColor : Theme.textSecondary
    }
    Components.AppLinkButton {
        objectName: "exportResultPath"
        Layout.fillWidth: true
        text: root.exportController?.resultPath ?? ""
        visible: text !== ""
        tooltip: (Qt.platform.os === "osx" ? qsTrId("text.1014") : qsTrId("text.1015")) + "\n" + text
        onClicked: root.exportController.openResultLocation()
    }
    Components.AppButton {
        text: qsTrId("text.0656")
        visible: !!root.exportController && root.exportController.busy
        onClicked: root.exportController.cancel()
    }
    Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.borderDefault }
    Text { text: qsTrId("text.1016"); color: Theme.textPrimary; font.pixelSize: 13; font.weight: Font.DemiBold }
    Components.AppCheckBox {
        id: allTabs
        objectName: "reportAllTabs"
        text: qsTrId("text.1017")
        enabled: !root.report?.busy
    }
    Components.AppCheckBox {
        id: reportImages
        objectName: "reportIncludeImages"
        text: qsTrId("text.1018")
        checked: true
        enabled: !root.report?.busy
    }
    RowLayout {
        Layout.fillWidth: true
        spacing: 6
        Components.AppButton {
            objectName: "exportMeasurementCsv"
            text: qsTrId("text.1019")
            actionRole: "primary"
            compact: true
            Layout.fillWidth: true
            enabled: !!root.report && !root.report.busy
            onClicked: root.report.exportReport("csv", allTabs.checked, anonymous.checked, false)
        }
        Components.AppButton {
            objectName: "exportMeasurementPdf"
            text: qsTrId("text.1020")
            compact: true
            Layout.fillWidth: true
            baseBorderWidth: 1
            baseBorderColor: Theme.primaryButtonBorder
            enabled: !!root.report && !root.report.busy
            onClicked: root.report.exportReport("pdf", allTabs.checked, anonymous.checked, reportImages.checked)
        }
    }
    Basic.ProgressBar { Layout.fillWidth: true; visible: root.report?.busy ?? false; value: root.report?.progress ?? 0; indeterminate: value === 0 }
    Components.AppButton {
        text: qsTrId("text.0656")
        visible: root.report?.busy ?? false
        onClicked: root.report.cancel()
    }
    Text {
        objectName: "measurementReportMessage"
        Layout.fillWidth: true
        text: root.report?.message ?? ""
        textFormat: Text.PlainText
        visible: text !== ""
        wrapMode: Text.WrapAnywhere
        font.pixelSize: 12
        color: root.report?.isError ? Theme.dangerColor : Theme.textSecondary
    }
    Components.AppLinkButton {
        objectName: "measurementReportResultPath"
        Layout.fillWidth: true
        text: root.report?.resultPath ?? ""
        visible: text !== ""
        tooltip: (Qt.platform.os === "osx" ? qsTrId("text.1014") : qsTrId("text.1015")) + "\n" + text
        onClicked: root.report.openResultLocation()
    }
    Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.borderDefault }
    Components.AppLinkButton {
        objectName: "exportManualLink"
        Layout.fillWidth: true
        text: qsTrId("text.0651")
        tooltip: qsTrId("text.1021")
        onClicked: root.manualRequested()
    }
    Text { text: qsTrId("results.title"); color: Theme.textPrimary; font.pixelSize: 13; font.weight: Font.DemiBold }
    Text {
        Layout.fillWidth: true
        text: qsTrId("results.help")
        color: Theme.textSecondary
        font.pixelSize: 12
        wrapMode: Text.Wrap
    }
    RowLayout {
        Layout.fillWidth: true
        spacing: 6
        Components.AppButton {
            objectName: "exportSegmentation"
            Layout.fillWidth: true
            text: qsTrId("results.seg")
            compact: true
            enabled: !!root.dicomResults && !root.dicomResults.busy
            onClicked: root.dicomResults.exportResults("seg")
        }
        Components.AppButton {
            objectName: "exportStructuredReport"
            Layout.fillWidth: true
            text: qsTrId("results.sr")
            compact: true
            enabled: !!root.dicomResults && !root.dicomResults.busy
            onClicked: root.dicomResults.exportResults("sr")
        }
    }
    Text {
        objectName: "srCompatibilityHint"
        Layout.fillWidth: true
        text: qsTrId("results.slicerHint")
        color: Theme.textMuted
        font.pixelSize: 12
        wrapMode: Text.Wrap
    }
    Basic.ProgressBar { Layout.fillWidth: true; visible: root.dicomResults?.busy ?? false; indeterminate: true }
    Text {
        objectName: "dicomResultsMessage"
        Layout.fillWidth: true
        text: root.dicomResults?.operation === "export" ? root.dicomResults.message : ""
        textFormat: Text.PlainText
        visible: text !== ""
        wrapMode: Text.WrapAnywhere
        font.pixelSize: 12
        color: root.dicomResults?.isError ? Theme.dangerColor : Theme.textSecondary
    }
    Components.AppButton {
        text: qsTrId("text.0656")
        visible: root.dicomResults?.busy ?? false
        onClicked: root.dicomResults.cancel()
    }
    Components.AppLinkButton {
        objectName: "dicomResultsPath"
        Layout.fillWidth: true
        text: root.dicomResults?.resultPath ?? ""
        visible: text !== ""
        onClicked: root.dicomResults.openResultLocation()
    }
}
