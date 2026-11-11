pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Templates as T
import QtQuick.Layouts
import "../theme"

Basic.Dialog {
    id: dialog
    property string subtitle: ""
    property string titleIcon: ""
    property bool closeEnabled: true
    property bool closeButtonVisible: true
    property string closeButtonName: objectName + "Close"
    property T.AbstractButton defaultButton: titleClose
    property T.AbstractButton escapeButton: closeButtonVisible ? titleClose : null
    padding: 16
    spacing: 0
    modal: true
    focus: true
    closePolicy: closeEnabled ? Basic.Popup.CloseOnEscape : Basic.Popup.NoAutoClose
    Basic.Overlay.modal: Rectangle { color: Theme.modalScrim }
    DialogKeys {
        popup: dialog
        defaultButton: dialog.defaultButton
        escapeButton: dialog.escapeButton
    }
    background: Rectangle {
        color: Theme.panelBackgroundStrong
        border.color: Theme.borderStrong
        radius: 8
    }
    header: Item {
        implicitHeight: Math.max(32, heading.implicitHeight) + 28
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 16; anchors.rightMargin: 16
            anchors.topMargin: 16; anchors.bottomMargin: 12
            spacing: 10
            AppIcon {
                visible: dialog.titleIcon !== ""
                iconName: dialog.titleIcon
                iconSize: 24
                iconColor: Theme.primaryColor
            }
            ColumnLayout {
                id: heading
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                spacing: 5
                Text {
                    Layout.fillWidth: true
                    text: dialog.title
                    textFormat: Text.PlainText
                    color: Theme.textPrimary
                    font.pixelSize: 17
                    font.weight: Font.DemiBold
                    wrapMode: Text.Wrap
                    maximumLineCount: 2
                    elide: Text.ElideRight
                }
                Text {
                    Layout.fillWidth: true
                    visible: text !== ""
                    text: dialog.subtitle
                    textFormat: Text.PlainText
                    color: Theme.textMuted
                    font.pixelSize: 12
                    elide: Text.ElideRight
                }
            }
            AppButton {
                id: titleClose
                objectName: dialog.closeButtonName
                visible: dialog.closeButtonVisible
                Layout.alignment: Qt.AlignTop
                Layout.preferredWidth: 32
                Layout.preferredHeight: 32
                minimumButtonWidth: 32
                compact: true
                iconName: "close"
                iconSize: 16
                enabled: dialog.closeEnabled
                normalColor: "transparent"
                hoverBorderWidth: 0
                pressedBorderWidth: 0
                Accessible.name: qsTrId("text.0621")
                hintText: qsTrId("text.0621")
                onClicked: dialog.reject()
            }
        }
    }
}
