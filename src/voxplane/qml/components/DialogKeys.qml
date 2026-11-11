pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Templates as T

QtObject {
    id: keys
    required property T.Popup popup
    readonly property PopupScope shortcutScope: PopupScope { popup: keys.popup }
    property T.AbstractButton defaultButton: null
    property T.AbstractButton escapeButton: null
    property bool closeOnEnter: false
    readonly property Binding enterHint: Binding {
        target: keys.defaultButton instanceof AppButton ? keys.defaultButton : null
        property: "dialogKeyHint"
        value: keys.defaultButton === keys.escapeButton ? "Enter / Esc" : "Enter"
        when: target !== null
    }
    readonly property Binding escapeHint: Binding {
        target: keys.escapeButton instanceof AppButton && keys.escapeButton !== keys.defaultButton ? keys.escapeButton : null
        property: "dialogKeyHint"
        value: "Esc"
        when: target !== null
    }
    // The content, header and footer share this visual parent, also in Popup.Window.
    // Unhandled keys bubble here after the focused editor or child popup has had its turn.
    readonly property Connections keyHandler: Connections {
        target: keys.popup?.contentItem?.parent?.Keys ?? null
        function onPressed(event) { keys.handleKey(event) }
    }
    function handleKey(event) {
        if (!popup.opened || !popup.activeFocus || (event.modifiers & ~Qt.KeypadModifier))
            return
        const enter = event.key === Qt.Key_Return || event.key === Qt.Key_Enter
        if (!enter && (event.key !== Qt.Key_Escape || !escapeButton))
            return
        event.accepted = true
        if (event.isAutoRepeat)
            return
        const focusItem = popup.contentItem.Window.window?.activeFocusItem
        if (focusItem?.inputMethodComposing || (enter && focusItem?.acceptableInput === false))
            return
        // Tab + Enter activates a deliberately focused button, including Cancel.
        const button = enter ? (focusItem instanceof T.Button && focusItem.visualFocus
            ? focusItem : defaultButton) : escapeButton
        if (button?.visible && button.enabled)
            button.click()
        else if (enter && !button && closeOnEnter)
            popup.close()
    }
}
