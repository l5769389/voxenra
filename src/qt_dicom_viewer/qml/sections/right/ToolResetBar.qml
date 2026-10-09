pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../components" as Components
import "components" as Controls
import "../../theme"
Rectangle {
    id: root
    objectName: "toolResetBar"
    required property var toolController
    property var voiController: null
    property bool collapsed: false
    property bool expansionAllowed: true
    property bool playbackActive: false
    property bool volumeContext: false
    readonly property bool resetAvailable: (toolController?.tools ?? []).some(tool =>
        tool.toolType === "reset" && tool.available !== false && tool.enabled !== false)
    signal collapseRequested()
    readonly property string panel: toolController?.activePanel ?? ""
    readonly property bool voiActions: !!voiController && ["segmentation", "voi"].includes(panel)
    readonly property bool showReset: collapsed ? resetAvailable : !!toolController?.canResetActiveTool
    implicitHeight: collapsed && showReset ? 80 : 40
    color: Theme.panelBackgroundStrong
    Controls.ToolActionButton {
        objectName: "activeToolReset"
        visible: !root.collapsed && !root.voiActions && root.showReset
        anchors.fill: parent; anchors.margins: 4; anchors.rightMargin: 42
        iconName: "reset"
        label: root.toolController ? root.toolController.resetLabel : qsTrId("text.0576")
        enabled: root.showReset && !root.playbackActive
        hoverColor: Theme.resetActionHover
        pressedColor: Theme.resetActionPressed
        onClicked: root.toolController.resetActiveTool()
    }
    RowLayout {
        objectName: "voiBottomActions"
        anchors.fill: parent
        anchors.margins: 4
        anchors.rightMargin: 42
        spacing: 8
        visible: !root.collapsed && root.voiActions
        Controls.ToolActionButton {
            objectName: "voiClearKind"
            iconName: "clear"
            iconSize: 22
            label: text
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            Layout.preferredHeight: 32
            compact: true
            baseBorderWidth: 1
            baseBorderColor: Theme.controlBorder
            disabledColor: Theme.controlBackground
            text: root.panel === "segmentation" ? qsTrId("text.0739") : qsTrId("text.0740")
            enabled: !root.playbackActive && (root.voiController?.items ?? []).some(item => item.kind === root.panel)
            onClicked: root.voiController.clear(root.panel)
        }
        Controls.ToolActionButton {
            objectName: "voiClearAll"
            iconName: "delete"
            iconSize: 22
            label: text
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            Layout.preferredHeight: 32
            compact: true
            baseBorderWidth: 1
            baseBorderColor: Theme.controlBorder
            disabledColor: Theme.controlBackground
            text: qsTrId("text.0741")
            textColor: Theme.warningColor
            enabled: !root.playbackActive && (root.voiController?.items?.length ?? 0) > 0
            onClicked: root.voiController.clear("")
        }
    }
    Components.ToolbarAction {
        visible: root.collapsed && root.showReset
        anchors.top: parent.top; anchors.topMargin: 4
        anchors.horizontalCenter: parent.horizontalCenter
        width: 32; height: 32
        buttonObjectName: "compactToolReset"
        iconName: "reset"
        label: root.volumeContext ? qsTrId("mpr.tools.resetVolume") : qsTrId("tools.resetAll")
        tooltipPlacement: "left"
        resetAction: true
        actionEnabled: root.resetAvailable && !root.playbackActive
        onTriggered: root.toolController.activateTool("reset")
    }
    Components.ToolbarAction {
        anchors.right: parent.right; anchors.rightMargin: root.collapsed ? 5 : 4
        anchors.bottom: parent.bottom; anchors.bottomMargin: 4
        width: 32; height: 32
        buttonObjectName: "toggleRightPanel"
        iconName: root.collapsed ? "chevron-left" : "chevron-right"
        actionEnabled: !root.collapsed || root.expansionAllowed
        label: root.collapsed && !root.expansionAllowed ? qsTrId("layout.expandNeedsSpace")
            : root.collapsed ? qsTrId("tools.expand") : qsTrId("tools.collapse")
        onTriggered: root.collapseRequested()
    }
}
