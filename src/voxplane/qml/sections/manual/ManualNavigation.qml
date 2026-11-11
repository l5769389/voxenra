pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../../components" as Components
import "../../theme"

Rectangle {
    id: navigation
    objectName: "manualNavigation"
    required property var controller
    color: Theme.panelBackground

    function revealChapter(button) {
        revealTimer.restart()
    }
    onWidthChanged: revealTimer.restart()
    Connections {
        target: navigationScroll.contentItem
        function onContentHeightChanged() { revealTimer.restart() }
        function onHeightChanged() { revealTimer.restart() }
    }
    Timer {
        id: revealTimer
        interval: 40
        onTriggered: {
            // Search and language changes rebuild delegates; find the live
            // selection instead of keeping a reference to a discarded button.
            let button = null
            for (let i = 0; i < categoryRepeater.count; ++i) {
                const category = categoryRepeater.itemAt(i)
                if (category) button = category.currentButton() ?? button
            }
            if (!button) return
            const scroller = navigationScroll.contentItem
            const top = button.mapToItem(scroller.contentItem, 0, 0).y
            const bottom = top + button.height
            scroller.contentY = Math.max(0, Math.min(
                Math.max(0, scroller.contentHeight - scroller.height),
                top < scroller.contentY ? top : bottom > scroller.contentY + scroller.height
                    ? bottom - scroller.height : scroller.contentY))
        }
    }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 10
        Components.AppTextField {
            objectName: "manualSearch"
            Layout.fillWidth: true
            font.pixelSize: 14
            placeholderText: qsTrId("text.0949")
            text: navigation.controller?.search ?? ""
            onTextEdited: navigation.controller?.setSearch(text)
        }
        Basic.ScrollView {
            id: navigationScroll
            objectName: "manualNavigationScroll"
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            rightPadding: 8
            clip: true
            Basic.ScrollBar.vertical: Components.AppScrollBar {}
            Basic.ScrollBar.horizontal.policy: Basic.ScrollBar.AlwaysOff
            ColumnLayout {
                width: navigationScroll.availableWidth
                spacing: 6
                Repeater {
                    id: categoryRepeater
                    model: navigation.controller?.navigation ?? []
                    delegate: ColumnLayout {
                        id: categoryEntry
                        required property var modelData
                        function currentButton() {
                            if (!modelData.expanded) return null
                            for (let i = 0; i < chapterRepeater.count; ++i) {
                                const button = chapterRepeater.itemAt(i)
                                if (button?.checked) return button
                            }
                            return null
                        }
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        spacing: 3
                        Components.AppButton {
                            id: groupButton
                            objectName: "manualCategory-" + categoryEntry.modelData.id
                            Layout.fillWidth: true
                            implicitHeight: Math.max(38, groupTitle.implicitHeight + 14)
                            minimumButtonWidth: 0
                            leftPadding: 6; rightPadding: 6
                            normalColor: "transparent"
                            momentary: true
                            Accessible.name: categoryEntry.modelData.title
                            onClicked: navigation.controller.toggleCategory(categoryEntry.modelData.id)
                            contentItem: RowLayout {
                                spacing: 8
                                Components.AppIcon {
                                    iconName: categoryEntry.modelData.icon
                                    iconSize: 20
                                    iconColor: Theme.textMuted
                                }
                                Text {
                                    id: groupTitle
                                    Layout.fillWidth: true
                                    text: categoryEntry.modelData.title
                                    color: Theme.textMuted
                                    font.pixelSize: 14
                                    font.weight: Font.DemiBold
                                    wrapMode: Text.Wrap
                                }
                                Components.AppIcon {
                                    iconName: categoryEntry.modelData.expanded ? "chevron-down" : "chevron-right"
                                    iconSize: 14
                                    iconColor: Theme.textMuted
                                }
                            }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            visible: categoryEntry.modelData.expanded
                            spacing: 3
                            Repeater {
                                id: chapterRepeater
                                model: categoryEntry.modelData.chapters
                                delegate: Components.AppButton {
                                    id: chapterButton
                                    required property var modelData
                                    objectName: "manualChapter-" + modelData.id
                                    Layout.fillWidth: true
                                    implicitHeight: Math.max(38, chapterTitle.implicitHeight + 14)
                                    minimumButtonWidth: 0
                                    leftPadding: 12; rightPadding: 8
                                    momentary: true
                                    normalColor: "transparent"
                                    activeBorderColor: "transparent"
                                    checked: navigation.controller?.chapterId === modelData.id
                                    onCheckedChanged: if (checked) navigation.revealChapter(chapterButton)
                                    onVisibleChanged: if (visible && checked) navigation.revealChapter(chapterButton)
                                    Component.onCompleted: if (checked) navigation.revealChapter(chapterButton)
                                    Accessible.name: categoryEntry.modelData.title + " · " + modelData.title
                                    onClicked: navigation.controller.selectChapter(modelData.id)
                                    contentItem: RowLayout {
                                        spacing: 8
                                        Components.AppIcon {
                                            iconName: chapterButton.modelData.icon
                                            iconSize: 18
                                            iconColor: chapterButton.checked ? Theme.primaryColor : Theme.textSubtle
                                        }
                                        Text {
                                            id: chapterTitle
                                            Layout.fillWidth: true
                                            text: chapterButton.modelData.title
                                            color: chapterButton.checked ? Theme.primaryColor : Theme.textSecondary
                                            font.pixelSize: 14
                                            wrapMode: Text.Wrap
                                            verticalAlignment: Text.AlignVCenter
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                Text {
                    Layout.fillWidth: true
                    visible: (navigation.controller?.navigation.length ?? 0) === 0
                    text: qsTrId("text.0950")
                    color: Theme.textMuted
                    font.pixelSize: 14
                    wrapMode: Text.Wrap
                }
            }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.dividerColor }
        Components.AppButton {
            objectName: "manualFeedback"
            Layout.fillWidth: true
            text: qsTrId("feedback.title")
            iconName: "feedback"
            normalColor: "transparent"
            onClicked: appController.feedbackController.show()
        }
    }
}
