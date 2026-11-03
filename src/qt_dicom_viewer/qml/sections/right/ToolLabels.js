.pragma library

// The CT window in fusion uses the general window binding; translated names
// such as PET intensity or display mapping need not match the setting's label.
function shortcutAction(tool, playbackTool) {
    if (tool === playbackTool) return "play"
    if (tool === "ct-window") return "window"
    return ["window", "scroll", "zoom", "pan", "measure", "pseudocolor", "mpr-layout"].includes(tool) ? tool : ""
}

// Explain the gesture or its effect where the tool name alone is insufficient.
function explanation(tool) {
    const ids = {scroll: "hint.scroll", zoom: "hint.zoom", pan: "hint.pan",
                 measure: "hint.measure", pseudocolor: "hint.palette", "cpr-path": "hint.cpr"}
    return ids[tool] ? qsTrId(ids[tool]) : ""
}

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
