pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../components" as Components
import "../../theme"
import "ToolLabels.js" as ToolLabels

Rectangle {
    id: toolBar
    objectName: "primaryToolBar"
    required property var toolController
    property var viewportController: null
    readonly property var volumeController: viewportController && viewportController.viewportType === "volume" ? viewportController : null
    property bool playbackActive: false
    property var tabController: null
    readonly property bool showToolLabels: toolController?.settingsController?.values.appearance.toolLabels ?? false
    readonly property real toolHeight: showToolLabels ? 54 : 36
    readonly property var tools: (toolController?.orderedToolbarTools ?? []).filter(t =>
        t.toolType !== "service" || !viewportController?.workspaceTab?.twoDLayout || viewportController.viewportType === "stack")
    // Resolve by explicit priority order; catalog insertion must not reshuffle these rows.
    function orderedTools(keys) {
        return (keys ?? []).map(key => tools.find(t => t.toolType === key)).filter(t => !!t)
    }
    readonly property var commonTools: orderedTools(toolController?.toolbarGroups?.common)
    readonly property var featureTools: orderedTools(toolController?.toolbarGroups?.primary)
    readonly property var moreTools: orderedTools(toolController?.toolbarGroups?.more)
    readonly property bool customized: toolController?.toolbarGroups?.customized ?? false
    readonly property var extraTools: customized ? moreTools : moreTools.filter(t => !["import", "export", "reset"].includes(t.toolType))
    readonly property var documentTools: customized ? [] : moreTools.filter(t => ["import", "export", "reset"].includes(t.toolType))
    property bool moreExpanded: false
    property string feedbackTool: ""
    signal toolTriggered(var toolDefinition)
    onToolControllerChanged: moreExpanded = false
    onViewportControllerChanged: moreExpanded = false
    onVisibleChanged: if (!visible) moreExpanded = false
    implicitHeight: content.implicitHeight + 12
    color: Theme.panelBackgroundStrong
    radius: Theme.controlRadius
    Timer { id: feedbackTimer; interval: 180; onTriggered: toolBar.feedbackTool = "" }

    component ToolAction: Components.ToolbarAction {
        required property var modelData
        readonly property bool bedAction: modelData.toolType === "volume-bed"
        readonly property bool playback: ["play", "slice-play"].includes(modelData.toolType)
        readonly property string playMode: modelData.toolType === "slice-play" || !toolBar.tabController?.temporalPlayback ? "slice" : "phase"
        readonly property bool running: playback && toolBar.playbackActive && toolBar.tabController?.playbackMode === playMode


        buttonObjectName: "primaryTool-" + modelData.toolType
        showLabel: toolBar.showToolLabels
        shortLabel: running ? qsTrId("tools.short.stop")
            : ToolLabels.label(modelData, toolBar.viewportController?.displayMappingEditor, true)
        label: modelData.toolType === "reset" && toolBar.volumeController
            ? qsTrId("mpr.tools.resetVolume") : running
            ? qsTrId("playback.stop") : ToolLabels.label(modelData, toolBar.viewportController?.displayMappingEditor, false)
        iconName: running ? (playMode === "phase" ? "cine-4d-stop" : "cine-stop") : modelData.iconName
        iconSize: Theme.toolbarIconSize
        placeholder: modelData.available === false
        actionEnabled: (!toolBar.playbackActive || running)
            && (!playback || running || (playMode === "phase" ? !!toolBar.tabController?.phasePlaybackAvailable : !!toolBar.tabController?.slicePlaybackAvailable))
            && (!bedAction || (toolBar.volumeController
                && toolBar.volumeController.bedRemovalAvailable && !toolBar.volumeController.editBusy))
        checked: playback ? running : bedAction ? !!toolBar.volumeController?.bedRemovalEnabled
            : modelData.toolType === toolBar.feedbackTool
            || modelData.toolType === toolBar.toolController?.activeTool
        resetAction: modelData.toolType === "reset"
        directionFace: modelData.toolType === "volume-direction"
            ? (toolBar.volumeController ? toolBar.volumeController.currentFace : "A") : ""
        directionColor: toolBar.volumeController
            ? toolBar.volumeController.currentFaceColor : Theme.iconDefault
        tooltipText: label + (placeholder ? qsTrId("text.0710")
            : !actionEnabled ? (toolBar.playbackActive ? qsTrId("text.0743") : toolBar.volumeController && toolBar.volumeController.editBusy ? qsTrId("text.0744") : qsTrId("text.0745"))
            : directionFace !== "" ? " · " + directionFace : "")
        onTriggered: {
            if (modelData.behavior === "command") {
                toolBar.feedbackTool = modelData.toolType
                feedbackTimer.restart()
            }
            toolBar.toolTriggered(modelData)
            if (!playback) toolBar.moreExpanded = false
        }
    }

    ColumnLayout {
        id: content
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: 6
        spacing: 4
        RowLayout {
            Layout.fillWidth: true
            spacing: 2
            Repeater {
                model: toolBar.commonTools
                delegate: ToolAction {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.preferredWidth: 1
                    Layout.preferredHeight: toolBar.toolHeight
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 2
            Repeater {
                model: toolBar.featureTools
                delegate: ToolAction {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.preferredWidth: 1
                    Layout.preferredHeight: toolBar.toolHeight
                }
            }
            Components.ToolbarAction {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.preferredWidth: 1
                Layout.preferredHeight: toolBar.toolHeight
                showLabel: toolBar.showToolLabels
                shortLabel: qsTrId("tools.short.more")
                buttonObjectName: "primaryToolsMore"
                iconName: "more"
                iconSize: Theme.toolbarIconSize
                label: qsTrId("tools.group.more")
                checked: toolBar.moreExpanded || [...toolBar.extraTools, ...toolBar.documentTools].some(t => t.toolType === toolBar.toolController?.activeTool)
                onTriggered: toolBar.moreExpanded = !toolBar.moreExpanded
            }
        }
        ColumnLayout {
            visible: toolBar.moreExpanded
            Layout.fillWidth: true
            spacing: 4
            Rectangle { visible: toolBar.extraTools.length > 0; Layout.fillWidth: true; implicitHeight: 1; color: Theme.dividerColor }
            GridLayout {
                Layout.fillWidth: true
                columns: 3
                columnSpacing: 4
                rowSpacing: 4
                Repeater {
                    model: toolBar.extraTools
                    delegate: ToolAction {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.preferredWidth: 1
                        Layout.preferredHeight: toolBar.toolHeight
                    }
                }
            }
            Rectangle { visible: toolBar.documentTools.length > 0; Layout.fillWidth: true; implicitHeight: 1; color: Theme.dividerColor }
            RowLayout {
                visible: toolBar.documentTools.length > 0
                Layout.fillWidth: true
                Repeater {
                    model: toolBar.documentTools
                    delegate: ToolAction {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.preferredWidth: 1
                        Layout.preferredHeight: toolBar.toolHeight
                    }
                }
            }
        }
    }
    Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 1; color: Theme.dividerColor }
}
