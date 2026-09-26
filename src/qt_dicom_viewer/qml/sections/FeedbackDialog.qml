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
    readonly property bool hasAttachments: controller.attachments.length > 0
    readonly property bool canEmail: !controller.busy && subject.text.trim().length > 0 && (!hasAttachments || controller.attachmentsReviewed)
    width: Math.min(620, parent ? parent.width - 32 : 620)
    height: Math.min(680, parent ? parent.height - 40 : 680)
    titleIcon: "feedback"
    title: qsTrId("feedback.title")
    subtitle: qsTrId("feedback.subtitle")
    function send(channel) {
        controller.openDraft(channel, subject.text, kind.currentIndex === 1 ? "suggestion" : "bug", description.text, includeInfo.checked)
    }
    contentItem: Basic.ScrollView {
        id: scroller
        objectName: "feedbackScroll"
        rightPadding: 10
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
                Components.AppButton {
                    objectName: "feedbackAddAttachments"
                    text: qsTrId("feedback.addAttachments")
                    enabled: !dialog.controller.busy
                    onClicked: dialog.controller.chooseAttachments()
                }
                Text {
                    Layout.fillWidth: true
                    text: qsTrId("feedback.attachmentHint")
                    color: Theme.textMuted
                    wrapMode: Text.Wrap
                    font.pixelSize: 12
                }
            }
            Repeater {
                model: dialog.controller.attachments
                delegate: RowLayout {
                    id: attachmentRow
                    required property int index
                    required property var modelData
                    Layout.fillWidth: true
                    Text {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: attachmentRow.modelData.name
                        textFormat: Text.PlainText
                        elide: Text.ElideMiddle
                        color: Theme.textSecondary
                        font.pixelSize: 12
                    }
                    Text {
                        text: attachmentRow.modelData.size < 0 ? qsTrId("feedback.missingFile") : attachmentRow.modelData.size >= 1048576
                            ? (attachmentRow.modelData.size / 1048576).toFixed(1) + " MiB"
                            : (attachmentRow.modelData.size / 1024).toFixed(1) + " KiB"
                        color: Theme.textMuted
                        font.pixelSize: 12
                    }
                    Components.AppButton {
                        objectName: "feedbackRemoveAttachment-" + attachmentRow.index
                        iconName: "close"
                        compact: true
                        Accessible.name: qsTrId("feedback.removeAttachment") + " " + attachmentRow.modelData.name
                        enabled: !dialog.controller.busy
                        onClicked: dialog.controller.removeAttachment(attachmentRow.index)
                    }
                }
            }
            Components.AppCheckBox {
                objectName: "feedbackReviewAttachments"
                visible: dialog.hasAttachments
                Layout.fillWidth: true
                text: qsTrId("feedback.reviewAttachments")
                checked: dialog.controller.attachmentsReviewed
                enabled: !dialog.controller.busy
                onClicked: dialog.controller.setAttachmentsReviewed(checked)
            }
            Components.AppButton {
                objectName: "feedbackSaveEmail"
                visible: dialog.hasAttachments
                text: qsTrId("feedback.saveEmail")
                enabled: dialog.canEmail
                onClicked: dialog.controller.saveEmail(subject.text, kind.currentIndex === 1 ? "suggestion" : "bug", description.text, includeInfo.checked)
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

        }
    }
    footer: Item {
        implicitHeight: footerContent.implicitHeight + 32
        ColumnLayout {
            id: footerContent
            anchors.fill: parent
            anchors.margins: 16
            spacing: 10
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
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Components.AppButton {
                    objectName: "feedbackCopy"
                    text: qsTrId("feedback.copy")
                    onClicked: dialog.controller.copyFeedback(subject.text, kind.currentIndex === 1 ? "suggestion" : "bug", description.text, includeInfo.checked)
                }
                Item { Layout.fillWidth: true }
                Components.AppButton {
                    objectName: "feedbackEmail"
                    text: dialog.controller.busy ? qsTrId("feedback.mailWorking") : qsTrId("feedback.email")
                    enabled: dialog.canEmail
                    onClicked: dialog.send("email")
                }
                Components.AppButton {
                    objectName: "feedbackGitHub"
                    text: qsTrId("feedback.github")
                    iconName: "github"
                    actionRole: "primary"
                    enabled: !dialog.controller.busy
                    onClicked: dialog.send("github")
                }
            }
        }
    }
}
