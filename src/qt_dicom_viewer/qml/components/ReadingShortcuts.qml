pragma ComponentBehavior: Bound
import QtQuick

Item {
    id: root
    required property var controller
    required property var toolController
    required property var tabController
    property bool allowed: false
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
                onActivated: root.controller.activate(bindingItem.modelData.action, root.toolController, root.tabController)
            }
        }
    }
}
