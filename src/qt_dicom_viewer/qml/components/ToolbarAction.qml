pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic as Basic
import "../theme"

Item {
    id: action

    required property string label
    required property string iconName
    required property string buttonObjectName
    property string shortLabel: label
    property bool actionEnabled: true
    property bool placeholder: false
    property bool checked: false
    property bool resetAction: false
    property real iconSize: Theme.toolbarIconSize
    property color normalIconColor: Theme.iconDefault
    property color disabledIconColor: Theme.iconDisabled
    property bool prominent: false
    property bool primaryAction: false
    property bool segmented: false
    property bool hoverWhenDisabled: false
    property string directionFace: ""
    property color directionColor: Theme.iconDefault
    property string tooltipPlacement: "above"
    property bool tooltipDismissed: false
    onHoveredChanged: if (!hovered) tooltipDismissed = false
    property string tooltipText: label + (placeholder ? qsTrId("text.0710") : "")
    readonly property bool hovered: hover.hovered
    readonly property bool tooltipVisible: tooltip.visible
    signal pressed()
    signal triggered()

    implicitWidth: 46
    implicitHeight: Theme.toolbarButtonHeight

    // 放在可用的容器上，确保禁用按钮也能解释不可用的原因。
    HoverHandler { id: hover }

    AppButton {
        id: button
        objectName: action.buttonObjectName
        anchors.fill: parent
        anchors.margins: action.segmented ? 3 : 0
        cornerRadius: Theme.controlRadius
        hoverBorderWidth: 0
        pressedBorderWidth: 0
        activeColor: action.segmented ? "transparent" : Theme.selectionBackground
        activeBorderColor: action.segmented ? "transparent" : Theme.selectionBorder
        enabled: action.actionEnabled && !action.placeholder
        checked: action.checked && enabled
        compact: true
        leftPadding: 2
        rightPadding: 2
        momentary: true
        minimumButtonWidth: 0
        normalColor: action.primaryAction ? Theme.primaryButtonBackground
            : action.prominent ? Theme.folderSurface : "transparent"
        disabledColor: action.hoverWhenDisabled && action.hovered ? Theme.controlHover
            : action.primaryAction ? Theme.primaryButtonDisabled : "transparent"
        hoverColor: action.primaryAction ? Theme.primaryButtonHover
            : action.segmented ? Theme.primarySoftHover
            : action.resetAction ? Theme.resetActionHover : Theme.controlHover
        pressedColor: action.primaryAction ? Theme.primaryButtonPressed
            : action.segmented ? Theme.selectionPressed
            : action.resetAction ? Theme.resetActionPressed : Theme.controlPressed
        activeHoverColor: action.segmented ? Theme.primarySoftHover
            : action.resetAction ? Theme.resetActionHover : Theme.selectionHover
        activePressedColor: action.resetAction ? Theme.resetActionPressed : Theme.selectionPressed
        hoverBorderColor: action.segmented ? "transparent"
            : action.resetAction ? Theme.resetActionBorder : Theme.selectionBorder
        pressedBorderColor: action.segmented ? "transparent"
            : action.resetAction ? Theme.resetActionBorder : Theme.selectionBorder
        Accessible.name: action.label
        Accessible.description: action.tooltipText
        onPressed: action.pressed()
        onClicked: { action.tooltipDismissed = true; action.triggered() }

        contentItem: Item {
            Column {
                anchors.centerIn: parent
                spacing: 3
                width: parent.width

                Item {
                    width: parent.width
                    height: action.iconSize
                    AppIcon {
                        objectName: "toolbarGlyph"
                        anchors.horizontalCenter: parent.horizontalCenter
                        visible: action.directionFace === ""
                        iconName: action.iconName
                        iconSize: action.iconSize
                        detailColor: action.iconName === "fusion" ? Theme.fusionAccent : "transparent"
                        iconColor: !button.enabled ? action.disabledIconColor
                            : action.segmented ? (button.hovered || button.down ? Theme.primaryHover : action.normalIconColor)
                            : action.resetAction && button.hovered ? Theme.resetActionColor
                            : button.down ? Theme.iconActive
                            : button.hovered ? (button.checked && !action.segmented ? Theme.primaryHover : Theme.iconHover)
                            : button.checked && !action.segmented ? Theme.iconActive : action.normalIconColor
                    }
                    Rectangle {
                        anchors.centerIn: parent
                        visible: action.directionFace !== ""
                        width: action.iconSize
                        height: width
                        radius: 4
                        color: button.enabled ? action.directionColor : Theme.controlDisabled
                        Text {
                            objectName: "currentVolumeFace"
                            anchors.centerIn: parent
                            text: action.directionFace
                            color: button.enabled ? Theme.textOnPrimary : Theme.textDisabled
                            font.pixelSize: 16
                            font.bold: true
                        }
                    }
                }

                Text {
                    objectName: "toolbarLabel"
                    visible: false
                    width: parent.width
                    text: action.shortLabel
                    horizontalAlignment: Text.AlignHCenter
                    color: !button.enabled ? Theme.textDisabled
                        : action.resetAction && button.hovered ? Theme.resetActionColor
                        : button.checked ? Theme.textPrimary : Theme.textSecondary
                    font.pixelSize: Theme.toolbarLabelSize
                    elide: Text.ElideRight
                }
            }
        }
    }

    Text {
        objectName: "placeholderBadge"
        visible: action.placeholder
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 2
        text: "·"
        color: Theme.textMuted
        font.pixelSize: 18
    }

    AppToolTip {
        id: tooltip
        objectName: "toolbarTooltip"
        visible: !action.tooltipDismissed && (action.hovered || button.visualFocus)
        placement: action.tooltipPlacement
        delay: 400
        text: action.tooltipText
    }
}
