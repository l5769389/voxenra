pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Window
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "right" as Right
import "../theme"
import "../components" as Components

Rectangle {
    id: rightPanel
    objectName: "rightPanel"

    required property var toolController
    required property bool toolVisible
    required property var viewportController
    property bool collapsed: false
    property bool expansionAllowed: true
    signal collapseRequested()
    property var tabController: null
    property var exportController: null
    property Item exportItem: null
    signal manualRequested(string chapter)
    readonly property var volumeController: viewportController && viewportController.viewportType === "volume"
        ? viewportController : null

    color: Theme.panelBackground
    border.color: Theme.panelBorder
    border.width: 1
    radius: 8
    clip: true

    onCollapsedChanged: { compactPanel.close(); syncCompactTool() }
    onToolControllerChanged: { compactPanel.close(); syncCompactTool() }
    onViewportControllerChanged: compactPanel.close()
    onVisibleChanged: if (!visible) compactPanel.close()
    function syncCompactTool() {
        if (collapsed && toolController) {
            const direct = ["window", "ct-window", "pet-window", "scroll", "pan", "zoom", "volume-rotate", "mpr-rotate-3d"]
            const panels = (toolController.tools ?? []).some(t => t.toolType === "volume-preset")
                ? ["volume-preset", "volume-direction", "mpr-layout", "viewport-settings"] : ["mpr-layout", "viewport-settings"]
            if (!["measure", "rotate", "pseudocolor", "annotate", "play", "slice-play", ...panels].includes(toolController.activeTool))
                toolController.activateDirectTool(direct.includes(toolController.activeTool) ? toolController.activeTool : "pan")
        }
    }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 1
        spacing: 0
        visible: rightPanel.toolVisible

        Text {
            objectName: "volumeToolContext"
            visible: !!rightPanel.volumeController
            Layout.fillWidth: true
            Layout.preferredHeight: visible ? 28 : 0
            text: rightPanel.collapsed ? "3D" : qsTrId("mpr.tools.volume")
            color: Theme.primaryColor
            font.pixelSize: 12
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        Right.CompactToolRail {
            visible: rightPanel.collapsed
            Layout.fillWidth: true
            Layout.fillHeight: true
            toolController: rightPanel.toolController
            viewportController: rightPanel.viewportController
            tabController: rightPanel.tabController
            onPanelRequested: tool => {
                if (compactPanel.opened && compactPanel.panelTool === tool) compactPanel.close()
                else { compactPanel.panelTool = tool; compactPanel.open() }
            }
        }
        Right.PrimaryToolBar {
            visible: !rightPanel.collapsed
            Layout.fillWidth: true
            Layout.preferredHeight: implicitHeight
            toolController: rightPanel.toolController
            viewportController: rightPanel.viewportController
            playbackActive: rightPanel.tabController?.playing ?? false
            tabController: rightPanel.tabController

            onToolTriggered: toolDefinition => {
                rightPanel.toolController?.activateTool(
                    toolDefinition.toolType
                )
                if (["play", "slice-play"].includes(toolDefinition.toolType))
                    rightPanel.tabController?.togglePlaybackMode(toolDefinition.toolType === "slice-play"
                        || !rightPanel.tabController.temporalPlayback ? "slice" : "phase")
            }
        }

        Text {
            objectName: "volumeEditStatus"
            Layout.fillWidth: true
            Layout.margins: visible ? 10 : 0
            visible: !rightPanel.collapsed && !!rightPanel.volumeController && (rightPanel.volumeController.bedRemovalEnabled
                || rightPanel.volumeController.editMessage !== "")
            text: rightPanel.volumeController
                ? [rightPanel.volumeController.bedRemovalEnabled ? qsTrId("text.0676") : "",
                    rightPanel.volumeController.editMessage].filter(s => s !== "").join("\n") : ""
            color: Theme.textSecondary
            font.pixelSize: 12
            wrapMode: Text.Wrap
        }

        Flickable {
            id: detailFlickable
            visible: !rightPanel.collapsed
            objectName: "toolDetailFlickable"

            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: width
            contentHeight: Math.max(
                height,
                toolDetailPanel.implicitHeight
            )
            boundsBehavior: Flickable.StopAtBounds

            Right.ToolDetailPanel {
                id: toolDetailPanel

                // Reserve the gutter even before overflow. Otherwise wrapped
                // text changes the height, which changes this width again and
                // can trap narrow measurement panels in a Qt layout loop.
                width: Math.max(0, detailFlickable.width - 10)
                height: detailFlickable.contentHeight
                toolController: rightPanel.toolController
                activePanel: rightPanel.toolController
                    ? rightPanel.toolController.activePanel
                    : ""
                viewportController: rightPanel.viewportController
                tabController: rightPanel.tabController
                exportController: rightPanel.exportController
                exportItem: rightPanel.exportItem
                onManualRequested: chapter => rightPanel.manualRequested(chapter)
            }

            Basic.ScrollBar.vertical: Components.AppScrollBar {
                policy: detailFlickable.contentHeight
                    > detailFlickable.height
                    ? Basic.ScrollBar.AsNeeded
                    : Basic.ScrollBar.AlwaysOff
            }
        }

        Right.ToolResetBar {
            Layout.fillWidth: true
            Layout.minimumHeight: implicitHeight
            Layout.maximumHeight: implicitHeight
            collapsed: rightPanel.collapsed
            expansionAllowed: rightPanel.expansionAllowed
            playbackActive: rightPanel.tabController?.playing ?? false
            volumeContext: !!rightPanel.volumeController
            onCollapseRequested: rightPanel.collapseRequested()
            toolController: rightPanel.toolController
            voiController: rightPanel.tabController?.voiController ?? rightPanel.viewportController?.voiController ?? null
        }
    }

    Connections {
        target: rightPanel.toolController ?? null
        function onActiveToolChanged() {
            if (rightPanel.toolController.activeTool !== compactPanel.panelTool) compactPanel.close()
        }
    }
    Connections {
        target: rightPanel.tabController?.playing !== undefined ? rightPanel.tabController : null
        function onPlayingChanged() { compactPanel.close() }
    }
    Basic.Popup {
        id: compactPanel
        objectName: "compactVolumePanel"
        property string panelTool: ""
        // A native popup remains above the native VTK viewport.
        popupType: Basic.Popup.Window
        x: -width - 8
        y: 28
        // Popup.Window uses implicit size when creating its native surface.
        // Set it before exposure so the first frame cannot shrink to the title.
        implicitWidth: 280
        width: implicitWidth
        implicitHeight: Math.min(560, (rightPanel.Window.window?.height ?? 640) - 48,
            compactDetails.implicitHeight + 56)
        height: implicitHeight
        padding: 8
        margins: 8
        focus: true
        closePolicy: Basic.Popup.CloseOnEscape | Basic.Popup.CloseOnPressOutside
        background: Rectangle { color: Theme.elevatedBackground; radius: Theme.controlRadius }
        contentItem: ColumnLayout {
            spacing: 8
            RowLayout {
                Layout.fillWidth: true
                Text {
                    Layout.fillWidth: true
                    text: rightPanel.toolController?.activeToolLabel ?? ""
                    color: Theme.textPrimary
                    font.pixelSize: 14
                    font.bold: true
                }
                Components.ToolbarAction {
                    width: 28; height: 28
                    buttonObjectName: "compactVolumePanelClose"
                    iconName: "close"
                    label: qsTrId("text.0621")
                    onTriggered: compactPanel.close()
                }
            }
            Flickable {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                contentWidth: width
                contentHeight: compactDetails.implicitHeight
                boundsBehavior: Flickable.StopAtBounds
                Right.ToolDetailPanel {
                    id: compactDetails
                    width: parent.width - 8
                    height: implicitHeight
                    activePanel: compactPanel.visible ? compactPanel.panelTool : ""
                    viewportController: rightPanel.viewportController
                    toolController: rightPanel.toolController
                    tabController: rightPanel.tabController
                }
                Basic.ScrollBar.vertical: Components.AppScrollBar { width: 3 }
            }
        }
    }
}
