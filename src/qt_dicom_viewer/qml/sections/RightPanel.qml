pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Window
import "../components/ScrollFocus.js" as ScrollFocus
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
    readonly property string readingMenu: visible && enabled && toolVisible && !compactPanel.visible
        && (!collapsed || (compactRail.visible && compactRail.expandedTool === toolController?.activePanel))
        ? toolController?.activePanel || (!collapsed && toolController?.canResetActiveTool ? toolController.activeTool : "") : ""
    readonly property var listPanel: collapsed ? compactRail.visiblePalette : toolDetailPanel.loadedPanel
    property var tabController: null
    property var exportController: null
    property Item exportItem: null
    signal manualRequested(string chapter)
    readonly property var volumeController: viewportController && viewportController.viewportType === "volume"
        ? viewportController : null
    readonly property bool resetEnabled: !!viewportController && !volumeController?.editBusy
        && (toolController?.activeTool !== "registration" || !!viewportController?.reconstructionController?.ready)
    readonly property string regionCalculationError:
        (tabController?.voiController ?? viewportController?.voiController)?.error ?? ""
    function revealRegionError() {
        if (regionCalculationError === "") return
        Qt.callLater(() => {
            if (rightPanel.regionCalculationError === "") return
            if (!rightPanel.collapsed && ["voi", "segmentation"].includes(rightPanel.toolController?.activePanel))
                detailFlickable.contentY = 0
            if (compactPanel.visible && ["voi", "segmentation"].includes(compactPanel.panelTool))
                compactDetailFlickable.contentY = 0
        })
    }
    onRegionCalculationErrorChanged: revealRegionError()

    color: Theme.panelBackground
    border.color: Theme.panelBorder
    border.width: 1
    radius: 8
    clip: true

    // Window limits can briefly collapse this panel while a tool component is
    // still being constructed. Apply the final compact state after layout;
    // changing the active tool here would destroy its own Loader context.
    onCollapsedChanged: { compactPanel.close(); Qt.callLater(syncCompactTool); revealRegionError() }
    onToolControllerChanged: { compactPanel.close(); Qt.callLater(syncCompactTool) }
    onViewportControllerChanged: compactPanel.close()
    onVisibleChanged: if (!visible) compactPanel.close()
    function syncCompactTool() {
        const tool = toolController?.activeTool
        if (!visible || !compactRail.directTools.includes(tool)) return
        if (collapsed && toolController.activePanel)
            toolController.activateDirectTool(tool)
        else if (!collapsed && !toolController.activePanel)
            toolController.activateTool(tool)
    }
    function selectPrimaryTool(tool) {
        if (visible && collapsed) compactRail.selectFromShortcut(tool)
        else toolController?.activateTool(tool)
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
            id: compactRail
            visible: rightPanel.collapsed
            Layout.fillWidth: true
            Layout.fillHeight: true
            toolController: rightPanel.toolController
            viewportController: rightPanel.viewportController
            tabController: rightPanel.tabController
            panelPopup: compactPanel
            onPanelRequested: (tool, closeOnly) => {
                if (closeOnly || (compactPanel.visible && compactPanel.panelTool === tool)) compactPanel.close()
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
                rightPanel.selectPrimaryTool(toolDefinition.toolType)
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

        Item {
            id: paletteHeadingSlot
            visible: children.length > 0 && !rightPanel.collapsed
            Layout.fillWidth: true
            Layout.leftMargin: 12
            Layout.rightMargin: 22
            Layout.topMargin: 10
            Layout.bottomMargin: 4
            implicitHeight: childrenRect.height
        }

        Flickable {
            id: detailFlickable
            visible: !rightPanel.collapsed
            objectName: "toolDetailFlickable"

            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            readonly property bool measures: toolDetailPanel.activePanel === "measure"
            interactive: !measures && contentHeight > height
            contentWidth: width
            contentHeight: Math.max(height, toolDetailPanel.implicitHeight)
            boundsBehavior: Flickable.StopAtBounds

            Connections {
                target: rightPanel.Window.window
                function onActiveFocusItemChanged() {
                    if (detailFlickable.interactive && detailFlickable.visible)
                        ScrollFocus.revealFocused(detailFlickable, rightPanel.Window.window?.activeFocusItem)
                }
            }
            Right.ToolDetailPanel {
                id: toolDetailPanel
                paletteHeadingHost: rightPanel.collapsed ? null : paletteHeadingSlot
                availableHeight: detailFlickable.height

                // Reserve the gutter even before overflow. Otherwise wrapped
                // text changes the height, which changes this width again and
                // can trap narrow measurement panels in a Qt layout loop.
                width: Math.max(0, detailFlickable.width - (detailFlickable.measures ? 0 : 10))
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
                policy: !detailFlickable.measures && detailFlickable.contentHeight
                    > detailFlickable.height
                    ? Basic.ScrollBar.AsNeeded
                    : Basic.ScrollBar.AlwaysOff
            }
        }

        Right.ToolResetBar {
            Layout.fillWidth: true
            Layout.minimumHeight: implicitHeight
            toolController: rightPanel.toolController
            voiController: rightPanel.tabController?.voiController ?? rightPanel.viewportController?.voiController ?? null
            cprController: rightPanel.tabController?.cprController ?? null
            qaController: rightPanel.viewportController?.qaController ?? null
            historyController: rightPanel.tabController?.historyController ?? null
            exportItem: rightPanel.exportItem
            collapsed: rightPanel.collapsed
            volumeContext: !!rightPanel.volumeController
            playbackActive: rightPanel.tabController?.playing ?? false
            resetEnabled: rightPanel.resetEnabled
        }
    }

    Connections {
        target: rightPanel.toolController ?? null
        function onActivePanelChanged() {
            detailFlickable.contentY = detailFlickable.originY
            rightPanel.revealRegionError()
        }
        function onActiveToolChanged() {
            if (rightPanel.toolController.activeTool !== compactPanel.panelTool) compactPanel.close()
        }
    }
    Connections {
        target: rightPanel.tabController?.playing !== undefined ? rightPanel.tabController : null
        function onPlayingChanged() { compactPanel.close() }
    }
    Components.ToolFlyout {
        id: compactPanel
        onOpened: rightPanel.revealRegionError()
        objectName: "compactVolumePanel"
        parent: rightPanel
        property string panelTool: ""
        property bool detailsLoaded: false
        onVisibleChanged: {
            if (visible) detailsLoaded = true
            // A native popup can close during a nested event loop while its
            // panel is being built. Unload after construction has unwound.
            else Qt.callLater(function() {
                if (!compactPanel.visible) compactPanel.detailsLoaded = false
            })
        }
        readonly property bool cprActions: panelTool === "cpr-path" && !!rightPanel.tabController?.cprController
        readonly property real footerHeight: popupFooter.hasActions ? popupFooter.implicitHeight + 4 : 0
        // A native popup remains above the native VTK viewport.
        popupType: Basic.Popup.Window
        x: -width - 8
        y: 28
        // Popup.Window uses implicit size when creating its native surface.
        // Set it before exposure so the first frame cannot shrink to the title.
        implicitWidth: 280
        width: implicitWidth
        implicitHeight: Math.min(560, (rightPanel.Window.window?.height ?? 640) - 48,
            compactDetails.implicitHeight + chromeHeight + footerHeight)
        height: implicitHeight
        title: rightPanel.toolController?.activeToolLabel ?? ""
        closeButtonName: "compactVolumePanelClose"
        Flickable {
            id: compactDetailFlickable
            objectName: "compactToolDetailFlickable"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: width
            interactive: compactPanel.panelTool !== "measure" && contentHeight > height
            contentHeight: compactDetails.implicitHeight
            boundsBehavior: Flickable.StopAtBounds
            Components.ReadingShortcuts {
                controller: typeof appController !== "undefined" ? appController.shortcutController : null
                toolController: rightPanel.toolController
                tabController: rightPanel.tabController
                listPanel: compactDetails.loadedPanel
                ownerPopup: compactPanel
                menuOnly: true
                activeMenu: compactPanel.opened && rightPanel.visible && rightPanel.enabled
                    && compactPanel.panelTool === rightPanel.toolController?.activePanel ? compactPanel.panelTool : ""
                cprPanelFocused: compactPanel.cprActions
                controlFocused: Window.window?.activeFocusItem?.checkable !== undefined
                function ownsFocus(item) {
                    for (let current = item; current; current = current.parent) {
                        if (current.selectByMouse !== undefined) return false
                        if (current === compactPanel.contentItem || current === compactPanel.contentItem.parent) return true
                    }
                    return false
                }
                allowed: !!activeMenu
                    && !controller?.recordingAction && ownsFocus(Window.window?.activeFocusItem)
            }
            Right.ToolDetailPanel {
                id: compactDetails
                availableHeight: Math.min(560, (rightPanel.Window.window?.height ?? 640) - 48)
                    - compactPanel.chromeHeight - compactPanel.footerHeight
                width: parent.width - (compactPanel.panelTool === "measure" ? 0 : 8)
                height: implicitHeight
                activePanel: compactPanel.detailsLoaded ? compactPanel.panelTool : ""
                onManualRequested: chapter => rightPanel.manualRequested(chapter)
                viewportController: rightPanel.viewportController
                toolController: rightPanel.toolController
                tabController: rightPanel.tabController
                exportController: rightPanel.exportController
                exportItem: rightPanel.exportItem
            }
            Basic.ScrollBar.vertical: Components.AppScrollBar { width: 3 }
        }
        Right.ToolResetBar {
            id: popupFooter
            objectName: "compactPanelFooter"
            Layout.fillWidth: true
            Layout.minimumHeight: implicitHeight
            panel: compactPanel.panelTool
            toolController: rightPanel.toolController
            voiController: rightPanel.tabController?.voiController ?? rightPanel.viewportController?.voiController ?? null
            cprController: rightPanel.tabController?.cprController ?? null
            qaController: rightPanel.viewportController?.qaController ?? null
            historyController: rightPanel.tabController?.historyController ?? null
            exportItem: rightPanel.exportItem
            playbackActive: rightPanel.tabController?.playing ?? false
            resetEnabled: rightPanel.resetEnabled
        }
    }
}
