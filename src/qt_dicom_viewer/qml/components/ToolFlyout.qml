pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../theme"

Basic.Popup {
    id: flyout
    property string title: ""
    property string closeButtonName: "toolFlyoutClose"
    default property alias body: column.data
    readonly property real headerHeight: 24
    readonly property real chromeHeight: 2 * padding + headerHeight + column.spacing

    // Native Popup.Window dismisses before replaying the same press to the rail,
    // even with OutsideParent. Preserve that event's state until the button can
    // capture it on press; do not use a time-based debounce on subsequent clicks.
    property bool dismissedInCurrentEvent: false
    onAboutToHide: {
        dismissedInCurrentEvent = true
        Qt.callLater(function() { flyout.dismissedInCurrentEvent = false })
    }
    function wasOpenOnPress() { return visible || dismissedInCurrentEvent }

    // Keep rail presses for its own toggle handlers. Outside presses still dismiss.
    closePolicy: Basic.Popup.CloseOnEscape | Basic.Popup.CloseOnPressOutsideParent
    popupType: Basic.Popup.Window
    modal: false
    focus: true
    padding: 8
    margins: 8
    background: Rectangle {
        color: Theme.elevatedBackground
        border.color: Theme.borderStrong
        radius: Theme.controlRadius
    }
    contentItem: ColumnLayout {
        id: column
        spacing: 4
        RowLayout {
            objectName: "toolFlyoutHeader"
            Layout.fillWidth: true
            Layout.minimumHeight: flyout.headerHeight
            Layout.preferredHeight: flyout.headerHeight
            Layout.maximumHeight: flyout.headerHeight
            Text {
                Layout.fillWidth: true
                text: flyout.title
                color: Theme.textPrimary
                font.pixelSize: 13
                font.bold: true
                elide: Text.ElideRight
            }
            ToolbarAction {
                Layout.preferredWidth: 24
                Layout.preferredHeight: 24
                iconSize: 16
                buttonObjectName: flyout.closeButtonName
                iconName: "close"
                label: qsTrId("text.0621")
                onTriggered: flyout.close()
            }
        }
    }
}
