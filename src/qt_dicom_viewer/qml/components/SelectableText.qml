pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import "../theme"
TextEdit {
    id: textBlock
    readOnly: true
    selectByMouse: true
    persistentSelection: true
    textFormat: TextEdit.PlainText
    wrapMode: TextEdit.Wrap
    color: Theme.textSecondary
    selectionColor: Theme.selectionBackground
    selectedTextColor: Theme.textPrimary
    padding: 0
    activeFocusOnTab: true
    TapHandler {
        acceptedButtons: Qt.RightButton
        onTapped: selectionMenu.popup()
    }
    Basic.Menu {
        id: selectionMenu
        readonly property PopupScope shortcutScope: PopupScope { popup: selectionMenu }
        Basic.MenuItem {
            text: qsTrId("text.1034")
            enabled: textBlock.selectedText.length > 0
            onTriggered: textBlock.copy()
        }
        Basic.MenuItem { text: qsTrId("selection.all"); onTriggered: textBlock.selectAll() }
    }
}
