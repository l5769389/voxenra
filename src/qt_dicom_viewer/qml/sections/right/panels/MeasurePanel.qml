pragma ComponentBehavior: Bound
import QtQuick
import "../../../components" as Components
import QtQuick.Layouts
import "../components" as Components
import "../../../theme"
import "../../../components" as Widgets

ColumnLayout {
    id: measurePanel
    spacing: 8
    required property var toolController
    property var resultsController: null
    property var dicomResults: null
    property var viewportController: null
    property bool maskConversionAvailable: false
    readonly property var measurements: viewportController?.measurementController ?? null
    readonly property bool selectedFreehand: (measurements?.measurementItems ?? []).some(
        item => item.measurementId === measurements?.selectedMeasurementId && item.type === "freehand")

    signal manualRequested()

    RowLayout {
        Layout.fillWidth: true
        Text {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            wrapMode: Text.Wrap
            text: qsTrId("text.0292")
            color: Theme.textPrimary
            font.pixelSize: 14
        }
        Components.ToolActionButton {
            objectName: "measurementManualButton"
            Layout.alignment: Qt.AlignRight
            Layout.preferredWidth: 28
            Layout.preferredHeight: 28
            iconName: "manual"
            iconSize: 18
            label: qsTrId("text.1031")
            onClicked: measurePanel.manualRequested()
        }
        Widgets.HelpButton {
            Layout.preferredWidth: 28
            Layout.preferredHeight: 28
            explanation: qsTrId("seg.roiHelp")
        }
    }

    signal actionTriggered(string action)

    Text {
        objectName: "measurementCalibrationWarning"
        Layout.fillWidth: true
        visible: !!measurePanel.viewportController
            && measurePanel.viewportController.loadState === "ready"
            && !measurePanel.viewportController.hasPhysicalSpacing
        text: qsTrId("measurement.noCalibration")
        color: Theme.textSecondary
        font.pixelSize: 12
        wrapMode: Text.Wrap
    }

    GridLayout {
        Layout.fillWidth: true
        columns: 2
        columnSpacing: 6
        rowSpacing: 6
        uniformCellWidths: true
        Repeater {
            model: measurePanel.toolController ? measurePanel.toolController.measureActions : []
            delegate: Components.ToolActionButton {
                id: measureButton
                objectName: "measureEntry-" + measureButton.modelData.action.split(":")[1]
                required property var modelData
                readonly property bool btnChecked: measureButton.modelData.action === (measurePanel.toolController?.activeInteraction ?? "")

                enabled: measurePanel.viewportController?.hasPhysicalSpacing ?? false
                checked: measureButton.btnChecked
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                iconName: modelData.iconName
                label: modelData.label

                onClicked: {
                    measurePanel.actionTriggered(modelData.action);
                }
            }
        }
    }

    MeasurementResults {
        Layout.fillWidth: true
        controller: measurePanel.resultsController
    }
    Widgets.AppButton {
        objectName: "freehandToSegmentation"
        Layout.fillWidth: true
        visible: measurePanel.maskConversionAvailable
        text: qsTrId("seg.convertRoi")
        enabled: measurePanel.selectedFreehand
            && !!measurePanel.dicomResults && !measurePanel.dicomResults.busy
        onClicked: measurePanel.dicomResults.convertSelectedRoi()
    }

    Text {
        objectName: "roiConversionMessage"
        Layout.fillWidth: true
        visible: measurePanel.maskConversionAvailable && text !== ""
        text: measurePanel.dicomResults?.operation === "convert" ? measurePanel.dicomResults.message : ""
        font.pixelSize: 12
        color: measurePanel.dicomResults?.isError ? Theme.dangerColor : Theme.textSecondary
        wrapMode: Text.Wrap
        textFormat: Text.PlainText
    }

}
