pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../components" as Components
import "../theme"

Components.AppDialog {
    id: dialog
    objectName: "feedbackDialog"
    required property var controller
    signal manualRequested()
    width: Math.min(620, parent ? parent.width - 32 : 620)
    height: Math.min(680, parent ? parent.height - 40 : 680)
    title: qsTrId("feedback.title")
    subtitle: qsTrId("feedback.subtitle")
    function send(channel) {
        controller.openDraft(channel, subject.text, kind.currentIndex === 1 ? "suggestion" : "bug", description.text, includeInfo.checked)
    }
    contentItem: Basic.ScrollView {
        id: scroller
        clip: true
        contentWidth: availableWidth
        Basic.ScrollBar.horizontal.policy: Basic.ScrollBar.AlwaysOff
        Basic.ScrollBar.vertical: Components.AppScrollBar {}
        ColumnLayout {
            width: scroller.availableWidth
            spacing: 12
            RowLayout {
                Layout.fillWidth: true
                Components.AppComboBox {
                    id: kind
                    objectName: "feedbackKind"
                    Layout.preferredWidth: 165
                    model: [qsTrId("feedback.bug"), qsTrId("feedback.suggestion")]
                    Accessible.name: qsTrId("feedback.kind")
                }
                Item { Layout.fillWidth: true }
                Components.AppButton {
                    text: qsTrId("feedback.manual")
                    iconName: "manual"
                    normalColor: "transparent"
                    onClicked: { dialog.close(); dialog.manualRequested() }
                }
            }
            Components.AppTextField {
                id: subject
                objectName: "feedbackSubject"
                Layout.fillWidth: true
                placeholderText: qsTrId("feedback.subject")
                Accessible.name: qsTrId("feedback.subject")
                maximumLength: 160
            }
            Basic.ScrollView {
                Layout.fillWidth: true
                Layout.preferredHeight: 140
                clip: true
                contentWidth: availableWidth
                Basic.ScrollBar.horizontal.policy: Basic.ScrollBar.AlwaysOff
                Basic.ScrollBar.vertical: Components.AppScrollBar {}
                Basic.TextArea {
                    id: description
                    objectName: "feedbackDescription"
                    placeholderText: qsTrId("feedback.description")
                    Accessible.name: qsTrId("feedback.description")
                    textFormat: TextEdit.PlainText
                    wrapMode: TextEdit.Wrap
                    selectByMouse: true
                    color: Theme.textPrimary
                    placeholderTextColor: Theme.textSubtle
                    selectionColor: Theme.selectionBackground
                    selectedTextColor: Theme.textPrimary
                    font.pixelSize: 13
                    padding: 10
                    background: Rectangle { color: Theme.controlBackground; border.color: description.activeFocus ? Theme.focusBorder : Theme.inputBorder; radius: 5 }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Components.AppCheckBox {
                    id: includeInfo
                    objectName: "feedbackIncludeInfo"
                    text: qsTrId("feedback.includeInfo")
                    checked: true
                }
                Item { Layout.fillWidth: true }
                Components.AppButton {
                    id: details
                    objectName: "feedbackDetails"
                    property bool expanded: false
                    text: expanded ? qsTrId("feedback.hideInfo") : qsTrId("feedback.showInfo")
                    normalColor: "transparent"
                    onClicked: expanded = !expanded
                }
            }
            Basic.TextArea {
                objectName: "feedbackSystemInfo"
                Layout.fillWidth: true
                visible: details.expanded
                text: dialog.controller.systemInfo
                textFormat: TextEdit.PlainText
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.Wrap
                color: Theme.textSecondary
                selectionColor: Theme.selectionBackground
                selectedTextColor: Theme.textPrimary
                font.pixelSize: 12
                padding: 10
                background: Rectangle { radius: 5; color: Theme.panelBackgroundSoft }
            }
            Text {
                Layout.fillWidth: true
                text: qsTrId("feedback.privacy")
                color: Theme.textMuted
                font.pixelSize: 12
                wrapMode: Text.Wrap
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: Theme.dividerColor }
            RowLayout {
                Layout.fillWidth: true
                Text { text: dialog.controller.email; color: Theme.textSecondary; font.pixelSize: 13 }
                Item { Layout.fillWidth: true }
                Components.AppButton {
                    objectName: "feedbackCopyEmail"
                    text: qsTrId("feedback.copyEmail")
                    compact: true
                    normalColor: "transparent"
                    onClicked: dialog.controller.copyEmail()
                }
            }
            Text {
                objectName: "feedbackStatus"
                Layout.fillWidth: true
                visible: text !== ""
                text: dialog.controller.status
                textFormat: Text.PlainText
                color: Theme.textSecondary
                font.pixelSize: 12
                wrapMode: Text.Wrap
                Accessible.role: Accessible.StaticText
                Accessible.name: text
            }
        }
    }
    footer: Item {
        implicitHeight: 64
        RowLayout {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 8
            Components.AppButton {
                objectName: "feedbackCopy"
                text: qsTrId("feedback.copy")
                onClicked: dialog.controller.copyFeedback(subject.text, kind.currentIndex === 1 ? "suggestion" : "bug", description.text, includeInfo.checked)
            }
            Item { Layout.fillWidth: true }
            Components.AppButton {
                objectName: "feedbackEmail"
                text: qsTrId("feedback.email")
                enabled: subject.text.trim().length > 0
                onClicked: dialog.send("email")
            }
            Components.AppButton {
                objectName: "feedbackGitHub"
                text: qsTrId("feedback.github")
                iconName: "github"
                actionRole: "primary"
                enabled: subject.text.trim().length > 0
                onClicked: dialog.send("github")
            }
        }
    }
}
