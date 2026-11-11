pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../theme"

RowLayout {
    id: heading
    property string title: ""
    property string explanation: ""
    Layout.fillWidth: true
    spacing: 8

    Text {
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        text: heading.title
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: Theme.textPrimary
        font.pixelSize: 14
        font.weight: Font.DemiBold
    }
    HelpButton {
        objectName: heading.objectName + "Help"
        Layout.preferredWidth: 28
        Layout.preferredHeight: 28
        explanation: heading.explanation
        visible: explanation.length > 0
    }
}
