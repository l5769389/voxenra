pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import "PopupShortcuts.js" as PopupShortcuts

Item {
    id: root
    required property var controller
    required property var toolController
    required property var tabController
    property var viewportController: null
    property var ownerPopup: null
    readonly property bool foreground: allowed && (!ownerPopup || !PopupShortcuts.blocked(
        Window.window, controller?.focusWindow, Basic.Overlay.overlay, ownerPopup))
    property bool menuOnly: false
    required property string activeMenu
    property bool allowed: false
    property bool controlFocused: false
    property bool cprPanelFocused: false
    property var listPanel: null
    readonly property int listCount: listPanel?.shortcutCount ?? 0
    function offers(binding) {
        // An expanded direct tool can show a reset footer with its submenu closed.
        if (binding.menu && !toolController?.activePanel && binding.action !== "view-reset") return false
        if (binding.action === "view-reset" && activeMenu === "mpr-layout") return !!tabController?.mprCompare && tabController.ready
        if (binding.action === "view-reset" && activeMenu === "registration") return !!tabController?.ready
        return binding.listIndex < 0 || binding.listIndex < listCount
    }
    signal primaryToolRequested(string tool)
    readonly property var cpr: tabController?.cprController ?? null
    readonly property bool cprPathActive: activeMenu === "cpr-path" && !!cpr
    readonly property bool measurementDraft: !!viewportController?.measurementController?.activeTransaction?.measurementId
    function canRunDrawingCommand(action) {
        if (cprPathActive) {
            if (action === "delete") return cprPanelFocused && cpr.canDeleteSelection
            if (cprPanelFocused || !menuOnly)
                return action === "finish" ? cpr.canFinishEditing : cpr.canCancelPath
        }
        return !menuOnly && action !== "delete" && measurementDraft
    }
    function runDrawingCommand(action) {
        if (cprPathActive) {
            if (action === "finish") cpr.finishEditing()
            else if (action === "cancel") cpr.cancel_operation()
            else cpr.deleteSelection()
        } else if (action === "finish") viewportController.finishMeasurement()
        else if (action === "cancel") viewportController.cancelMeasurement()
    }
    readonly property var menuSequences: activeMenu ? (controller?.bindings ?? [])
        .filter(binding => binding.menus.includes(activeMenu) && offers(binding) && binding.sequence)
        .map(binding => binding.sequence) : []
    Repeater {
        model: (root.controller?.bindings ?? []).filter(binding => !binding.viewType)
        delegate: Item {
            id: bindingItem
            required property var modelData
            Shortcut {
                objectName: "readingShortcut-" + bindingItem.modelData.action
                sequence: bindingItem.modelData.sequence
                context: Qt.WindowShortcut
                autoRepeat: false
                enabled: root.foreground && bindingItem.modelData.sequence.length > 0
                    && !root.controller?.recordingAction
                    && !(root.controlFocused && bindingItem.modelData.sequence === "Space")
                    && (bindingItem.modelData.menu
                        ? bindingItem.modelData.menus.includes(root.activeMenu) && root.offers(bindingItem.modelData)
                        : !root.menuOnly
                            && !root.menuSequences.includes(bindingItem.modelData.sequence))
                onActivated: {
                    const binding = bindingItem.modelData
                    if (binding.listIndex >= 0) {
                        if (!root.tabController?.playing && root.controller.pointerIdle())
                            root.listPanel.selectShortcutIndex(binding.listIndex)
                    } else if (!binding.menu && !["play", "reset"].includes(binding.action)) {
                        if (root.tabController?.playing || root.tabController?.activeViewport?.editBusy) return
                        const tool = root.controller.primaryToolFor(binding.action, root.toolController)
                        if (tool) root.primaryToolRequested(tool)
                    } else {
                        root.controller.activate(binding.action, root.toolController, root.tabController, root.activeMenu)
                    }
                }
            }
        }
    }
    // A tab or sidebar button must not strand an active drawing transaction.
    // The window supplies only its active viewport and gates text/popup focus;
    // Shortcut consumes the command before the viewport's local Keys handler.
    Repeater {
        model: [
            {key: "Return", action: "finish"}, {key: "Enter", action: "finish"},
            {key: "Escape", action: "cancel"},
            {key: "Delete", action: "delete"}, {key: "Backspace", action: "delete"}
        ]
        delegate: Item {
            id: command
            required property var modelData
            Shortcut {
                sequence: command.modelData.key
                context: Qt.WindowShortcut
                autoRepeat: false
                enabled: root.foreground && root.canRunDrawingCommand(command.modelData.action)
                onActivated: root.runDrawingCommand(command.modelData.action)
            }
        }
    }
}
