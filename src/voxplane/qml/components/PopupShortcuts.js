.pragma library

function registry(window) {
    for (let current = window; current; current = current.transientParent) {
        if (current.shortcutPopupRegistry)
            return current.shortcutPopupRegistry
    }
    return null
}

// A transient can have keyboard focus while Qt still calls its owner active.
// Preserve shortcuts for native child rendering surfaces and passive tooltips.
function blocked(window, focusWindow, overlay, ownerPopup) {
    if (registry(window)?.children.some(marker => marker.ownerWindow === window && marker.popup !== ownerPopup))
        return true
    if (focusWindow && focusWindow !== window && focusWindow.visible) {
        const type = focusWindow.flags & Qt.WindowType_Mask
        if (type === Qt.Popup || type === Qt.Dialog || type === Qt.Sheet
                || focusWindow.modality !== Qt.NonModal)
            return true
    }
    const items = overlay?.children ?? []
    for (let index = items.length - 1; index >= 0; --index) {
        const item = items[index]
        if (!item.visible || item.contentItem?.passiveToolTip)
            continue
        return item !== ownerPopup?.contentItem?.parent
    }
    return false
}
