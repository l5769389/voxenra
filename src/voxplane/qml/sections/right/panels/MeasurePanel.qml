pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window
import "../../../components/ScrollFocus.js" as ScrollFocus
import QtQuick.Layouts
import QtQuick.Controls.Basic as Basic
import "../components" as Components
import "../../../theme"
import "../../../components" as Widgets

Item {
    id: measurePanel
    property real maximumPanelHeight: Infinity
    required property var toolController
    property var resultsController: null
    property var dicomResults: null
    property var viewportController: null
    property bool maskConversionAvailable: false
    readonly property var currentAction: toolController?.measureActions.find(
        entry => entry.action === toolController.activeInteraction)
    readonly property real toolsTop: heading.implicitHeight + 8
    readonly property real resultsTop: toolsTop + tools.implicitHeight + 12
    readonly property real feedbackHeight: conversionMessage.visible ? conversionMessage.implicitHeight + 8 : 0
    // Leave room to read the results heading and at least one complete row.
    readonly property bool shortHeight: maximumPanelHeight < resultsTop + feedbackHeight + 120
    readonly property real listTop: shortHeight ? toolsTop : resultsTop + results.headerHeight
    implicitHeight: Math.min(maximumPanelHeight, resultsTop + results.implicitHeight + feedbackHeight
        + (shortHeight ? 0 : results.headerHeight))

    signal manualRequested()
    signal actionTriggered(string action)

    RowLayout {
        id: heading
        width: parent.width
        height: implicitHeight
        Text {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            objectName: "measurementModeHeading"
            elide: Text.ElideRight
            text: measurePanel.shortHeight && measurePanel.currentAction
                ? measurePanel.currentAction.label : qsTrId("measure.tools")
            color: Theme.textPrimary
            font.pixelSize: 14
            font.weight: Font.DemiBold
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
            visible: measurePanel.maskConversionAvailable
            Layout.preferredWidth: 28
            Layout.preferredHeight: 28
            explanation: qsTrId("seg.roiHelp")
        }
    }

    // Stable slots keep the grid before the results in the Tab order after resizing.
    Item { id: fixedTools; y: measurePanel.toolsTop }
    ColumnLayout {
        id: tools
        parent: measurePanel.shortHeight ? scrollingTools : fixedTools
        width: results.width
        height: implicitHeight
        spacing: 8

        Text {
            objectName: "measurementCalibrationWarning"
            Layout.fillWidth: true
            visible: !!measurePanel.viewportController
                && measurePanel.viewportController.loadState === "ready"
                && !measurePanel.viewportController.hasPhysicalSpacing
            text: measurePanel.viewportController?.viewportRole === "curved"
                ? qsTrId("cpr.measurementHint") : qsTrId("measurement.noCalibration")
            color: Theme.textSecondary
            font.pixelSize: 12
            wrapMode: Text.Wrap
        }

        GridLayout {
            Layout.fillWidth: true
            enabled: measurePanel.viewportController?.viewportRole !== "curved"
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
                    shortLabel: modelData.shortLabel
                    shortcutAction: modelData.action

                    onClicked: {
                        measurePanel.actionTriggered(modelData.action);
                    }
                }
            }
        }
    }

    Item { id: fixedResultHeader; y: measurePanel.resultsTop }
    Flickable {
        id: scroller
        objectName: "measurementScroll"
        width: parent.width
        y: measurePanel.listTop
        height: Math.max(0, measurePanel.height - y - measurePanel.feedbackHeight)
        contentWidth: width
        contentHeight: results.y + results.implicitHeight
        flickableDirection: Flickable.VerticalFlick
        boundsBehavior: Flickable.StopAtBounds
        clip: true

        Item { id: scrollingTools }
        MeasurementResults {
            id: results
            fixedHeaderParent: measurePanel.shortHeight ? null : fixedResultHeader
            y: measurePanel.shortHeight ? tools.implicitHeight + 12 : 0
            // Keep wrapped rows stable when the scrollbar appears or disappears.
            width: Math.max(0, scroller.width - 8)
            height: implicitHeight
            controller: measurePanel.resultsController
            dicomResults: measurePanel.dicomResults
            maskConversionAvailable: measurePanel.maskConversionAvailable && !measurePanel.toolController?.mprProjectionEnabled
        }
        Connections {
            target: scroller.Window.window
            function onActiveFocusItemChanged() {
                ScrollFocus.revealFocused(scroller, scroller.Window.window?.activeFocusItem)
            }
        }
        WheelHandler {
            target: null
            onWheel: event => {
                scroller.cancelFlick()
                const delta = event.pixelDelta.y || event.angleDelta.y / 3
                scroller.contentY = Math.max(0, Math.min(scroller.contentHeight - scroller.height, scroller.contentY - delta))
                event.accepted = true
            }
        }
        Basic.ScrollBar.vertical: Widgets.AppScrollBar { width: 5 }
    }

    Text {
        id: conversionMessage
        objectName: "roiConversionMessage"
        anchors.bottom: parent.bottom
        width: parent.width
        visible: results.maskConversionAvailable && text !== ""
        text: measurePanel.dicomResults?.operation === "convert" ? measurePanel.dicomResults.message : ""
        color: measurePanel.dicomResults?.isError ? Theme.dangerColor : Theme.textSecondary
        font.pixelSize: 12
        wrapMode: Text.Wrap
        textFormat: Text.PlainText
    }
}
