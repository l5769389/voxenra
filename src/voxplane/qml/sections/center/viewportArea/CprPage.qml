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
    property bool capturingPng: false
    property bool anonymousExport: false
    readonly property bool results: controller?.resultView ?? false
    readonly property bool stackedResults: results && width < 720
    readonly property bool splitResults: results && !(controller?.focusedViewportId ?? "")
    readonly property real minimumResultWidth: Math.min(280, Math.floor(resultContentWidth / 5))
    readonly property real splitHandleWidth: 6
    readonly property real resultContentWidth: Math.max(0, width - splitHandleWidth)
    readonly property real curvedResultWidth: Math.max(minimumResultWidth,
        Math.min(resultContentWidth - minimumResultWidth, resultContentWidth * (controller?.resultSplitRatio ?? 2/3)))
    readonly property real resultContentHeight: Math.max(0, height - splitHandleWidth)
    readonly property real minimumResultHeight: Math.min(100, resultContentHeight / 2)
    readonly property real curvedResultHeight: Math.max(minimumResultHeight,
        Math.min(resultContentHeight - minimumResultHeight, resultContentHeight * (controller?.resultSplitRatio ?? 2/3)))
    function focusActiveViewport() {
        if (!page.visible) return
        for (let i = 0; i < cells.count; ++i) {
            const cell = cells.itemAt(i)
            if (cell?.visible && cell.modelData.viewportId === controller?.activeViewport?.viewportId)
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
    property var focusBeforeResultChange: null
    property bool pendingResultFocus: false
    onVisibleChanged: if (visible && pendingResultFocus) Qt.callLater(focusAfterResultChange)
    function focusAfterResultChange() {
        // The workspace can still be showing its loading page when the CPR
        // result arrives. An invisible item cannot take keyboard focus.
        pendingResultFocus = !visible
        if (pendingResultFocus) return
        const focused = page.Window.window?.activeFocusItem
        // Hiding the focused footer button may give another button focus on
        // Windows. Restore reading focus if the original action disappeared.
        const previous = focusBeforeResultChange
        focusBeforeResultChange = null
        if (previous && !previous.visible && focused?.selectByMouse === undefined) {
            focusActiveViewport()
            return
        }
        // Reconstruction can finish while the user is typing or operating a
        // control. Only redirect focus if it no longer belongs to that control.
        if (focused?.visible && (focused.selectByMouse !== undefined
                || (focused.focusPolicy !== undefined && focused.focusPolicy !== Qt.NoFocus)))
            return
        focusActiveViewport()
    }
    Connections {
        target: page.controller ?? null
        function onResultViewAboutToChange() { page.focusBeforeResultChange = page.Window.window?.activeFocusItem ?? null }
        function onResultViewChanged() { Qt.callLater(page.focusAfterResultChange) }
        function onPathInputFinished() { Qt.callLater(page.focusAfterResultChange) }
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
        rowSpacing: page.splitResults && page.stackedResults ? page.splitHandleWidth : 4
        columnSpacing: page.splitResults ? page.splitHandleWidth : 4
        uniformCellWidths: !page.results
        uniformCellHeights: !(page.splitResults && page.stackedResults)
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
                Layout.preferredWidth: page.splitResults && !page.stackedResults
                    ? (index === 2 ? page.curvedResultWidth : page.resultContentWidth - page.curvedResultWidth) : 1
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumWidth: page.splitResults && !page.stackedResults ? page.minimumResultWidth : 0
                Layout.minimumHeight: page.splitResults && page.stackedResults ? page.minimumResultHeight : 100
                Layout.preferredHeight: page.splitResults && page.stackedResults
                    ? (index === 2 ? page.curvedResultHeight : page.resultContentHeight - page.curvedResultHeight) : 1
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
                            onPointToolFocusToggleRequested: page.controller.focusSingleViewport(cell.focused ? "" : cell.modelData.viewportId)
                            objectName: "cprViewport-" + cell.modelData.viewportRole
                            anchors.fill: parent
                            cprKeysActive: (page.Window.window?.activeReadingMenu ?? page.controller?.toolController?.activePanel) === "cpr-path"
                            viewportController: cell.modelData
                            twoDViewMode: cell.index < 2 && !cell.modelData.historicalPlane
                                ? page.controller?.referencePlanes[cell.index] ?? "axial" : ""
                            hasTabs: true
                            capturingPng: page.capturingPng
                            anonymousExport: page.anonymousExport
                            multiViewport: !cell.focused
                            overlayStatusText: cell.modelData.historicalPlane ? qsTrId("cpr.statusHistoricalPlane")
                                : cell.index < 2 ? ""
                                : page.controller?.drawing && cell.modelData.imageRows > 0 ? qsTrId("cpr.statusPreviousResult")
                                : page.controller?.busy ? (rebuildFeedback.showing ? qsTrId("cpr.statusUpdating") : "")
                                : !page.controller?.ready ? qsTrId("cpr.statusNoResult") : ""
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
        verticalDrag: page.stackedResults
        showGrip: true
        // Use the same geometry as the grid. Under asynchronous incubation
        // itemAt() can return null before the delegates exist, without notifying a binding.
        readonly property real edgeOverlap: 7
        readonly property real extent: verticalDrag ? page.resultContentHeight : page.resultContentWidth
        currentWidth: verticalDrag ? page.curvedResultHeight : page.curvedResultWidth
        x: verticalDrag ? 0 : Math.round(currentWidth) - edgeOverlap
        y: verticalDrag ? Math.round(currentWidth) - edgeOverlap : 0
        width: verticalDrag ? page.width : page.splitHandleWidth + edgeOverlap * 2
        height: verticalDrag ? page.splitHandleWidth + edgeOverlap * 2 : page.height
        minimumWidth: verticalDrag ? page.minimumResultHeight : page.minimumResultWidth
        maximumWidth: extent - minimumWidth
        onWidthDragged: value => { if (extent > 0) page.controller?.setResultSplitRatio(value / extent) }
        onWidthCommitted: value => { if (extent > 0) page.controller?.setResultSplitRatio(value / extent) }
    }
}
