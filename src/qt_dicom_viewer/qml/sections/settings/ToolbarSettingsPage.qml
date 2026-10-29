pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import QtQuick.Controls.Basic as Basic
import "../../components" as Components
import "../../theme"

Item {
    id: page
    objectName: "toolbarSettingsPage"
    required property var settingsController
    property string initialProfile: ""
    property bool detailsExpanded: false
    property var editor: settingsController.createToolbarEditor(page)
    readonly property string currentScope: editor.scope
    readonly property string currentProfile: editor.selectedProfile
    property string selectedKey: ""
    property string selectedGroup: ""
    readonly property var selectedEntries: selectedGroup === "left" ? editor.leftViews : selectedGroup === "common" ? editor.commonTools : editor.moreTools
    readonly property int selectedIndex: selectedEntries.findIndex(e => e.toolType === selectedKey)
    readonly property var selectedEntry: selectedIndex >= 0 ? selectedEntries[selectedIndex] : null
    property var dragEntry: null
    property string dragKey: ""
    property string dragGroup: ""
    property bool dragging: false
    property real pressX: 0
    property real pressY: 0
    property real pointerX: 0
    property real pointerY: 0
    property real dragWidth: 80
    property real dragHeight: 76
    property string targetGroup: ""
    property int targetIndex: -1
    readonly property bool stacked: page.width < 640
    readonly property var fixedSources: [
        {iconName: "nav-load-file", label: qsTrId("sidebar.short.images"), show: typeof appController === "undefined" || appController.pacsController.localEnabled},
        {iconName: "nav-pacs", label: "PACS", show: typeof appController === "undefined" || appController.pacsController.pacsEnabled}
    ].filter(e => e.show)
    Component.onCompleted: if (initialProfile) editor.selectProfile(initialProfile)
    onCurrentScopeChanged: resetInteraction()
    onCurrentProfileChanged: resetInteraction()
    onVisibleChanged: if (!visible) cancelDrag()
    onWidthChanged: cancelDrag()
    onHeightChanged: cancelDrag()
    Connections {
        target: page.Window.window
        function onActiveChanged() { if (!page.Window.window.active) page.cancelDrag() }
    }
    function resetInteraction() { cancelDrag(); selectedKey = ""; selectedGroup = "" }
    function select(key, group, focus = true) {
        selectedKey = key; selectedGroup = group
        if (focus) forceActiveFocus()
    }
    function cancelDrag() {
        dragging = false; dragEntry = null; dragKey = ""; dragGroup = ""
        targetGroup = ""; targetIndex = -1
    }
    function press(entry, group, x, y, width, height) {
        select(entry.toolType, group)
        dragEntry = entry; dragKey = entry.toolType; dragGroup = group
        pressX = x; pressY = y; pointerX = x; pointerY = y
        dragWidth = width; dragHeight = height
    }
    function movePointer(x, y) {
        if (!dragEntry) return
        pointerX = x; pointerY = y
        if (!dragging && Math.hypot(x - pressX, y - pressY) < 8) return
        dragging = true
        updateTarget()
    }
    function updateTarget() {
        targetGroup = ""; targetIndex = -1
        const p = mapToItem(boardsScroll, pointerX, pointerY)
        if (p.x < 0 || p.x > boardsScroll.width || p.y < 0 || p.y > boardsScroll.height) return
        for (const board of [primaryBoard, moreBoard]) {
            const index = board.locate(pointerX, pointerY)
            if (index >= 0) { targetGroup = board.group; targetIndex = index; break }
        }
    }
    function revealInSurface(item, y, height) {
        if (!stacked) return
        const top = item.mapToItem(boardsScroll.contentItem, 0, y).y
        boardsScroll.contentY = Math.max(0, Math.min(Math.max(0, boardsScroll.contentHeight - boardsScroll.height),
            top < boardsScroll.contentY ? top : top + height > boardsScroll.contentY + boardsScroll.height
                ? top + height - boardsScroll.height : boardsScroll.contentY))
    }
    Timer {
        interval: 30; repeat: true; running: page.dragging && page.stacked
        onTriggered: {
            const p = page.mapToItem(boardsScroll, page.pointerX, page.pointerY)
            if (p.x < 0 || p.x > boardsScroll.width || p.y < 0 || p.y > boardsScroll.height) return
            const step = p.y < 32 ? -12 : p.y > boardsScroll.height - 32 ? 12 : 0
            if (step) {
                boardsScroll.contentY = Math.max(0, Math.min(Math.max(0, boardsScroll.contentHeight - boardsScroll.height), boardsScroll.contentY + step))
                page.updateTarget()
            }
        }
    }
    function releasePointer() {
        const key = dragKey, source = dragGroup, destination = targetGroup, index = targetIndex
        const commit = dragging && index >= 0
        // Clear the pointer session before changed signals rebuild the source delegate.
        cancelDrag()
        if (commit && editor.placeEntry(key, source, destination, index)) select(key, destination)
    }
    function moveSelected(offset) {
        if (dragging || selectedIndex < 0) return
        const destination = selectedIndex + offset
        if (destination < 0 || destination >= selectedEntries.length) return
        const focusedAction = upAction.activeFocus ? upAction : downAction.activeFocus ? downAction : null
        if (selectedGroup === "left") editor.moveLeftView(selectedIndex, destination)
        else editor.moveTool(selectedGroup, selectedIndex, destination)
        if (focusedAction && focusedAction.enabled) focusedAction.forceActiveFocus()
        else if (focusedAction) focusActions()
        else forceActiveFocus()
    }
    function focusActions() {
        for (const button of [upAction, downAction, groupAction]) {
            if (button.visible && button.enabled) { button.forceActiveFocus(); break }
        }
    }
    function focusAfterGroup(group) {
        if (group === "common" && moreBoard.focusEntry(0)) return
        focusActions()
    }
    function focusBeforeGroup(group) {
        if (group === "more" && primaryBoard.focusEntry(primaryBoard.entries.length - 1)) return
        if (capabilityChooser.visible) capabilityChooser.forceActiveFocus()
        else if (detailsToggle.visible) detailsToggle.forceActiveFocus()
        else leftScopeButton.forceActiveFocus()
    }
    function transferSelected() {
        if (!selectedEntry || selectedGroup === "left" || dragging) return
        const destination = selectedGroup === "common" ? "more" : "common"
        if (editor.moveToGroup(selectedKey, destination)) selectedGroup = destination
        groupAction.forceActiveFocus()
        Qt.callLater(() => (selectedGroup === "more" ? moreBoard : primaryBoard).reveal(selectedKey))
    }
    Shortcut { sequence: "Escape"; enabled: page.visible && page.dragging; onActivated: page.cancelDrag() }
    Shortcut { sequence: "Alt+Left"; enabled: page.visible && !!page.selectedEntry; onActivated: page.moveSelected(-1) }
    Shortcut { sequence: "Alt+Right"; enabled: page.visible && !!page.selectedEntry; onActivated: page.moveSelected(1) }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 10
        Text { text: qsTrId("toolbar.title"); color: Theme.textPrimary; font.pixelSize: 18; font.bold: true }
        RowLayout {
            Layout.fillWidth: true; Layout.minimumWidth: 0
            Components.AppButton {
                id: leftScopeButton
                objectName: "toolbarScopeLeft"; text: qsTrId("toolbar.left"); iconName: "nav-view-2d"
                Layout.fillWidth: true
                Layout.preferredWidth: Math.ceil(implicitWidth) + 2
                Layout.maximumWidth: Layout.preferredWidth
                checked: page.editor.scope === "left"; checkable: true
                onClicked: page.editor.selectScope("left")
            }
            Components.AppButton {
                objectName: "toolbarScopeRight"; text: qsTrId("toolbar.right"); iconName: "measure"
                Layout.fillWidth: true
                Layout.preferredWidth: Math.ceil(implicitWidth) + 2
                Layout.maximumWidth: Layout.preferredWidth
                checked: page.editor.scope === "right"; checkable: true
                onClicked: page.editor.selectScope("right")
            }
        }
        RowLayout {
            visible: page.editor.scope === "right"
            Layout.fillWidth: true
            Components.AppComboBox {
                id: profileChooser
                objectName: "toolbarProfile"
                Layout.fillWidth: true
                model: page.editor.viewCategories
                textRole: "label"; valueRole: "key"
                currentIndex: page.editor.viewCategories.findIndex(p => p.key === page.editor.selectedCategory)
                Accessible.name: qsTrId("toolbar.viewCategory")
                onActivated: index => page.editor.selectCategory(page.editor.viewCategories[index].key)
                KeyNavigation.tab: detailsToggle
            }
            Components.AppButton {
                id: detailsToggle
                objectName: "toolbarDetails"
                text: qsTrId("toolbar.details"); iconName: page.detailsExpanded ? "chevron-up" : "chevron-down"
                compact: true; checkable: true; checked: page.detailsExpanded
                onClicked: { page.cancelDrag(); page.detailsExpanded = !page.detailsExpanded }
                Keys.onTabPressed: {
                    if (page.detailsExpanded) (modeChooser.visible ? modeChooser : capabilityChooser).forceActiveFocus()
                    else if (!primaryBoard.focusEntry(0)) page.focusAfterGroup(primaryBoard.group)
                }
            }
        }
        Text {
            objectName: "toolbarProfileSummary"
            visible: page.editor.scope === "right"
            Layout.fillWidth: true
            text: page.editor.selectedProfileLabel
            color: Theme.textSecondary; font.pixelSize: 12; wrapMode: Text.Wrap
        }
        RowLayout {
            visible: page.editor.scope === "right" && page.detailsExpanded
            Layout.fillWidth: true; spacing: 12
            ColumnLayout {
                visible: page.editor.modes.length > 1
                Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 4
                Text { text: qsTrId("toolbar.mode"); color: Theme.textSecondary; font.pixelSize: 12 }
                Components.AppComboBox {
                    id: modeChooser
                    objectName: "toolbarMode"
                    Layout.fillWidth: true
                    model: page.editor.modes; textRole: "label"; valueRole: "key"
                    currentIndex: page.editor.modes.findIndex(p => p.key === page.editor.selectedMode)
                    Accessible.name: qsTrId("toolbar.mode")
                    onActivated: index => page.editor.selectMode(page.editor.modes[index].key)
                    KeyNavigation.tab: capabilityChooser
                    KeyNavigation.backtab: detailsToggle
                }
            }
            ColumnLayout {
                Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 4
                Text { text: qsTrId("toolbar.imageType"); color: Theme.textSecondary; font.pixelSize: 12 }
                Components.AppComboBox {
                    id: capabilityChooser
                    objectName: "toolbarCapability"
                    Layout.fillWidth: true
                    model: page.editor.capabilities; textRole: "label"; valueRole: "key"
                    currentIndex: page.editor.capabilities.findIndex(p => p.key === page.editor.selectedCapability)
                    Accessible.name: qsTrId("toolbar.imageType")
                    onActivated: index => page.editor.selectCapability(page.editor.capabilities[index].key)
                    Keys.onTabPressed: if (!primaryBoard.focusEntry(0)) page.focusAfterGroup(primaryBoard.group)
                    KeyNavigation.backtab: modeChooser.visible ? modeChooser : detailsToggle
                }
            }
        }
        Text {
            Layout.fillWidth: true
            text: page.editor.scope === "left" ? qsTrId("toolbar.fixed") : qsTrId("toolbar.hint")
            color: Theme.textSecondary; font.pixelSize: 12; wrapMode: Text.Wrap
        }
        Flickable {
            id: boardsScroll
            objectName: "toolbarBoardsScroll"
            Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 80
            clip: true
            contentWidth: width
            contentHeight: page.stacked ? boards.implicitHeight : height
            boundsBehavior: Flickable.StopAtBounds
            interactive: page.stacked && !page.dragging
            Basic.ScrollBar.vertical: Components.AppScrollBar {}
            GridLayout {
                id: boards
                width: boardsScroll.width - (page.stacked ? 10 : 0)
                height: page.stacked ? implicitHeight : boardsScroll.height
                columns: page.editor.scope === "right" && !page.stacked ? 2 : 1
                columnSpacing: 12; rowSpacing: 10
                ColumnLayout {
                    Layout.fillWidth: true; Layout.fillHeight: !page.stacked; Layout.preferredWidth: 1
                    Text {
                        text: page.editor.scope === "left" ? qsTrId("toolbar.left")
                            : qsTrId("toolbar.common") + " · " + page.editor.commonTools.length + "/7"
                        color: Theme.textPrimary; font.pixelSize: 13; font.bold: true
                    }
                    ToolbarOrderList {
                        id: primaryBoard
                        Layout.fillWidth: true; Layout.fillHeight: !page.stacked
                        Layout.preferredHeight: page.stacked ? naturalHeight : -1
                        surface: page
                        group: page.editor.scope === "left" ? "left" : "common"
                        entries: page.editor.scope === "left" ? page.editor.leftViews : page.editor.commonTools
                        fixedEntries: page.fixedSources
                    }
                }
                ColumnLayout {
                    visible: page.editor.scope === "right"
                    Layout.fillWidth: true; Layout.fillHeight: !page.stacked; Layout.preferredWidth: 1
                    Text { text: qsTrId("toolbar.more"); color: Theme.textPrimary; font.pixelSize: 13; font.bold: true }
                    ToolbarOrderList {
                        id: moreBoard
                        Layout.fillWidth: true; Layout.fillHeight: !page.stacked
                        Layout.preferredHeight: page.stacked ? naturalHeight : -1
                        surface: page; group: "more"; entries: page.editor.moreTools
                    }
                }
            }
        }
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: selectionActions.implicitHeight + 16
            color: Theme.panelBackground; radius: Theme.controlRadius
            ColumnLayout {
                id: selectionActions
                anchors.left: parent.left; anchors.right: parent.right; anchors.margins: 8; y: 8
                spacing: 6
                Text {
                    Layout.fillWidth: true
                    text: page.selectedEntry ? page.selectedEntry.label : qsTrId("toolbar.selectHint")
                    color: page.selectedEntry ? Theme.textPrimary : Theme.textMuted
                    textFormat: Text.PlainText; font.pixelSize: 12; elide: Text.ElideRight
                }
                RowLayout {
                    Layout.fillWidth: true
                    Components.AppButton {
                        id: upAction
                        objectName: "toolbarUp-" + page.selectedGroup + "-" + page.selectedKey
                        text: qsTrId("toolbar.up"); compact: true
                        enabled: page.selectedIndex > 0 && !page.dragging
                        Accessible.name: text + " · " + (page.selectedEntry?.label ?? "")
                        onClicked: page.moveSelected(-1)
                        KeyNavigation.tab: downAction.enabled ? downAction : groupAction.enabled && groupAction.visible ? groupAction : restoreAction
                    }
                    Components.AppButton {
                        id: downAction
                        objectName: "toolbarDown-" + page.selectedGroup + "-" + page.selectedKey
                        text: qsTrId("toolbar.down"); compact: true
                        enabled: page.selectedIndex >= 0 && page.selectedIndex < page.selectedEntries.length - 1 && !page.dragging
                        Accessible.name: text + " · " + (page.selectedEntry?.label ?? "")
                        onClicked: page.moveSelected(1)
                        KeyNavigation.tab: groupAction.enabled && groupAction.visible ? groupAction : restoreAction
                        KeyNavigation.backtab: upAction.enabled ? upAction : null
                    }
                    Components.AppButton {
                        id: groupAction
                        objectName: "toolbarGroup-" + page.selectedGroup + "-" + page.selectedKey
                        visible: page.editor.scope === "right"
                        text: page.selectedGroup === "common" ? qsTrId("toolbar.toMore") : qsTrId("toolbar.toCommon")
                        compact: true; enabled: !!page.selectedEntry && !page.dragging
                        onClicked: page.transferSelected()
                        KeyNavigation.tab: restoreAction
                        KeyNavigation.backtab: downAction.enabled ? downAction : upAction.enabled ? upAction : null
                    }
                    Item { Layout.fillWidth: true }
                }
            }
        }
        Text {
            Layout.fillWidth: true; visible: text.length > 0
            text: page.editor.message || page.settingsController.message
            wrapMode: Text.Wrap; color: Theme.dangerColor; font.pixelSize: 12
        }
        RowLayout {
            Layout.fillWidth: true
            Components.AppButton { id: restoreAction; objectName: "toolbarRestore"; text: qsTrId("toolbar.restore"); onClicked: { page.cancelDrag(); page.editor.restoreCurrentDefault() } }
            Item { Layout.fillWidth: true }
            Components.AppButton { objectName: "toolbarCancel"; text: qsTrId("toolbar.cancel"); enabled: page.editor.dirty; onClicked: { page.cancelDrag(); page.editor.cancel() } }
            Components.AppButton { objectName: "toolbarSave"; text: qsTrId("toolbar.save"); actionRole: "primary"; enabled: page.editor.dirty; onClicked: { page.cancelDrag(); page.editor.save() } }
        }
    }
    ToolbarEditorTile {
        objectName: "toolbarDragPreview"
        visible: page.dragging
        z: 100
        entry: page.dragEntry ?? ({iconName: "more", label: ""})
        x: page.pointerX - width / 2; y: page.pointerY - height / 2 - 10
        width: page.dragWidth; height: page.dragHeight
        selected: true; opacity: 0.94; rotation: -2
    }
}
