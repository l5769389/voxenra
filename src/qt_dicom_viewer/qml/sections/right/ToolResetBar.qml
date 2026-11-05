pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../components" as Components
import "components" as Controls
import "../../theme"
Rectangle {
    id: root
    objectName: "toolResetBar"
    property string resetObjectName: "activeToolReset"
    required property var toolController
    property var voiController: null
    property var cprController: null
    property bool collapsed: false
    property bool volumeContext: false
    property bool resetEnabled: true
    property bool playbackActive: false
    property string panel: toolController?.activePanel ?? ""
    readonly property bool voiActions: !collapsed && !!voiController && ["segmentation", "voi"].includes(panel)
    readonly property bool cprActions: !collapsed && panel === "cpr-path" && !!(cprController?.drawing || cprController?.pathEditing || cprController?.selectedPathId)
    readonly property var globalReset: collapsed
        ? (toolController?.orderedToolbarTools ?? []).find(t => t.toolType === "reset" && t.available !== false) : null
    readonly property bool showReset: !collapsed && !voiActions && !!toolController?.canResetActiveTool
        && !["measure", "cpr-path"].includes(panel)
    readonly property bool hasActions: collapsed ? !!globalReset : cprActions || voiActions || showReset
    visible: hasActions
    implicitHeight: root.voiActions && voiRow.columns === 1 ? 80 : 44
    color: Theme.panelBackgroundStrong

    Rectangle {
        anchors.top: parent.top
        width: parent.width
        height: 1
        color: Theme.dividerColor
    }
    Components.ToolbarAction {
        visible: root.collapsed && !!root.globalReset
        anchors.centerIn: parent
        width: 32
        height: 32
        buttonObjectName: "compactToolReset"
        iconName: "reset"
        label: root.volumeContext ? qsTrId("mpr.tools.resetVolume") : qsTrId("tools.resetAll")
        tooltipPlacement: "left"
        resetAction: true
        actionEnabled: root.resetEnabled && root.globalReset?.enabled !== false && !root.playbackActive
        onTriggered: root.toolController.activateTool("reset")
    }
    Controls.CprActions {
        visible: root.cprActions
        controller: root.cprController
        anchors.fill: parent
        anchors.margins: 6
    }
    component FooterAction: Controls.ToolActionButton {
        implicitWidth: labeledWidth
        showLabel: true
        centerLabel: true
        fontPixelSize: 13
        iconSize: 18
    }
    FooterAction {
        objectName: visible ? root.resetObjectName : ""
        visible: root.showReset
        anchors.fill: parent; anchors.margins: 6; anchors.leftMargin: 12; anchors.rightMargin: 12
        readonly property bool clearsContent: ["annotate", "service", "volume-crop"].includes(root.toolController?.activeTool)
        iconName: clearsContent ? "clear" : "reset"
        label: root.toolController ? root.toolController.resetLabel : qsTrId("text.0576")
        shortcutAction: (shortcutOwner?.bindings ?? []).some(b => b.action === "view-reset" && b.menus.includes(root.toolController?.activeTool)) ? "view-reset" : ""
        enabled: root.showReset && root.resetEnabled && !root.playbackActive
        hoverColor: Theme.resetActionHover
        pressedColor: Theme.resetActionPressed
        onClicked: root.toolController.resetActiveTool()
    }
    GridLayout {
        id: voiRow
        objectName: "voiBottomActions"
        columns: width >= clearKind.implicitWidth + clearAll.implicitWidth + columnSpacing ? 2 : 1
        columnSpacing: 8
        rowSpacing: 4
        anchors.fill: parent
        anchors.margins: 6
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        visible: root.voiActions
        FooterAction {
            id: clearKind
            objectName: "voiClearKind"
            iconName: "clear"
            label: text
            Layout.fillWidth: true
            Layout.preferredHeight: 32
            compact: true
            baseBorderWidth: 1
            baseBorderColor: Theme.controlBorder
            disabledColor: Theme.controlBackground
            text: root.panel === "segmentation" ? qsTrId("text.0739") : qsTrId("text.0740")
            enabled: !root.playbackActive && (root.voiController?.items ?? []).some(item => item.kind === root.panel)
            onClicked: root.voiController.clear(root.panel)
        }
        FooterAction {
            id: clearAll
            objectName: "voiClearAll"
            iconName: "delete"
            label: text
            Layout.fillWidth: true
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
}
