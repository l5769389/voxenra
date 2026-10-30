pragma ComponentBehavior: Bound
import QtQuick

Item {
    id: root
    required property var controller
    required property var toolController
    required property var tabController
    property bool allowed: false
    property bool controlFocused: false
    property bool cprPanelFocused: false
    readonly property var cpr: tabController?.cprController ?? null
    Repeater {
        model: root.controller?.bindings ?? []
        delegate: Item {
            id: bindingItem
            required property var modelData
            Shortcut {
                objectName: "readingShortcut-" + bindingItem.modelData.action
                sequence: bindingItem.modelData.sequence
                context: Qt.WindowShortcut
                autoRepeat: false
                enabled: root.allowed && bindingItem.modelData.sequence.length > 0
                    && !root.controller?.recordingAction
                    && (!root.controlFocused || ["cpr-new", "cpr-edit"].includes(bindingItem.modelData.action))
                onActivated: root.controller.activate(bindingItem.modelData.action, root.toolController, root.tabController)
            }
        }
    }
    // A panel button must not strand CPR commands in the viewport's Keys handler.
    // Keep ordinary image keys there, and leave text fields/popups to their owner.
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
                enabled: root.allowed && root.cprPanelFocused && !!root.cpr
                    && (command.modelData.action === "finish" ? root.cpr.canFinishEditing
                        : command.modelData.action === "cancel" ? root.cpr.canCancelPath
                        : root.cpr.canDeletePoint)
                onActivated: {
                    if (command.modelData.action === "finish") root.cpr.finishEditing()
                    else if (command.modelData.action === "cancel") root.cpr.cancel_operation()
                    else root.cpr.deleteSelectedPoint()
                }
            }
        }
    }
}
