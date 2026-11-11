pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import QtQuick.Controls.Basic as Basic
import "../theme"

Basic.Button {
    id: control
    // Match a pointer/keyboard activation: update state and emit the action.
    Accessible.onToggleAction: control.click()
    Layout.minimumWidth: 0

    property string actionRole: "neutral"
    property bool compact: false
    property bool momentary: false
    property string iconName: ""
    property real iconSize: 18
    property real minimumButtonWidth: 40
    property real cornerRadius: Theme.controlRadius
    property real fontPixelSize: 13
    property int fontWeight: actionRole === "primary" ? Font.DemiBold : Font.Normal
    property string shortcutTitle: ""
    property string captionKey: ""
    property string dialogKeyHint: ""
    property string hintText: ""
    readonly property string keyboardHintText: dialogKeyHint && enabled
        ? (hintText || text || Accessible.name) + " (" + dialogKeyHint + ")" : hintText || text
    readonly property string displayedButtonCaption: {
        const label = contentItem === defaultContent ? contentLabel : contentItem
        return label?.visible && !label.truncated ? label.text ?? "" : ""
    }
    // Keep the full text for accessibility and the hover/focus tooltip.
    text: captionKey ? shortcutTitle + " (" + captionKey + ")" : shortcutTitle

    property color normalColor: actionRole === "primary" ? Theme.primaryButtonBackground
        : actionRole === "danger" ? Theme.dangerSurface : Theme.controlBackground
    property color hoverColor: actionRole === "primary" ? Theme.primaryButtonHover
        : actionRole === "danger" ? Theme.dangerButtonHover : Theme.controlHover
    property color pressedColor: actionRole === "primary" ? Theme.primaryButtonPressed
        : actionRole === "danger" ? Theme.dangerButtonPressed : Theme.controlPressed
    property color activeColor: Theme.selectionBackground
    property color activeHoverColor: Theme.selectionHover
    property color activePressedColor: Theme.selectionPressed
    property color hoverBorderColor: Theme.controlHoverBorder
    property color pressedBorderColor: Theme.selectionBorder
    property color disabledColor: actionRole === "primary" ? Theme.primaryButtonDisabled : Theme.controlDisabled
    property color textColor: actionRole === "primary" ? Theme.textOnPrimary
        : actionRole === "danger" ? Theme.dangerColor : Theme.textPrimary
    property color disabledTextColor: Theme.textDisabled
    property color focusBorderColor: Theme.focusBorder
    property color activeBorderColor: Theme.selectionBorder
    property color baseBorderColor: Theme.borderDefault
    property real baseBorderWidth: 0
    property real hoverBorderWidth: 1
    property real pressedBorderWidth: 1

    readonly property bool hasIcon:
        control.iconName !== "" || control.icon.source.toString() !== ""

    readonly property bool hasText:
        control.text.length > 0

    hoverEnabled: true
    HoverHandler { cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }
    focusPolicy: control.momentary
        ? Qt.TabFocus
        : Qt.StrongFocus

    leftPadding: compact ? 6 : 12
    rightPadding: compact ? 6 : 12
    topPadding: compact ? 6 : 8
    bottomPadding: compact ? 6 : 8

    implicitWidth: Math.max(
        minimumButtonWidth,
        contentLabel.preferredWidth + (hasIcon ? iconSize + (hasText ? 7 : 0) : 0) + leftPadding + rightPadding
    )

    implicitHeight: compact ? Theme.compactControlHeight : Theme.controlHeight

    background: Rectangle {
        radius: control.cornerRadius

        readonly property color fillTarget: {
            if (!control.enabled)
                return control.disabledColor
            if (control.down)
                return control.checked ? control.activePressedColor : control.pressedColor
            if (control.checked)
                return control.hovered ? control.activeHoverColor : control.activeColor
            if (control.hovered)
                return control.hoverColor
            return control.normalColor
        }

        // Interpolate premultiplied RGB and alpha together. Straight QColor
        // interpolation passes through black when fading from "transparent".
        function premultiply(value) {
            return Qt.vector3d(value.r * value.a, value.g * value.a, value.b * value.a)
        }
        function unpremultiply(rgb, alpha) {
            return alpha > 0 ? Qt.rgba(rgb.x / alpha, rgb.y / alpha, rgb.z / alpha, alpha) : "transparent"
        }
        property vector3d fillRgb: premultiply(fillTarget)
        property real fillAlpha: fillTarget.a
        color: unpremultiply(fillRgb, fillAlpha)
        Behavior on fillRgb { Vector3dAnimation { duration: 90 } }
        Behavior on fillAlpha { NumberAnimation { duration: 90 } }

        border.width: Math.max(
            control.baseBorderWidth,
            control.visualFocus ? 2 : !control.enabled ? 0 : control.checked ? 1
                : control.down ? control.pressedBorderWidth : control.hovered ? control.hoverBorderWidth : 0
        )
        readonly property color borderTarget: control.visualFocus ? control.focusBorderColor
            : control.enabled && control.down ? control.pressedBorderColor
            : control.enabled && control.hovered ? control.hoverBorderColor
            : control.checked ? control.activeBorderColor : control.baseBorderColor
        property vector3d borderRgb: premultiply(borderTarget)
        property real borderAlpha: borderTarget.a
        border.color: unpremultiply(borderRgb, borderAlpha)
        Behavior on borderRgb { Vector3dAnimation { duration: 80 } }
        Behavior on borderAlpha { NumberAnimation { duration: 80 } }
    }

    contentItem: Item {
        id: defaultContent
        implicitWidth: contentLabel.preferredWidth + (control.hasIcon ? control.iconSize + (control.hasText ? 7 : 0) : 0)
        implicitHeight: contentRow.implicitHeight

        Row {
            id: contentRow

            anchors.centerIn: parent
            spacing: control.hasIcon && control.hasText ? 7 : 0

            AppIcon {
                visible: control.iconName !== ""
                anchors.verticalCenter: parent.verticalCenter
                iconName: control.iconName
                iconSize: control.iconSize
                iconColor: control.enabled ? control.textColor : control.disabledTextColor
            }

            Image {
                visible: control.iconName === "" && control.hasIcon

                anchors.verticalCenter: parent.verticalCenter
                width: control.iconSize
                height: control.iconSize
                sourceSize.width: Math.ceil(control.iconSize * Math.max(1, Screen.devicePixelRatio))
                sourceSize.height: Math.ceil(control.iconSize * Math.max(1, Screen.devicePixelRatio))

                source: control.icon.source
                fillMode: Image.PreserveAspectFit
                smooth: true
                mipmap: true
                opacity: control.enabled ? 1 : 0.45
            }

            ShortcutLabel {
                id: contentLabel
                objectName: control.shortcutTitle ? "buttonCaption" : ""
                visible: control.hasText
                width: Math.max(0, Math.min(preferredWidth, control.availableWidth
                    - (control.hasIcon ? control.iconSize + contentRow.spacing : 0)))

                anchors.verticalCenter: parent.verticalCenter
                title: control.shortcutTitle || control.text
                keyHint: control.captionKey || (control.enabled && control.hasText ? control.dialogKeyHint : "")
                maximumLineCount: control.shortcutTitle ? 1 : 2147483647
                textFormat: control.shortcutTitle ? Text.PlainText : Text.AutoText
                color: control.enabled
                    ? control.textColor
                    : control.disabledTextColor

                font.pixelSize: control.fontPixelSize
                font.weight: control.checked
                    ? Font.DemiBold
                    : control.fontWeight

                verticalAlignment: Text.AlignVCenter
            }
        }
    }

    AppToolTip {
        objectName: control.objectName ? control.objectName + "-hint" : ""
        requested: (control.hovered || control.visualFocus)
            && (control.hintText !== "" || (control.contentItem === defaultContent
                && (contentLabel.truncated || contentLabel.text !== control.keyboardHintText)))
        text: control.keyboardHintText
    }
}
