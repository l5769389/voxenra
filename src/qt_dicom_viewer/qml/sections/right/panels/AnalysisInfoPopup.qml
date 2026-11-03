pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../../../theme"
import "../../../components" as Components

Basic.Popup {
    id: info
    objectName: "mtfInfoPopup"
    required property var anchorItem
    property string explanation: ""
    property var warnings: []
    parent: Basic.Overlay.overlay
    popupType: Basic.Popup.Item
    modal: false
    focus: true
    Components.DialogKeys { popup: info; closeOnEnter: true }
    padding: 14
    margins: 8
    closePolicy: Basic.Popup.CloseOnEscape | Basic.Popup.CloseOnPressOutside
    width: Math.min(380, (parent?.width ?? 396) - 16)
    height: Math.min(details.implicitHeight + padding * 2, (parent?.height ?? 600) - 32)
    onAboutToShow: {
        const position = anchorItem.mapToItem(parent, 0, anchorItem.height)
        x = Math.max(8, Math.min(position.x + anchorItem.width - width, parent.width - width - 8))
        y = Math.max(8, Math.min(position.y + 6, parent.height - height - 8))
    }
    background: Rectangle {
        color: Theme.elevatedBackground
        border.color: Theme.borderStrong
        radius: 6
    }
    contentItem: Basic.ScrollView {
        clip: true
        contentWidth: availableWidth
        Basic.ScrollBar.horizontal.policy: Basic.ScrollBar.AlwaysOff
        ColumnLayout {
            id: details
            width: parent.width
            spacing: 12
            Text {
                Layout.fillWidth: true
                text: qsTrId("mtf.details")
                font.pixelSize: 13
                font.bold: true
                color: Theme.textPrimary
            }
            Text {
                objectName: "mtfInfoExplanation"
                Layout.fillWidth: true
                text: info.explanation
                textFormat: Text.PlainText
                font.pixelSize: 12
                color: Theme.textSecondary
                wrapMode: Text.Wrap
            }
            Repeater {
                model: info.warnings
                Text {
                    required property string modelData
                    required property int index
                    objectName: "mtfInfoWarning-" + index
                    Layout.fillWidth: true
                    text: modelData
                    textFormat: Text.PlainText
                    font.pixelSize: 12
                    color: Theme.chartY
                    wrapMode: Text.Wrap
                }
            }
        }
    }
}
