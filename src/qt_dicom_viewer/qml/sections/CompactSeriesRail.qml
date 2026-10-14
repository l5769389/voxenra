pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import "../components" as Components
import "../theme"

Item {
    id: rail
    objectName: "compactSeriesRail"
    required property var panelController
    property var pacsController: null
    property var workspaceController: null
    property bool showLabels: false
    signal contextRequested(string uid, real sceneX, real sceneY)
    property string anchorKey: ""
    property int anchorIndex: 0
    property real anchorOffset: 0
    property bool restorePending: false
    property bool resetPending: false

    function captureScroll(reset) {
        resetPending = resetPending || reset
        if (restorePending) return
        restorePending = true
        const index = listing.indexAt(1, listing.contentY + 1)
        const item = listing.itemAtIndex(index)
        anchorIndex = Math.max(0, index)
        anchorKey = panelController.compactSidebarModel.keyAt(index)
        anchorOffset = item ? item.y - listing.contentY : 0
    }
    function restoreScroll() {
        listing.forceLayout()
        if (resetPending || !listing.count) {
            listing.positionViewAtBeginning()
        } else {
            const found = panelController.compactSidebarModel.indexOfKey(anchorKey)
            const index = found >= 0 ? found : Math.min(anchorIndex, listing.count - 1)
            listing.positionViewAtIndex(index, ListView.Beginning)
            const item = listing.itemAtIndex(index)
            if (item) {
                const lower = listing.originY
                const upper = lower + Math.max(0, listing.contentHeight - listing.height)
                listing.contentY = Math.max(lower, Math.min(item.y - anchorOffset, upper))
            }
        }
        restorePending = false
        resetPending = false
    }
    Connections {
        target: rail.panelController.compactSidebarModel
        function onStructureAboutToChange(reset) { rail.captureScroll(reset) }
        function onStructureChanged(reset) { Qt.callLater(rail.restoreScroll) }
    }
    Column {
        id: sourceEntries
        anchors.top: parent.top
        anchors.topMargin: 4
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 4
        Components.ToolbarAction {
            tooltipPlacement: "right"
            id: openImport
            buttonObjectName: "compactSidebarImport"
            visible: !rail.pacsController || rail.pacsController.localEnabled
            width: 40; height: rail.showLabels ? 44 : 32
            showLabel: rail.showLabels
            shortLabel: qsTrId("sidebar.short.images")
            label: rail.panelController.scanning ? qsTrId("text.0620") : qsTrId("text.0532")
            tooltipText: label
            iconName: "nav-load-file"
            iconSize: 20
            actionEnabled: true
            onTriggered: rail.panelController.openImportDialog()
        }
        Components.ToolbarAction {
            tooltipPlacement: "right"
            buttonObjectName: "compactSidebarPacs"
            visible: rail.pacsController !== null && rail.pacsController.pacsEnabled
            width: 40; height: rail.showLabels ? 44 : 32
            showLabel: rail.showLabels
            shortLabel: "PACS"
            label: qsTrId("text.0494")
            tooltipText: label
            iconName: "nav-pacs"
            iconSize: 20
            checked: rail.workspaceController?.activeTabType === "pacs"
            actionEnabled: rail.workspaceController !== null
            onTriggered: rail.workspaceController.openPacs()
        }
    }
    ListView {
        id: listing
        objectName: "compactSidebarSeriesList"
        anchors.top: sourceEntries.bottom
        anchors.topMargin: 4
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        model: rail.panelController.compactSidebarModel
        clip: true
        reuseItems: true
        boundsBehavior: Flickable.StopAtBounds
        Basic.ScrollBar.vertical: Components.AppScrollBar { width: 3 }
        function focusRow(index, reason) {
            if (index < 0 || index >= count) return false
            currentIndex = index
            positionViewAtIndex(index, ListView.Contain)
            forceLayout()
            const row = itemAtIndex(index)
            if (row) row.forceActiveFocus(reason)
            return !!row
        }
        delegate: Item {
            id: entry
            required property int index
            required property var modelData
            readonly property string uid: modelData.seriesInstanceUid
            readonly property bool selected: rail.panelController.selectedSeriesUids.includes(uid)
            readonly property bool active: rail.panelController.activeSeriesUid === uid
            objectName: "compactSeries-" + uid
            width: listing.width
            height: 46
            activeFocusOnTab: index === listing.currentIndex
            onActiveFocusChanged: if (activeFocus) {
                listing.currentIndex = index
                listing.positionViewAtIndex(index, ListView.Contain)
            }
            Accessible.role: Accessible.Button
            Accessible.name: modelData.label + " · " + modelData.modality
                + (modelData.subtitle ? " · " + modelData.subtitle : "")
            Accessible.focusable: true
            Accessible.checkable: true
            Accessible.checked: selected
            Accessible.onPressAction: rail.panelController.openSeriesView(uid, "2d")
            Accessible.onToggleAction: rail.panelController.selectSeriesWithModifiers(uid, true)
            Keys.onPressed: event => {
                const backward = event.key === Qt.Key_Backtab || (event.key === Qt.Key_Tab && (event.modifiers & Qt.ShiftModifier))
                if (event.key === Qt.Key_Tab || backward || event.key === Qt.Key_Down || event.key === Qt.Key_Up) {
                    event.accepted = listing.focusRow(index + (backward || event.key === Qt.Key_Up ? -1 : 1),
                        backward ? Qt.BacktabFocusReason : Qt.TabFocusReason)
                } else if (event.key === Qt.Key_Home || event.key === Qt.Key_End) {
                    event.accepted = listing.focusRow(event.key === Qt.Key_Home ? 0 : listing.count - 1, Qt.OtherFocusReason)
                } else if (event.key === Qt.Key_Space) {
                    rail.panelController.selectSeriesWithModifiers(uid, true)
                    event.accepted = true
                } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                    rail.panelController.openSeriesView(uid, "2d")
                    event.accepted = true
                }
            }
            Rectangle {
                anchors.centerIn: parent
                width: 40; height: 40
                radius: 5
                color: entry.selected ? Theme.selectionBackground : Theme.canvasBackground
                border.width: entry.activeFocus || entry.active ? 2 : 1
                border.color: entry.activeFocus ? Theme.focusBorder
                    : entry.active ? Theme.primaryColor : entry.selected ? Theme.selectionBorder
                    : mouse.containsMouse ? Theme.borderStrong : Theme.borderSubtle
                Image {
                    id: thumbnail
                    objectName: "compactThumbnail-" + entry.uid
                    anchors.fill: parent
                    anchors.margins: 3
                    source: entry.modelData.thumbnailUrl
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                    mipmap: true
                    cache: false
                }
                Text {
                    anchors.centerIn: parent
                    visible: thumbnail.status !== Image.Ready
                    text: entry.modelData.modality || "—"
                    color: Theme.textMuted
                    font.pixelSize: 10
                }
                Components.ModalityBadge {
                    objectName: "compactModality-" + entry.uid
                    anchors.left: parent.left
                    anchors.top: parent.top
                    modality: entry.modelData.modality
                    compact: true
                }
                Rectangle {
                    visible: entry.selected
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    width: 12; height: 12; radius: 3
                    color: Theme.selectionBackground
                    Text { anchors.centerIn: parent; text: "✓"; color: Theme.primaryColor; font.pixelSize: 10 }
                }
            }
            Components.SeriesDragArea {
                id: mouse
                seriesUid: entry.uid
                panelController: rail.panelController
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.LeftButton | Qt.RightButton
                cursorShape: Qt.PointingHandCursor
                onClicked: event => {
                    if (event.button === Qt.RightButton) {
                        rail.panelController.selectContextSeries(entry.uid)
                        const point = entry.mapToItem(null, event.x, event.y)
                        rail.contextRequested(entry.uid, point.x, point.y)
                    } else {
                        rail.panelController.selectSeriesWithModifiers(entry.uid,
                            (event.modifiers & (Qt.ControlModifier | Qt.MetaModifier)) !== 0)
                    }
                }
                onDoubleClicked: event => {
                    if (event.button === Qt.LeftButton)
                        rail.panelController.openSeriesView(entry.uid, "2d")
                }
            }
            Components.AppToolTip {
                visible: mouse.containsMouse
                delay: 700
                text: entry.modelData.label + " · " + entry.modelData.modality
                    + (entry.modelData.subtitle ? "\n" + entry.modelData.subtitle : "")
            }
        }
    }
}
