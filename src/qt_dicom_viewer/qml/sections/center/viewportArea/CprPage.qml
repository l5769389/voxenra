pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import "../../../components" as Components
import "../../../theme"

Item {
    id: page
    objectName: "cprPage"
    required property var controller
    property bool anonymousExport: false
    readonly property bool results: controller?.resultView ?? false
    readonly property bool stackedResults: results && width < 720
    readonly property bool splitResults: results && !stackedResults && !(controller?.focusedViewportId ?? "")
    readonly property real minimumResultWidth: 280
    readonly property real splitHandleWidth: 8
    readonly property real resultContentWidth: Math.max(0, width - splitHandleWidth)
    readonly property real curvedResultWidth: Math.max(minimumResultWidth,
        Math.min(resultContentWidth - minimumResultWidth, resultContentWidth * (controller?.resultSplitRatio ?? 2/3)))
    function focusActiveViewport() {
        if (!page.visible) return
        for (let i = 0; i < cells.count; ++i) {
            const cell = cells.itemAt(i)
            if (cell?.visible && cell.modelData === controller?.activeViewport)
                cell.imageItem.forceActiveFocus()
        }
    }
    function restoreVisibleFocus() {
        for (let i = 0; i < cells.count; ++i) {
            const cell = cells.itemAt(i)
            if (cell && !cell.visible && cell.imageItem.activeFocus) {
                focusActiveViewport()
                return
            }
        }
    }
    function focusAfterResultChange() {
        const focused = page.Window.window?.activeFocusItem
        // Reconstruction can finish while the user is typing or operating a
        // control. Only redirect focus if it no longer belongs to that control.
        if (focused?.visible && (focused.selectByMouse !== undefined
                || (focused.focusPolicy !== undefined && focused.focusPolicy !== Qt.NoFocus)))
            return
        focusActiveViewport()
    }
    Connections {
        target: page.controller ?? null
        function onResultViewChanged() { Qt.callLater(page.focusAfterResultChange) }
        function onPathInputStarted() { Qt.callLater(page.focusActiveViewport) }
        function onViewLayoutChanged() { Qt.callLater(page.restoreVisibleFocus) }
    }
    Components.DelayedActivity {
        id: rebuildFeedback
        active: page.visible && (page.controller?.busy ?? false)
        activityKey: page.controller
    }
    function activeExportItem() {
        if (!controller) return null
        if (controller.exportScope === "combined") return page
        for (let i = 0; i < cells.count; i++) {
            const cell = cells.itemAt(i)
            if (cell.modelData.viewportRole === controller.exportScope) return cell.imageItem
        }
        return null
    }
    GridLayout {
        anchors.fill: parent
        rowSpacing: 4
        columnSpacing: page.splitResults ? page.splitHandleWidth : 4
        uniformCellWidths: !page.results
        uniformCellHeights: true
        Repeater {
            id: cells
            model: page.controller?.cprViews ?? []
            delegate: Rectangle {
                id: cell
                required property int index
                required property var modelData
                property alias imageItem: viewport
                readonly property bool focused: (page.controller?.focusedViewportId ?? "") !== ""
                visible: focused ? page.controller?.focusedViewportId === modelData.viewportId : !page.results || index >= 2
                Layout.row: !visible ? index + 2 : focused ? 0
                    : page.results ? (page.stackedResults ? Math.max(0, index - 2) : 0) : Math.floor(index / 2)
                Layout.column: focused || page.stackedResults ? 0 : index % 2
                Layout.preferredWidth: page.splitResults
                    ? (index === 2 ? page.curvedResultWidth : page.resultContentWidth - page.curvedResultWidth) : 1
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumWidth: page.splitResults ? page.minimumResultWidth : 0
                Layout.minimumHeight: 100
                color: Theme.canvasBackground
                border.color: page.controller?.activeViewport === modelData ? Theme.primaryColor : Theme.controlBorder
                border.width: 1
                Item {
                    anchors.fill: parent
                    anchors.margins: 2
                    Item {
                        anchors.fill: parent
                        Viewport {
                            id: viewport
                            objectName: "cprViewport-" + cell.modelData.viewportRole
                            anchors.fill: parent
                            viewportController: cell.modelData
                            twoDViewMode: cell.index < 2 && !cell.modelData.historicalPlane
                                ? page.controller?.referencePlanes[cell.index] ?? "axial" : ""
                            hasTabs: true
                            anonymousExport: page.anonymousExport
                            multiViewport: !cell.focused
                            overlayStatusText: cell.modelData.historicalPlane ? "HISTORICAL PLANE"
                                : cell.index < 2 ? ""
                                : page.controller?.drawing && cell.modelData.imageRows > 0 ? "PREVIOUS RESULT"
                                : page.controller?.busy ? (rebuildFeedback.showing ? "UPDATING" : "")
                                : !page.controller?.ready ? "NO RESULT" : ""
                            TapHandler {
                                onPressedChanged: if (pressed) page.controller?.activateViewport(cell.modelData.viewportId)
                            }
                        }
                        // Reuse the 2D plane selector outside the exported image.
                        // Neither reference plane has a primary/secondary role.
                        TwoDViewSelector {
                            objectName: "cprPlane-" + cell.index
                            readonly property var overlay: viewport.cornerOverlay
                            x: 10; y: 10; z: 40
                            visible: cell.index < 2 && !cell.modelData.historicalPlane && !page.anonymousExport
                            width: Math.min(overlay?.selectorWidth ?? 70, Math.max(0, parent.width - x - 4))
                            height: overlay?.selectorHeight ?? 24
                            font.pixelSize: overlay?.textPixelSize ?? 12
                            mode: viewport.twoDViewMode
                            model: [
                                {value: "axial", label: qsTrId("layout.axialReconstruction"), group: ""},
                                {value: "coronal", label: qsTrId("layout.coronalReconstruction"), group: ""},
                                {value: "sagittal", label: qsTrId("layout.sagittalReconstruction"), group: ""}
                            ]
                            onActivationRequested: page.controller?.activateViewport(cell.modelData.viewportId)
                            onModeSelected: mode => page.controller?.setReferencePlane(cell.index, mode)
                        }
                    }
                }
            }
        }
    }
    Components.WidthResizeHandle {
        objectName: "cprResultSplitHandle"
        visible: page.splitResults && !page.anonymousExport
        enabled: page.splitResults
        x: (cells.itemAt(2)?.x ?? 0) + (cells.itemAt(2)?.width ?? 0)
        y: 0
        width: page.splitHandleWidth
        height: page.height
        currentWidth: cells.itemAt(2)?.width ?? page.curvedResultWidth
        minimumWidth: page.minimumResultWidth
        maximumWidth: page.resultContentWidth - page.minimumResultWidth
        onWidthDragged: value => page.controller?.setResultSplitRatio(value / page.resultContentWidth)
        onWidthCommitted: value => page.controller?.setResultSplitRatio(value / page.resultContentWidth)
    }
}
