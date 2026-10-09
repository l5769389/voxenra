pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import "../theme"

AppButton {
    id: control
    property string explanation: ""
    compact: true
    minimumButtonWidth: 28
    implicitWidth: 28
    implicitHeight: 28
    iconName: "help"
    iconSize: 18
    Accessible.name: qsTrId("ui.help")
    Accessible.description: explanation
    onClicked: details.visible ? details.close() : details.open()
    onVisibleChanged: if (!visible) details.close()
    AppToolTip { visible: control.hovered || control.visualFocus; text: qsTrId("ui.help") }
    Basic.Popup {
        id: details
        objectName: control.objectName + "Popup"
        parent: Basic.Overlay.overlay
        popupType: Basic.Popup.Item
        focus: true
        padding: 14
        margins: 8
        width: Math.min(380, (parent?.width ?? 396) - 16)
        height: Math.min(body.implicitHeight + padding * 2, (parent?.height ?? 600) - 32)
        closePolicy: Basic.Popup.CloseOnEscape | Basic.Popup.CloseOnPressOutside
        onAboutToShow: {
            const p = control.mapToItem(parent, 0, control.height)
            x = Math.max(8, Math.min(p.x + control.width - width, parent.width - width - 8))
            y = Math.max(8, Math.min(p.y + 6, parent.height - height - 8))
        }
        background: Rectangle { color: Theme.elevatedBackground; border.color: Theme.borderStrong; radius: 6 }
        contentItem: Basic.ScrollView {
            clip: true
            contentWidth: availableWidth
            Basic.ScrollBar.horizontal.policy: Basic.ScrollBar.AlwaysOff
            Text {
                id: body
                objectName: control.objectName + "Text"
                width: parent.width
                text: control.explanation
                textFormat: Text.PlainText
                color: Theme.textSecondary
                font.pixelSize: 13
                wrapMode: Text.Wrap
            }
        }
    }
}
