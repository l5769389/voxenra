pragma ComponentBehavior: Bound
import QtQuick

Item {
    id: root
    required property var controller
    required property var panelController
    required property string seriesUid
    property bool allowed: false
    property bool controlFocused: false
    property var suppressedSequences: []
    signal viewRequested(string viewType)

    Repeater {
        model: (root.controller?.bindings ?? []).filter(binding => !!binding.viewType)
        delegate: Item {
            id: bindingItem
            required property var modelData
            Shortcut {
                objectName: "seriesViewShortcut-" + bindingItem.modelData.viewType
                sequence: bindingItem.modelData.sequence
                context: Qt.WindowShortcut
                autoRepeat: false
                enabled: root.allowed && !!root.seriesUid && !!bindingItem.modelData.sequence
                    && !root.controller?.recordingAction
                    && !(root.controlFocused && bindingItem.modelData.sequence === "Space")
                    && !root.suppressedSequences.includes(bindingItem.modelData.sequence)
                onActivated: {
                    if (root.controller.pointerIdle()
                            && root.panelController.canOpenSeriesView(root.seriesUid, bindingItem.modelData.viewType))
                        root.viewRequested(bindingItem.modelData.viewType)
                }
            }
        }
    }
}
