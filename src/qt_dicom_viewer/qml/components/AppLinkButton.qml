pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic as Basic
import "../theme"

Basic.Button {
    id: control
    property string tooltip: text
    Layout.minimumWidth: 0
    implicitWidth: Math.min(260, label.implicitWidth + leftPadding + rightPadding)
    implicitHeight: 28
    padding: 4
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.name: text
    Accessible.description: tooltip
    HoverHandler { cursorShape: Qt.PointingHandCursor }
    AppToolTip {
        visible: (parent?.hovered ?? false) && parent.tooltip !== ""
        delay: 500
        text: parent?.tooltip ?? ""
    }
    contentItem: Text {
        id: label
        text: control.text
        textFormat: Text.PlainText
        font.pixelSize: 12
        font.underline: true
        color: control.enabled ? Theme.iconActive : Theme.textDisabled
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideMiddle
        maximumLineCount: 1
    }
    background: Rectangle {
        radius: Theme.controlRadius
        color: control.down ? Theme.controlPressed : control.hovered ? Theme.controlHover : "transparent"
        border.width: control.visualFocus ? 1 : 0
        border.color: Theme.focusBorder
    }
}
