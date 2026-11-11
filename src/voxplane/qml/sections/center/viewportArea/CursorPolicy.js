.pragma library

// Match interaction dispatch: region handles first, then crosshair handles,
// then the current tool. A drag latches this result until mouse release.
function resolve(interaction, region, crosshair, measurement) {
    // Display rotation takes precedence over MPR crosshair handles.
    if (interaction === "rotate") return "rotate"
    if (interaction === "mpr:voi" || interaction === "mpr:segmentation")
        return region || interaction.slice(4)
    if (interaction === "annotate:text") return "annotate-text"
    if (crosshair === "center") return "crosshair-move"
    if (crosshair === "horizontalLine" || crosshair === "verticalLine")
        return "crosshair-rotate"
    const drawing = {"measure:length":"measure-line", "measure:angle":"measure-angle",
        "measure:rect":"measure-rect", "measure:ellipse":"measure-ellipse",
        "measure:freehand":"measure-freehand",
        "measure:curve":"measure-curve",
        "annotate:arrow":"annotate-arrow", "service:mtf":"mtf", "service:fwhm":"measure-rect", "service:qa":"qa"}
    if (interaction === "service:qa") return measurement || "window"
    if (drawing[interaction]) return measurement || drawing[interaction]
    return ({window:"window", scroll:"scroll", pan:"pan", zoom:"zoom",
        "mpr:rotate3d":"rotate-3d", "volume:rotate":"rotate-3d", "volume:crop":"volume-crop"})[interaction] || "window"
}

// Primary drags use the selected tool. Secondary buttons can temporarily override it.
function dragBinding(buttons, preferences) {
    if (buttons & 1) return "selected"
    if (buttons & 2) return preferences?.rightButton ?? "zoom"
    if (buttons & 4) return preferences?.middleButton ?? "selected"
    return "none"
}

function resolveDrag(hover, buttons, registration, preferences) {
    if (!(buttons & 1) && (buttons & 2) && registration) return "rotate-3d"
    const binding = dragBinding(buttons, preferences)
    return binding === "selected" ? hover : binding === "none" ? "" : binding
}
