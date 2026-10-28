pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import "../../components" as Components
import "../../theme"

Rectangle {
    id: listing
    required property var surface
    required property string group
    required property var entries
    // Fixed source entries preserve the actual left navigation's row split.
    property var fixedEntries: []
    readonly property real naturalHeight: tiles.height + 20
    readonly property int tileHeight: 76
    readonly property int gap: 8
    readonly property bool receiving: surface.dragging && surface.targetGroup === group
    readonly property bool permitted: group !== "common" || surface.dragGroup === "common" || entries.length < 7
    color: Theme.panelBackground
    border.color: receiving ? (permitted ? Theme.selectionBorder : Theme.dangerColor) : Theme.borderSubtle
    border.width: receiving ? 2 : 1
    radius: Theme.controlRadius

    function cell(index) {
        let row, column, count
        if (group === "left") {
            const firstCount = Math.min(4, fixedEntries.length + entries.length)
            const position = index + fixedEntries.length
            row = position < firstCount ? 0 : 1
            column = row === 0 ? position : position - firstCount
            count = row === 0 ? firstCount : Math.max(1, entries.length + fixedEntries.length - firstCount)
        } else if (group === "common") {
            row = index < Math.min(4, entries.length) ? 0 : 1
            column = row === 0 ? index : index - Math.min(4, entries.length)
            count = row === 0 ? Math.min(4, entries.length) : Math.max(1, entries.length - 4 + 1)
        } else {
            row = Math.floor(index / 3); column = index % 3; count = 3
        }
        const width = (tiles.width - (count - 1) * gap) / count
        return Qt.rect(column * (width + gap), row * (tileHeight + gap), width, tileHeight)
    }
    function boundary(x, y) {
        for (let i = 0; i < entries.length; ++i) {
            const rect = cell(i)
            if (y < rect.y || (y <= rect.y + rect.height + gap / 2 && x < rect.x + rect.width / 2)) return i
        }
        return entries.length
    }
    function locate(x, y) {
        const bounds = surface.mapToItem(listing, x, y)
        if (!visible || bounds.x < 0 || bounds.x > width || bounds.y < 0 || bounds.y > height) return -1
        const p = surface.mapToItem(scroll, x, y)
        return boundary(p.x, p.y + scroll.contentY)
    }
    function scrollAtPointer() {
        if (!receiving) return
        const p = surface.mapToItem(scroll, surface.pointerX, surface.pointerY)
        const step = p.y < 32 ? -12 : p.y > scroll.height - 32 ? 12 : 0
        if (step) {
            scroll.contentY = Math.max(0, Math.min(Math.max(0, scroll.contentHeight - scroll.height), scroll.contentY + step))
            surface.updateTarget()
        }
    }
    function reveal(key) {
        const index = entries.findIndex(e => e.toolType === key)
        if (index < 0) return
        const rect = cell(index)
        scroll.contentY = Math.max(0, Math.min(Math.max(0, scroll.contentHeight - scroll.height),
            rect.y < scroll.contentY ? rect.y : rect.y + rect.height > scroll.contentY + scroll.height
                ? rect.y + rect.height - scroll.height : scroll.contentY))
        surface.revealInSurface(tiles, rect.y, rect.height)
    }
    function focusEntry(index) {
        const tile = tileRepeater.itemAt(index)
        if (tile) tile.forceActiveFocus(Qt.TabFocusReason)
        return !!tile
    }
    onEntriesChanged: Qt.callLater(() => {
        if (surface.selectedGroup === group) reveal(surface.selectedKey)
    })
    Timer { interval: 30; repeat: true; running: listing.receiving; onTriggered: listing.scrollAtPointer() }
    Flickable {
        id: scroll
        objectName: "toolbarList-" + listing.group
        anchors.fill: parent
        anchors.margins: 10
        clip: true
        contentWidth: width
        contentHeight: tiles.height
        boundsBehavior: Flickable.StopAtBounds
        interactive: !listing.surface.dragging
        Basic.ScrollBar.vertical: Components.AppScrollBar {}
        Item {
            id: tiles
            width: Math.max(1, scroll.width - 8)
            height: listing.group === "more" ? Math.max(listing.tileHeight, Math.ceil(listing.entries.length / 3) * (listing.tileHeight + listing.gap) - listing.gap)
                : listing.tileHeight * 2 + listing.gap
            Repeater {
                id: tileRepeater
                model: listing.entries
                delegate: ToolbarEditorTile {
                    id: tile
                    required property int index
                    required property var modelData
                    readonly property rect cell: listing.cell(index)
                    objectName: "toolbarTile-" + listing.group + "-" + modelData.toolType
                    entry: modelData
                    x: cell.x; y: cell.y; width: cell.width; height: cell.height
                    selected: listing.surface.selectedGroup === listing.group && listing.surface.selectedKey === modelData.toolType
                    hovered: pointer.containsMouse
                    opacity: listing.surface.dragging && listing.surface.dragKey === modelData.toolType && listing.surface.dragGroup === listing.group ? 0.3 : 1
                    Accessible.role: Accessible.Button
                    Accessible.name: modelData.label
                    Accessible.description: qsTrId("toolbar.selectHint")
                    Accessible.onPressAction: listing.surface.select(modelData.toolType, listing.group)
                    activeFocusOnTab: true
                    onActiveFocusChanged: if (activeFocus) {
                        listing.surface.select(modelData.toolType, listing.group, false)
                        listing.reveal(modelData.toolType)
                    }
                    Keys.onSpacePressed: listing.surface.focusActions()
                    Keys.onReturnPressed: listing.surface.focusActions()
                    Keys.onEnterPressed: listing.surface.focusActions()
                    // macOS may restrict the default Tab chain to text controls.
                    // The editor still provides an explicit local keyboard path.
                    Keys.onTabPressed: {
                        if (!listing.focusEntry(index + 1)) listing.surface.focusAfterGroup(listing.group)
                    }
                    Keys.onBacktabPressed: {
                        if (!listing.focusEntry(index - 1)) listing.surface.focusBeforeGroup(listing.group)
                    }
                    MouseArea {
                        id: pointer
                        objectName: "toolbarDrag-" + listing.group + "-" + tile.modelData.toolType
                        anchors.fill: parent
                        hoverEnabled: true
                        preventStealing: true
                        cursorShape: listing.surface.dragging ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                        onPressed: mouse => {
                            const p = mapToItem(listing.surface, mouse.x, mouse.y)
                            listing.surface.press(tile.modelData, listing.group, p.x, p.y, tile.width, tile.height)
                        }
                        onPositionChanged: mouse => {
                            if (!pressed) return
                            const p = mapToItem(listing.surface, mouse.x, mouse.y)
                            listing.surface.movePointer(p.x, p.y)
                        }
                        onReleased: listing.surface.releasePointer()
                        onCanceled: listing.surface.cancelDrag()
                    }
                    Components.AppToolTip {
                        visible: (pointer.containsMouse || tile.activeFocus) && !listing.surface.dragging
                        text: tile.modelData.label + (tile.modelData.available === false ? " · " + qsTrId("toolbar.unavailable") : "")
                    }
                }
            }
            Repeater {
                model: listing.group === "left" ? listing.fixedEntries : []
                delegate: ToolbarEditorTile {
                    required property int index
                    required property var modelData
                    readonly property rect cell: listing.cell(index - listing.fixedEntries.length)
                    x: cell.x; y: cell.y; width: cell.width; height: cell.height
                    entry: modelData; fixed: true
                }
            }
            ToolbarEditorTile {
                visible: listing.group === "common"
                readonly property rect cell: listing.cell(listing.entries.length)
                x: cell.x; y: cell.y; width: cell.width; height: cell.height
                entry: ({iconName: "more", label: qsTrId("tools.short.more")})
                fixed: true
            }
            Text {
                visible: listing.entries.length === 0
                x: 4; y: 20; width: parent.width - 8
                text: qsTrId("toolbar.empty")
                horizontalAlignment: Text.AlignHCenter
                color: Theme.textMuted; wrapMode: Text.Wrap; font.pixelSize: 12
            }
            Rectangle {
                objectName: "toolbarInsertion-" + listing.group
                visible: listing.receiving
                readonly property int insertion: listing.surface.targetIndex
                readonly property rect cell: listing.entries.length ? listing.cell(Math.min(Math.max(0, insertion), listing.entries.length - 1)) : Qt.rect(0, 0, 0, listing.tileHeight)
                x: insertion < listing.entries.length ? Math.max(0, cell.x - 4) : Math.min(tiles.width - 3, cell.x + cell.width + 2)
                y: cell.y
                width: 3; height: listing.tileHeight; radius: 1.5
                color: listing.permitted ? Theme.selectionBorder : Theme.dangerColor
            }
        }
    }
}
