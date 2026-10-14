.pragma library

// Name the window entry for the editor it actually opens in this viewport.
function label(tool, editor, short) {
    if (tool.toolType !== "window")
        return short ? (tool.shortLabel ?? tool.label) : tool.label
    if (editor === "pet-range")
        return qsTrId(short ? "tools.short.pet-window" : "text.0279")
    if (editor === "palette" || editor === "scalar-range")
        return qsTrId(short ? "tools.short.mapping" : "mapping.title")
    return qsTrId(short ? "tools.short.window" : "text.0285")
}
