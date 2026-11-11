import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic as Basic
import "../theme"

Basic.TextField {
    id: control
    Layout.minimumWidth: 0
    property bool compact: false
    implicitHeight: compact ? Theme.compactControlHeight : Theme.controlHeight
    leftPadding: 10
    rightPadding: 10
    hoverEnabled: true
    color: enabled ? Theme.textPrimary : Theme.textDisabled
    placeholderTextColor: Theme.textSubtle
    font.pixelSize: Theme.bodyFontSize
    selectByMouse: true
    selectionColor: Theme.selectionBackground
    selectedTextColor: Theme.textPrimary
    background: Rectangle {
        radius: Theme.controlRadius
        color: control.enabled ? Theme.controlBackground : Theme.controlDisabled
        border.width: control.activeFocus ? 2 : 1
        border.color: !control.enabled ? Theme.controlBorder
            : control.activeFocus ? Theme.focusBorder
            : control.hovered ? Theme.controlHoverBorder : Theme.inputBorder
    }
}
