pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window
import QtQuick.Controls.Basic as Basic
import "../theme"

Basic.ToolTip {
    id: tip
    property string placement: "above"
    readonly property real gap: 8
    property int geometryRevision: 0
    readonly property var anchorWindow: parent?.Window.window ?? null
    readonly property point anchorPosition: {
        // Depend on the available geometry before Popup.Window is exposed.
        const revision = (parent?.x ?? 0) + (parent?.y ?? 0)
            + (anchorWindow?.width ?? 0) + (anchorWindow?.height ?? 0) + geometryRevision
        return parent ? parent.mapToItem(null, 0, 0) : Qt.point(0, 0)
    }
    readonly property point popupPosition: {
        const aw = parent?.width ?? 0
        const ah = parent?.height ?? 0
        const left = margins - anchorPosition.x
        const top = margins - anchorPosition.y
        const right = (anchorWindow?.width ?? 376) - margins - anchorPosition.x
        const bottom = (anchorWindow?.height ?? 600) - margins - anchorPosition.y
        const centerX = Math.max(left, Math.min((aw - width) / 2, right - width))
        const centerY = Math.max(top, Math.min((ah - height) / 2, bottom - height))
        const opposite = {above: "below", below: "above", left: "right", right: "left"}
        // Clamping an 'above' tooltip at the top edge can cover its trigger.
        // Try the opposite side, then the other axis, keeping the hover area clear.
        for (const side of [placement, opposite[placement], "above", "below", "left", "right"]) {
            if (side === "above" && -height - gap >= top)
                return Qt.point(centerX, -height - gap)
            if (side === "below" && ah + gap + height <= bottom)
                return Qt.point(centerX, ah + gap)
            if (side === "left" && -width - gap >= left)
                return Qt.point(-width - gap, centerY)
            if (side === "right" && aw + gap + width <= right)
                return Qt.point(aw + gap, centerY)
        }
        // Very long text in a small window may not fit on any side. Keep it
        // within the window; the native tooltip remains input-transparent.
        return Qt.point(centerX, Math.max(top, Math.min(-height - gap, bottom - height)))
    }
    x: popupPosition.x
    y: popupPosition.y
    onAboutToShow: geometryRevision++
    property bool requested: false
    property string displayedCaption: {
        if (parent?.displayedButtonCaption !== undefined) return parent.displayedButtonCaption
        const label = parent?.contentItem
        return label?.visible && !label.truncated ? label.text ?? "" : ""
    }
    visible: requested && parent?.visible === true && anchorWindow?.visible === true
        && text.length > 0 && text !== displayedCaption && Qt.application.state === Qt.ApplicationActive
        && (anchorWindow?.active || anchorWindow?.transientParent?.active || false)
    // Explicit styling also applies to controls backed by the system light palette.
    popupType: Basic.Popup.Window
    focus: false
    modal: false
    closePolicy: Basic.Popup.NoAutoClose
    delay: 500
    padding: 10
    margins: 8
    opacity: 1
    implicitWidth: Math.min(360, Math.max(80, (parent?.Window.window?.width ?? 376) - 16), label.implicitWidth + padding * 2)
    implicitHeight: label.implicitHeight + padding * 2
    Binding {
        // ToolTip's native window otherwise draws a square platform frame
        // around our rounded background (especially visible in light mode).
        target: label.Window.window
        property: "flags"
        when: !!target && !!tip.parent && target !== tip.parent.Window.window
        // Never steal hover from the anchor, even when the window manager
        // repositions a tooltip near a screen edge or over a native 3D view.
        value: Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus
            | Qt.WindowTransparentForInput
        restoreMode: Binding.RestoreNone
    }
    contentItem: Text {
        id: label
        readonly property bool passiveToolTip: true
        text: tip.text
        textFormat: Text.PlainText
        color: Theme.textPrimary
        font.pixelSize: 13
        wrapMode: Text.Wrap
        lineHeight: 1.2
    }
    background: Rectangle {
        color: Theme.elevatedBackground
        opacity: 1
        border.color: Theme.borderStrong
        radius: Theme.controlRadius
    }
}
