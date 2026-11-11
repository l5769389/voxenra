import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic as Basic
import "../theme"

Basic.Slider {
    id: control
    property color accentColor: Theme.primaryColor
    Layout.minimumWidth: horizontal ? 32 : 16
    implicitWidth: horizontal ? 160 : 32
    implicitHeight: horizontal ? 32 : 160
    padding: 8
    hoverEnabled: true
    background: Rectangle {
        x: control.horizontal ? control.leftPadding : control.leftPadding + (control.availableWidth - width) / 2
        y: control.horizontal ? control.topPadding + (control.availableHeight - height) / 2 : control.topPadding
        width: control.horizontal ? control.availableWidth : 4
        height: control.horizontal ? 4 : control.availableHeight
        radius: 2
        color: control.enabled ? Theme.sliderTrack : Theme.controlBorder
        Rectangle {
            x: control.horizontal && control.mirrored ? parent.width - width : 0
            y: control.horizontal ? 0 : parent.height - height
            width: control.horizontal ? control.position * parent.width : parent.width
            height: control.horizontal ? parent.height : control.position * parent.height
            radius: 2
            color: control.enabled ? control.accentColor : Theme.iconDisabled
        }
    }
    handle: Rectangle {
        x: control.leftPadding + (control.horizontal
            ? control.visualPosition * (control.availableWidth - width) : (control.availableWidth - width) / 2)
        y: control.topPadding + (control.horizontal
            ? (control.availableHeight - height) / 2 : control.visualPosition * (control.availableHeight - height))
        implicitWidth: 16
        implicitHeight: 16
        radius: 8
        color: !control.enabled ? Theme.iconDisabled
            : control.pressed || control.hovered ? Theme.textPrimary : control.accentColor
        border.width: 2
        border.color: Theme.controlBackground
        Rectangle {
            anchors.fill: parent
            anchors.margins: -4
            visible: control.activeFocus
            radius: width / 2
            color: "transparent"
            border.width: 2
            border.color: Theme.focusBorder
        }
    }
}
