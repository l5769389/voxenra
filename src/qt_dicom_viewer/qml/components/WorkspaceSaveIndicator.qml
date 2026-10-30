pragma ComponentBehavior: Bound
import QtQuick
import "../theme"

Item {
    id: indicator
    property var controller: null
    property bool badge: false
    property bool tooltipEnabled: true
    readonly property string status: controller?.recoveryState ?? "disabled"
    DelayedActivity { id: feedback; active: indicator.visible && indicator.status === "saving" }
    readonly property string displayStatus: status === "saving" && !feedback.showing ? "pending" : status
    readonly property string statusText: controller?.recoveryStatusText ?? qsTrId("text.0737")
    readonly property color statusColor: displayStatus === "saved" ? Theme.successColor
        : displayStatus === "error" ? Theme.dangerColor
        : ["pending", "recoverable"].includes(displayStatus) ? Theme.warningColor
        : displayStatus === "saving" ? Theme.primaryColor : Theme.textMuted
    implicitWidth: badge ? 12 : 20
    implicitHeight: implicitWidth
    Accessible.role: Accessible.StaticText
    Accessible.name: statusText
    Accessible.ignored: badge
    Rectangle {
        anchors.fill: parent
        radius: width / 2
        visible: indicator.badge
        color: Theme.panelBackgroundStrong
    }
    AppIcon {
        id: glyph
        anchors.centerIn: parent
        width: indicator.width - (indicator.badge ? 2 : 0)
        height: width
        iconName: ({saved: "check", saving: "reset", pending: "status-pending", recoverable: "reset",
            error: "close", disabled: "cine-pause", idle: "status-pending"})[indicator.displayStatus]
        iconColor: indicator.statusColor
    }
    RotationAnimation {
        target: glyph
        property: "rotation"
        from: 0; to: 360
        duration: 1100
        loops: Animation.Infinite
        running: feedback.showing
        onStopped: glyph.rotation = 0
    }
    HoverHandler { id: hover }
    AppToolTip {
        visible: indicator.tooltipEnabled && hover.hovered
        text: indicator.statusText + qsTrId("text.0738") + (indicator.controller?.recoveryPath ?? "")
    }
}
