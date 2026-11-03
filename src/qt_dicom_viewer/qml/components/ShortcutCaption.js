.pragma library

function hint(action, bindings, activeMenu, listCount) {
    if (!action) return ""
    const binding = bindings.find(item => item.action === action)
    // A scoped binding wins over a general tool in ReadingShortcuts.qml.
    if (binding && !binding.menu && activeMenu && bindings.some(item =>
        item.menu && (item.listIndex < 0 || item.listIndex < listCount) && item.menus.includes(activeMenu) && item.sequence === binding.sequence))
        return ""
    return binding?.display ?? ""
}
