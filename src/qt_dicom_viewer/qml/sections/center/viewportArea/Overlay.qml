pragma ComponentBehavior: Bound
import QtQuick
import "../../../theme"

Item {
    id: root
    objectName: "viewportMetadataOverlay"
    required property var viewportController
    property bool hideSensitiveInfo: false
    property bool multiViewport: false
    property string viewMode: ""
    readonly property bool hasViewSelector: viewMode !== ""
    readonly property string modeLabel: ({stack: qsTrId("layout.originalSlices"), axial: qsTrId("layout.axialReconstruction"),
        coronal: qsTrId("layout.coronalReconstruction"), sagittal: qsTrId("layout.sagittalReconstruction")})[viewMode] ?? ""
    readonly property int textPixelSize: Math.max(10, Math.round((options.fontSize ?? 12) * fontScale))
    readonly property real textRowHeight: textPixelSize * (options.lineHeight ?? 1.2)
    readonly property real selectorWidth: Math.min(Math.ceil(modeMetrics.advanceWidth) + 30, Math.max(0, (width - 24) / 2))
    readonly property real selectorHeight: Math.max(24, modeSizing.implicitHeight + 6)
    readonly property bool inlineViewPosition: hasViewSelector && (options.topLeft ?? [])[0] === "viewPosition"
    readonly property rect positionRect: Qt.rect(modeRow.x + positionLabel.x, modeRow.y + positionLabel.y,
        positionLabel.width, positionLabel.height)
    readonly property string positionText: {
        const raw = value("viewPosition")
        if (!raw) return qsTrId("layout.orientationUnavailable")
        const planes = {Axial: qsTrId("layout.orientationAxial"), Coronal: qsTrId("layout.orientationCoronal"),
            Sagittal: qsTrId("layout.orientationSagittal"), Oblique: qsTrId("layout.orientationOblique")}
        // Read the actual frame geometry, not the selected reconstruction mode.
        // Preserve Oblique even in a reconstructed view.
        const text = viewMode === "stack" ? raw : raw.replace(/^(Axial|Coronal|Sagittal),?\s*/, "")
        return text.replace(/^(Axial|Coronal|Sagittal|Oblique)/, name => planes[name])
            .replace(", ", " · ").replace(/(\d)mm\b/g, "$1 mm")
    }
    TextMetrics { id: modeMetrics; font.pixelSize: root.textPixelSize; font.weight: Font.DemiBold; text: root.modeLabel }
    Text {
        id: modeSizing
        visible: false
        width: Math.max(1, root.selectorWidth - 30)
        text: root.modeLabel
        font.pixelSize: root.textPixelSize; font.weight: Font.DemiBold
        wrapMode: Text.Wrap
        maximumLineCount: 4
    }
    readonly property var overlay: viewportController ? viewportController.overlayInfo : ({})
    readonly property var cursorInfo: viewportController ? viewportController.cursorController.cursorInfo : ({})
    readonly property var options: viewportController?.settingsController.values.corners ?? ({})
    readonly property bool petWorkspace: !!overlay.viewRole
    readonly property real bottomTextHeight: Math.max(bottomLeft.visible ? bottomLeft.height : 0,
                                                     bottomRight.visible ? bottomRight.height : 0)
    readonly property real topLeftTextHeight: (topLeft.visible ? topLeft.height : 0) + (hasViewSelector ? modeRow.height : 0)
    readonly property real bottomLeftTextHeight: bottomLeft.visible ? bottomLeft.height : 0
    readonly property real fontScale: multiViewport || width < 640 || height < 480 ? 0.85 : 1
    readonly property color backgroundColor: viewportController?.canvasBackgroundColor ?? Theme.imageBlack
    readonly property bool lightBackground: backgroundColor.r * 0.299 + backgroundColor.g * 0.587 + backgroundColor.b * 0.114 > 0.6
    readonly property color textColor: options.colorMode === "custom" ? options.color : lightBackground ? Theme.overlayDarkText : Theme.overlayText
    visible: options.enabled !== false

    function value(key) {
        const text = String(overlay[key] ?? "").trim()
        return petWorkspace && (text === "--" || text === "—") ? "" : text
    }
    function label(key, title, unit = "") { const text = value(key); return text ? title + text + unit : "" }
    function planePosition() {
        return value("viewPosition")
            .replace(/^(Axial|Coronal|Sagittal|Oblique)/, name => name.toUpperCase())
            .replace(", ", " · ").replace(/(\d)mm\b/g, "$1 mm")
    }
    // Corner field labels stay English regardless of UI or external language packs.
    // Patient and series values are source metadata and are never translated.
    function field(key) {
        switch (key) {
        case "viewPosition": {
            const role = value("viewRole")
            if (role === "fusion")
                return ["FUSION", planePosition()].filter(Boolean).join(" · ")
            if (role === "mip") return value("viewType")
            if (role) return [role === "ct" ? "CT" : "PET", planePosition()].filter(Boolean).join(" · ")
            return value("viewPosition") || value("viewType").toUpperCase()
        }
        case "slice": {
            if (value("viewRole") === "mip") return overlay.registrationPreview ? "Reduced-resolution projection" : "Whole-volume projection"
            if (petWorkspace) return value("sliceIndex") ? "Reformatted slice: " + value("sliceIndex") + " / " + value("sliceCount")
                + (overlay.compactOverlay || !value("sourceSliceCount") ? "" : "\nSource images: " + value("sourceSliceCount")
                    + " (" + (value("viewRole") === "ct" ? "CT" : "PET") + ")") : ""
            return label("sliceIndex", "Slice: ") + (value("sliceCount") ? " / " + value("sliceCount") : "")
        }
        case "patientName": return hideSensitiveInfo ? "" : label("patientName", "Patient: ")
        case "patientId": return hideSensitiveInfo || overlay.suppressIdentifiers ? "" : label("patientId", "ID: ")
        case "seriesDescription": return value("viewRole") === "fusion"
            ? (hideSensitiveInfo ? "" : [label("ctSeries", "CT series: "), label("petSeries", "PET series: ")].filter(Boolean).join("\n"))
            : value(key)
        case "exposure": return value("modality") === "MR" ? value("mrParameters") : value("modality") === "PT"
            ? [label("radiopharmaceutical", "Tracer: "),
               petWorkspace ? [label("correctedImage", "Corrections: "), label("decayCorrection", "Decay correction: ")].filter(Boolean).join("\n")
                   : "Correction: " + value("correctedImage") + " · " + value("decayCorrection")].filter(Boolean).join("\n")
            : [label("kvp", "kV: "), label("tubeCurrentMa", "mA: ")].filter(Boolean).join("   ")
        case "sliceThickness": return label("sliceThickness", petWorkspace ? "Source thickness: " : "Thickness: ", " mm")
        case "window": {
            if (overlay.derivedMapping) {
                const mode = overlay.mappingMode === "custom" ? "Custom range" : "Source mapping"
                return value("mappingLower") && value("mappingUpper")
                    ? mode + ": " + value("mappingLower") + " – " + value("mappingUpper") + " " + value("pixelUnit")
                    : mode
            }
            if (value("modality") === "PT") {
                const lines = [label("petDisplayUpper", petWorkspace ? "Display range: 0 – " : "PET Range: 0 – ", " " + value("pixelUnit"))]
                if (!overlay.compactOverlay)
                    lines.push(label("petUnits", petWorkspace ? "DICOM units: " : "Source Units: "),
                               label("suvType", petWorkspace ? "SUV type: " : "SUV Type: "))
                if (value("viewRole") === "fusion")
                    lines.push([label("ctWindowCenter", "CT WL: "), label("ctWindowWidth", "WW: ")].filter(Boolean).join("  "))
                return lines.filter(Boolean).join("\n")
            }
            return [label("windowCenter", "WL: "), label("windowWidth", "WW: ")].filter(Boolean).join("   ")
        }
        case "cursor": if (overlay.registrationPreview) return "Preview MIP · Release to refine"
            return (petWorkspace ? "Col: " : "X: ") + (cursorInfo.x ?? "--") + (petWorkspace ? "   Row: " : "   Y: ") + (cursorInfo.y ?? "--")
            + "\n" + (value("viewRole") === "mip" ? "PET max" : cursorInfo.label ?? "Value") + ": " + (cursorInfo.value ?? "--") + " " + (cursorInfo.unit ?? "")
            + (viewportController?.secondaryCursorText ? "\n" + viewportController.secondaryCursorText : "")
        case "zoom": return label("zoom", "Zoom: ")
        case "matrix": return value("rows") && value("columns") ? (petWorkspace ? "Matrix: " : "") + value("rows") + " × " + value("columns") : ""
        case "spacing": return value("pixelSpacingX") && value("pixelSpacingY") ? (petWorkspace
            ? "Pixel spacing: " + value("pixelSpacingY") + " × " + value("pixelSpacingX")
            : value("pixelSpacingX") + " × " + value("pixelSpacingY")) + " mm" : ""
        default: return value(key)
        }
    }
    function lines(corner) {
        const compactFields = ["viewPosition", "slice", "patientName", "patientId", "window", "transform", "cursor"]
        return (options[corner] ?? []).filter((key, index) => !(corner === "topLeft" && inlineViewPosition && index === 0))
            .filter(key => !overlay.compactOverlay || compactFields.includes(key))
            .map(key => field(key)).filter(Boolean).join("\n")
    }
    component CornerText: Item {
        id: corner
        property string text: ""
        property int horizontalAlignment: Text.AlignLeft
        property real reservedHeight: 0
        readonly property real pixelSize: root.textPixelSize
        readonly property real rowHeight: pixelSize * (root.options.lineHeight ?? 1.2)
        readonly property int rowLimit: Math.max(0, Math.min(root.overlay.compactOverlay ? 4 : 12,
            Math.floor((root.height / 2 - 12 - reservedHeight) / rowHeight)))
        readonly property var rows: text.split("\n").filter(Boolean).slice(0, rowLimit)
        width: Math.max(0, (root.width - 24) / 2)
        height: rows.length * rowHeight
        clip: true
        visible: root.viewportController !== null && text.length > 0
        Column {
            width: parent.width
            Repeater {
                model: corner.rows.length
                Text {
                    required property int index
                    objectName: "cornerInformationLine"
                    width: corner.width
                    height: corner.rowHeight
                    text: corner.rows[index] ?? ""
                    color: root.textColor
                    font.pixelSize: corner.pixelSize
                    font.weight: root.overlay.compactOverlay ? Font.Normal : Font.DemiBold
                    horizontalAlignment: corner.horizontalAlignment
                    verticalAlignment: Text.AlignVCenter
                    style: Text.Outline
                    styleColor: root.lightBackground ? Theme.overlayLightOutline : Theme.overlayOutline
                    textFormat: Text.PlainText
                    wrapMode: Text.NoWrap
                    maximumLineCount: 1
                    elide: Text.ElideRight
                }
            }
        }
    }
    // The live dropdown is a sibling of the exported viewport. Keep plain text here
    // so a captured image retains the view mode and physical position, without UI.
    Item {
        id: modeRow
        objectName: "twoDModeInformation"
        x: 2; y: 2
        width: topLeft.width
        readonly property bool positionOnNextLine: root.inlineViewPosition
            && positionLabel.implicitWidth > Math.max(0, width - root.selectorWidth - 4)
        height: root.selectorHeight + (positionOnNextLine ? root.textRowHeight : 0)
        visible: root.hasViewSelector
        Text {
            objectName: "twoDModeLabel"
            width: Math.max(0, root.selectorWidth - 30); height: root.selectorHeight
            text: root.modeLabel
            font.pixelSize: root.textPixelSize; font.weight: Font.DemiBold
            verticalAlignment: Text.AlignVCenter
            color: root.textColor
            style: Text.Outline
            styleColor: root.lightBackground ? Theme.overlayLightOutline : Theme.overlayOutline
            elide: Text.ElideRight
            wrapMode: Text.Wrap
            maximumLineCount: 4
        }
        Text {
            id: positionLabel
            objectName: "twoDModePosition"
            x: modeRow.positionOnNextLine ? 0 : root.selectorWidth + 4
            y: modeRow.positionOnNextLine ? root.selectorHeight : 0
            width: Math.max(0, parent.width - x)
            height: modeRow.positionOnNextLine ? root.textRowHeight : root.selectorHeight
            visible: root.inlineViewPosition
            text: root.inlineViewPosition ? root.positionText : ""
            font.pixelSize: root.textPixelSize; font.weight: Font.Normal
            verticalAlignment: Text.AlignVCenter
            color: root.textColor
            style: Text.Outline
            styleColor: root.lightBackground ? Theme.overlayLightOutline : Theme.overlayOutline
            textFormat: Text.PlainText
            elide: Text.ElideRight
        }
    }
    CornerText {
        id: topLeft
        objectName: "overlay-topLeft"
        anchors.left: parent.left; anchors.top: parent.top
        anchors.leftMargin: 2
        anchors.topMargin: 2 + reservedHeight
        reservedHeight: root.hasViewSelector ? modeRow.height : 0
        text: root.lines("topLeft")
    }
    CornerText { objectName: "overlay-topRight"; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 2; horizontalAlignment: Text.AlignRight; text: root.lines("topRight") }
    CornerText { id: bottomLeft; objectName: "overlay-bottomLeft"; anchors.left: parent.left; anchors.bottom: parent.bottom; anchors.margins: 2; text: root.lines("bottomLeft") }
    CornerText { id: bottomRight; objectName: "overlay-bottomRight"; anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 2; horizontalAlignment: Text.AlignRight; text: root.lines("bottomRight") }
}
