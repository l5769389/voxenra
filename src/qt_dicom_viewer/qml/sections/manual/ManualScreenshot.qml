pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import QtQuick.Controls.Basic as Basic
import "../../components" as Components
import "../../theme"

ColumnLayout {
    id: shot
    required property string file
    property string poster: ""
    property string caption: ""
    property real maximumPreviewHeight: 240
    property bool playing: false
    property bool pageActive: true
    property var readingViewport: null
    signal playRequested()
    signal stopRequested()
    readonly property bool animated: file.toLowerCase().endsWith(".gif")
    readonly property url imageUrl: file ? "../../assets/help/" + file : ""
    readonly property url stillUrl: poster ? "../../assets/help/" + poster : imageUrl
    readonly property bool windowVisible: !Window.window || (Window.window.visibility !== Window.Hidden
        && Window.window.visibility !== Window.Minimized)
    readonly property bool withinViewport: {
        if (!readingViewport) return true
        const scrollY = readingViewport.contentY
        // Track layout positions explicitly: mapToItem alone does not notify
        // this binding when an ancestor moves during a language relayout.
        let top = 0
        for (let item = shot; item && item !== readingViewport.contentItem; item = item.parent)
            top += item.y
        return top + height > scrollY && top < scrollY + readingViewport.height
    }
    readonly property bool playbackAllowed: pageActive && visible && windowVisible
        && (preview.visible || withinViewport)
    onPlaybackAllowedChanged: if (!playbackAllowed) {
        stopRequested()
        preview.close()
    }
    onFileChanged: {
        stopRequested()
        preview.close()
    }
    spacing: 8
    visible: file !== ""
    Basic.Button {
        id: button
        objectName: "manualScreenshotButton"
        Layout.fillWidth: true
        Layout.preferredHeight: example.sourceSize.width > 0
            ? Math.min(shot.maximumPreviewHeight, width * example.sourceSize.height / example.sourceSize.width) : 0
        padding: 0
        hoverEnabled: true
        Accessible.name: I18n.format(qsTrId("manual.enlarge"), {caption: shot.caption})
        onClicked: preview.open()
        HoverHandler { cursorShape: Qt.PointingHandCursor }
        contentItem: Item {
            Image {
                id: example
                objectName: "manualExample"
                anchors.fill: parent
                source: shot.stillUrl
                visible: !inlineAnimation.active
                fillMode: Image.PreserveAspectFit
                smooth: true
                mipmap: true
            }
            Loader {
                id: inlineAnimation
                anchors.fill: parent
                active: shot.animated && shot.playing && shot.playbackAllowed && !preview.visible
                sourceComponent: AnimatedImage {
                    objectName: "manualAnimation"
                    source: inlineAnimation.active ? shot.imageUrl : ""
                    playing: inlineAnimation.active
                    cache: false
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                    onStatusChanged: if (status === AnimatedImage.Error) shot.stopRequested()
                }
            }
        }
        background: Rectangle {
            color: Theme.appBackground
            radius: 4
            border.width: button.hovered || button.visualFocus ? 1 : 0
            border.color: Theme.primaryColor
        }
        Components.AppToolTip { visible: button.hovered; text: qsTrId("text.0960") }
    }
    Components.SelectableText {
        Layout.fillWidth: true
        text: I18n.format(qsTrId("manual.caption"), {caption: shot.caption})
        textFormat: TextEdit.PlainText
        color: Theme.textMuted
        font.pixelSize: 12
        wrapMode: TextEdit.Wrap
    }
    Components.AppButton {
        objectName: "manualTutorialPlay"
        visible: shot.animated
        text: shot.playing ? qsTrId("manual.tutorial.stop") : qsTrId("manual.tutorial.play")
        onClicked: shot.playing ? shot.stopRequested() : shot.playRequested()
    }
    Basic.Dialog {
        id: preview
        objectName: "manualScreenshotPreview"
        parent: Basic.Overlay.overlay
        anchors.centerIn: parent
        popupType: Basic.Popup.Window
        title: qsTrId("text.0962")
        implicitWidth: 1120
        implicitHeight: 800
        width: Math.min(implicitWidth, parent ? parent.width - 32 : implicitWidth)
        height: Math.min(implicitHeight, parent ? parent.height - 32 : implicitHeight)
        padding: 12
        modal: true
        focus: true
        closePolicy: Basic.Popup.CloseOnEscape
        onOpened: original.checked = false
        onClosed: shot.stopRequested()
        background: Rectangle { color: Theme.panelBackgroundStrong }
        header: Item { implicitHeight: 0 }
        contentItem: Basic.ScrollView {
            id: scroll
            implicitWidth: 0
            implicitHeight: 0
            clip: true
            contentWidth: fullCanvas.width
            contentHeight: fullCanvas.height
            Basic.ScrollBar.horizontal: Basic.ScrollBar {
                height: 8
                padding: 1
                contentItem: Rectangle {
                    implicitWidth: 6; implicitHeight: 6
                    radius: 3
                    color: Theme.textSubtle
                }
            }
            Basic.ScrollBar.vertical: Components.AppScrollBar {}
            Item {
                id: fullCanvas
                width: original.checked ? fullImage.sourceSize.width : scroll.availableWidth
                height: original.checked ? fullImage.sourceSize.height : scroll.availableHeight
                Image {
                    id: fullImage
                    objectName: "manualFullScreenshot"
                    anchors.fill: parent
                    source: preview.visible ? shot.stillUrl : ""
                    visible: !fullAnimation.active
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                    mipmap: true
                }
                Loader {
                    id: fullAnimation
                    anchors.fill: parent
                    active: preview.visible && shot.animated && shot.playing && shot.playbackAllowed
                    sourceComponent: AnimatedImage {
                        objectName: "manualFullAnimation"
                        source: fullAnimation.active ? shot.imageUrl : ""
                        playing: fullAnimation.active
                        cache: false
                        fillMode: Image.PreserveAspectFit
                        smooth: true
                        onStatusChanged: if (status === AnimatedImage.Error) shot.stopRequested()
                    }
                }
            }
        }
        footer: RowLayout {
            implicitHeight: Math.max(44, footerCaption.implicitHeight + 16)
            spacing: 12
            Components.SelectableText {
                id: footerCaption
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.leftMargin: 12
                text: shot.caption
                textFormat: TextEdit.PlainText
                color: Theme.textSecondary
                font.pixelSize: 12
                wrapMode: TextEdit.Wrap
            }
            Components.AppButton {
                objectName: "manualPreviewPlay"
                visible: shot.animated
                compact: true
                text: shot.playing ? qsTrId("manual.tutorial.stop") : qsTrId("manual.tutorial.play")
                onClicked: shot.playing ? shot.stopRequested() : shot.playRequested()
            }
            Components.AppButton {
                id: original
                objectName: "manualScreenshotOriginalSize"
                Layout.rightMargin: 12
                compact: true
                checkable: true
                text: checked ? qsTrId("text.0963") : qsTrId("text.0964")
            }
        }
    }
}
