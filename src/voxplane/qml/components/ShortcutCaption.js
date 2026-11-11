.pragma library

function hint(action, bindings, menuSequences) {
    if (!action) return ""
    const binding = bindings.find(item => item.action === action)
    // A scoped binding wins over a general tool in ReadingShortcuts.qml.
    if (binding && !binding.menu && menuSequences?.includes(binding.sequence))
        return ""
    return binding?.display ?? ""
}
