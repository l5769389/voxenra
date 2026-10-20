pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../../components" as Components
import "../../theme"
import "../center/viewportArea" as ViewportUi

Rectangle {
    id: manual
    objectName: "operationManual"
    required property var controller
    readonly property var article: controller?.currentChapter ?? ({})
    readonly property string chapter: controller?.chapterId ?? ""
    property bool restoring: true
    property string positionChapter: ""
    property bool active: true
    property string playingTutorialId: ""
    onArticleChanged: playingTutorialId = ""
    onActiveChanged: {
        if (active) restorePosition()
        else {
            restoring = true
            playingTutorialId = ""
        }
    }
    property bool petExample: false
    color: Theme.panelBackgroundStrong

    property real dragWidth: -1
    readonly property real navigationLimit: Math.max(180, Math.min(400, width - 368))
    readonly property real navigationWidth: Math.min(navigationLimit,
        dragWidth >= 0 ? dragWidth : (controller?.navigationWidth ?? 260))

    function restorePosition() {
        restoring = true
        readingArea.cancelFlick()
        // Chapter changes reset synchronously; delayed text/image layout still
        // uses the timer for restoring an existing chapter's saved offset.
        if (controller && controller.scrollPosition === 0)
            readingArea.contentY = 0
        restoreTimer.restart()
    }
    Timer {
        id: restoreTimer
        // Incubation completes before wrapped text and images finish layout.
        // Restore only after their geometry has settled, without saving the
        // temporary zero/clamped offset back into the chapter controller.
        interval: 16
        onTriggered: {
            if (!manual.controller || !manual.active) return
            const section = manual.controller.sectionIndex >= 0
                ? sectionRepeater.itemAt(manual.controller.sectionIndex) : null
            const offset = section ? section.y + readingContent.y : manual.controller.scrollPosition
            readingArea.contentY = Math.max(0, Math.min(offset,
                readingArea.contentHeight - readingArea.height))
            manual.positionChapter = manual.controller.chapterId
            manual.restoring = false
            manual.controller.setScrollPosition(readingArea.contentY)
        }
    }
    Component.onCompleted: restorePosition()
    Connections {
        target: manual.controller
        function onChapterChanged() { manual.restorePosition() }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0
        ManualNavigation {
            controller: manual.controller
            Layout.minimumWidth: manual.navigationWidth
            Layout.preferredWidth: manual.navigationWidth
            Layout.maximumWidth: manual.navigationWidth
            Layout.fillHeight: true
        }
        Components.WidthResizeHandle {
            objectName: "manualNavigationResizeHandle"
            Layout.preferredWidth: 8
            Layout.fillHeight: true
            currentWidth: manual.navigationWidth
            minimumWidth: Math.min(220, manual.navigationLimit)
            maximumWidth: manual.navigationLimit
            onWidthDragged: value => manual.dragWidth = value
            onWidthCommitted: value => {
                manual.controller?.setNavigationWidth(Math.round(value))
                manual.dragWidth = -1
            }
        }
        Flickable {
            id: readingArea
            objectName: "manualReadingArea"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumWidth: 0
            contentWidth: width
            contentHeight: readingContent.implicitHeight + 40
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            onMovementStarted: {
                restoreTimer.stop()
                manual.positionChapter = manual.controller?.chapterId ?? ""
                manual.restoring = false
            }
            onContentHeightChanged: if (manual.active && manual.restoring) restoreTimer.restart()
            onHeightChanged: if (manual.active && manual.restoring) restoreTimer.restart()
            // A chapter notification may resize the old content before its
            // restore handler runs. Do not write that offset to the new chapter.
            onContentYChanged: if (manual.active && !manual.restoring
                && manual.positionChapter === manual.controller?.chapterId)
                manual.controller?.setScrollPosition(contentY)
            Basic.ScrollBar.vertical: Components.AppScrollBar {}
            ColumnLayout {
                id: readingContent
                x: (readingArea.width - width) / 2; y: 20
                width: Math.min(900, Math.max(1, readingArea.width - 48))
                spacing: 16
                Components.SelectableText {
                    Layout.fillWidth: true
                    text: manual.article.categoryTitle ?? ""
                    color: Theme.textMuted
                    font.pixelSize: 11
                    wrapMode: TextEdit.Wrap
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    Components.AppIcon {
                        iconName: manual.article.icon ?? "manual"
                        iconSize: 26
                        iconColor: Theme.primaryColor
                    }
                    Components.SelectableText {
                        objectName: "manualChapterTitle"
                        Layout.fillWidth: true
                        text: manual.article.title ?? ""
                        color: Theme.textPrimary
                        font.pixelSize: 24
                        font.weight: Font.DemiBold
                        wrapMode: TextEdit.Wrap
                    }
                }
                Components.SelectableText {
                    objectName: "manualChapterSummary"
                    Layout.fillWidth: true
                    text: manual.article.summary ?? ""
                    textFormat: TextEdit.PlainText
                    color: Theme.textMuted
                    font.pixelSize: 14
                    wrapMode: TextEdit.Wrap
                }
                Flow {
                    objectName: "manualShortcuts"
                    Layout.fillWidth: true
                    visible: (manual.article.shortcuts?.length ?? 0) > 0
                    spacing: 8
                    Repeater {
                        model: manual.article.shortcuts ?? []
                        delegate: Rectangle {
                            id: shortcut
                            required property var modelData
                            required property int index
                            objectName: "manualShortcut-" + index
                            readonly property string keys: Qt.platform.os === "osx"
                                ? modelData.mac : modelData.keys
                            width: Math.min(shortcutRow.implicitWidth + 20, parent.width)
                            height: 30
                            radius: 5
                            color: Theme.controlBackground
                            Accessible.role: Accessible.StaticText
                            Accessible.name: modelData.label + " " + keys
                            RowLayout {
                                id: shortcutRow
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                spacing: 8
                                Components.SelectableText { text: shortcut.modelData.label; color: Theme.textSecondary; font.pixelSize: 12 }
                                Components.SelectableText {
                                    text: shortcut.keys
                                    color: Theme.primaryColor
                                    font.pixelSize: 14
                                    font.weight: Font.DemiBold
                                }
                            }
                        }
                    }
                }
                RowLayout {
                    visible: (manual.article.examples?.length ?? 0) > 0
                    Components.SelectableText { text: qsTrId("text.0952"); color: Theme.textMuted; font.pixelSize: 11 }
                    Components.AppButton { text: "CT"; compact: true; checked: !manual.petExample; onClicked: manual.petExample = false }
                    Components.AppButton { text: "PET"; compact: true; checked: manual.petExample; onClicked: manual.petExample = true }
                }
                ManualScreenshot {
                    Layout.fillWidth: true
                    maximumPreviewHeight: readingArea.height < 620 ? 180 : 240
                    file: manual.article.example
                        ?? ((manual.article.examples?.length ?? 0) > 0 ? manual.article.examples[manual.petExample ? 1 : 0] : "")
                    caption: manual.article.caption ?? qsTrId("text.0952")
                    pageActive: manual.active
                    readingViewport: readingArea
                }
                VoiManualFigure {
                    Layout.fillWidth: true
                    Layout.preferredHeight: visible ? width * 220 / 760 : 0
                    visible: !!manual.article.figure
                    chapter: manual.article.figure ?? ""
                }
                Repeater {
                    id: sectionRepeater
                    model: manual.article.sections ?? []
                    delegate: Rectangle {
                        id: step
                        required property var modelData
                        required property int index
                        objectName: "manualSection-" + index
                        readonly property bool important: modelData.important ?? false
                        Layout.fillWidth: true
                        implicitHeight: sectionContent.implicitHeight + (important ? 20 : 0)
                        color: important ? Theme.warningSurface : "transparent"
                        radius: 5
                        Rectangle {
                            visible: step.important
                            width: 3
                            height: parent.height
                            radius: 1
                            color: Theme.warningColor
                        }
                        ColumnLayout {
                            id: sectionContent
                            x: step.important ? 14 : 0
                            y: step.important ? 10 : 0
                            width: step.width - (step.important ? 28 : 0)
                            spacing: 6
                            Components.SelectableText {
                                objectName: "manualImportantLabel-" + step.index
                                Layout.fillWidth: true
                                visible: step.important
                                text: qsTrId("manual.important")
                                color: Theme.warningColor
                                font.pixelSize: 12
                                font.weight: Font.DemiBold
                            }
                            Components.SelectableText {
                                Layout.fillWidth: true
                                text: step.modelData.title
                                textFormat: TextEdit.PlainText
                                color: Theme.textPrimary
                                font.pixelSize: 16
                                font.weight: Font.DemiBold
                                wrapMode: TextEdit.Wrap
                            }
                            Components.SelectableText {
                                objectName: "manualSectionBody-" + step.index
                                Layout.fillWidth: true
                                text: "<p style=\"margin:0; line-height:145%\">" + step.modelData.bodyHtml + "</p>"
                                textFormat: TextEdit.RichText
                                color: Theme.textSecondary
                                font.pixelSize: 15
                                wrapMode: TextEdit.Wrap
                            }
                            Repeater {
                                model: step.modelData.tutorials ?? []
                                delegate: ManualScreenshot {
                                    id: tutorialShot
                                    required property var modelData
                                    objectName: "manualTutorial-" + modelData.id
                                    Layout.fillWidth: true
                                    Layout.topMargin: 10
                                    maximumPreviewHeight: readingArea.height < 620 ? 180 : 280
                                    file: modelData.file
                                    poster: modelData.poster
                                    caption: modelData.caption
                                    pageActive: manual.active
                                    readingViewport: readingArea
                                    playing: manual.playingTutorialId === modelData.id
                                    onPlayRequested: manual.playingTutorialId = modelData.id
                                    onStopRequested: if (manual.playingTutorialId === modelData.id)
                                        manual.playingTutorialId = ""
                                }
                            }
                        }
                    }
                }
                GridLayout {
                    Layout.fillWidth: true
                    visible: manual.article.cursorLegend ?? false
                    columns: width < 600 ? 2 : 3
                    columnSpacing: 8; rowSpacing: 8
                    Repeater {
                        model: [{key:"segmentation",label:qsTrId("text.0953")}, {key:"voi",label:qsTrId("text.0954")},
                            {key:"pan",label:qsTrId("text.0955")}, {key:"resize",label:qsTrId("text.0956")},
                            {key:"crosshair-move",label:qsTrId("text.0957")}, {key:"crosshair-rotate",label:qsTrId("text.0958")},
                            {key:"window",label:qsTrId("text.0285")}, {key:"zoom",label:qsTrId("text.0033")}, {key:"scroll",label:qsTrId("text.0287")}]
                        delegate: Rectangle {
                            id: legend
                            required property var modelData
                            Layout.fillWidth: true
                            implicitHeight: 50
                            color: Theme.panelBackground
                            radius: 4
                            RowLayout {
                                anchors.fill: parent; anchors.margins: 8
                                ViewportUi.CursorGlyph {
                                    visible: true
                                    Layout.preferredWidth: 40; Layout.preferredHeight: 32; iconName: legend.modelData.key
                                }
                                Components.SelectableText { Layout.fillWidth: true; text: legend.modelData.label; color: Theme.textSecondary; font.pixelSize: 12; wrapMode: TextEdit.Wrap }
                            }
                        }
                    }
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: 8
                    Repeater {
                        model: manual.article.relatedChapters ?? []
                        delegate: Components.AppLinkButton {
                            required property var modelData
                            objectName: "manualRelated-" + modelData.id
                            text: modelData.title + " →"
                            onClicked: manual.controller.selectChapter(modelData.id)
                        }
                    }
                }
            }
        }
    }
}
