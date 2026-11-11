pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Templates as T
import "PopupShortcuts.js" as PopupShortcuts

// A native popup can stay visible while focus returns to its owner. Register a
// nonvisual marker with that owner's reading window for the popup's lifetime.
Item {
    required property T.Popup popup
    readonly property var ownerWindow: popup?.parent?.Window.window
    parent: popup?.visible && popup.popupType !== T.Popup.Item
        ? PopupShortcuts.registry(ownerWindow) : null
    visible: false
}
