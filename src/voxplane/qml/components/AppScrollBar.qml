import QtQuick
import QtQuick.Controls.Basic as Basic
import "../theme"

Basic.ScrollBar {
    id: control
    objectName: "appScrollBar"
    orientation: Qt.Vertical
    x: parent ? parent.width - width : 0
    y: 0
    width: 8
    height: parent ? parent.height : 0
    visible: policy === Basic.ScrollBar.AlwaysOn || (policy !== Basic.ScrollBar.AlwaysOff && size < 1)
    padding: 1
    minimumSize: 0.08
    active: size < 1
    contentItem: Rectangle {
        implicitWidth: 6
        implicitHeight: 6
        radius: 3
        color: control.pressed ? Theme.primaryColor
            : control.hovered ? Theme.textSecondary : Theme.textSubtle
    }
    background: Rectangle {
        implicitWidth: 8
        implicitHeight: 8
        radius: 4
        color: Theme.borderSubtle
        opacity: 0.5
    }
}
