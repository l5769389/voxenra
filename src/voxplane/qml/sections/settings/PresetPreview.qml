pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import QtQuick.Controls.Basic as Basic
import "../../components" as Components
import "../../theme"

Rectangle {
    id: root
    required property var settingsController
    required property string kind
    readonly property var controller: settingsController.createPresetPreview(root, kind)
    property int pageIndex: 0
    readonly property bool ready: previewImage.status === Image.Ready
    readonly property int contentMargin: 8
    readonly property real imageRatio: previewImage.sourceSize.width > 0 ? previewImage.sourceSize.height / previewImage.sourceSize.width : .6
    implicitHeight: kind === "report" ? Math.max(360, Math.min(860, (Window.window?.height ?? 900)-300))
        : Math.max(0, width - 2 * contentMargin) * imageRatio
          + previewHeader.implicitHeight + previewCaption.implicitHeight + previewHint.implicitHeight + 24 + 2 * contentMargin
    color: Theme.panelBackgroundStrong
    border.color: Theme.borderStrong
    radius: 8
    objectName: "presetPreview-" + kind
    Components.AppDialog {
        id: enlarged
        objectName: "presetPreviewDialog-" + root.kind
        parent: Basic.Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(1600, (parent?.width ?? 1600)-32)
        height: (parent?.height ?? 900)-32
        title: qsTrId("presetPreview.title")
        modal: true
        defaultButton: closePreview
        escapeButton: closePreview
        contentItem: Basic.ScrollView {
            id: enlargedScroll
            contentWidth: availableWidth
            contentHeight: enlargedImage.height
            clip: true
            Basic.ScrollBar.horizontal.policy: Basic.ScrollBar.AlwaysOff
            Image {
                id: enlargedImage
                width: enlargedScroll.availableWidth
                height: root.kind === "report" ? width * root.imageRatio : enlargedScroll.availableHeight
                source: root.controller.pages[root.pageIndex] ?? ""
                fillMode: Image.PreserveAspectFit
                cache: false
            }
        }
        footer: RowLayout {
            Components.AppButton { text: "‹"; Accessible.name: qsTrId("presetPreview.previous"); enabled: root.pageIndex > 0; onClicked: root.pageIndex-- }
            Text { text: (root.pageIndex+1) + " / " + root.controller.pages.length; color: Theme.textPrimary }
            Components.AppButton { text: "›"; Accessible.name: qsTrId("presetPreview.next"); enabled: root.pageIndex+1 < root.controller.pages.length; onClicked: root.pageIndex++ }
            Item { Layout.fillWidth: true }
            Components.AppButton { id: closePreview; text: qsTrId("report.close"); onClicked: enlarged.close() }
        }
    }
    Connections {
        target: root.controller
        function onChanged() { root.pageIndex = Math.min(root.pageIndex, Math.max(0, root.controller.pages.length-1)) }
    }
    onPageIndexChanged: {
        previewScroll.contentItem.contentY = 0
        enlargedScroll.contentItem.contentY = 0
    }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: root.contentMargin
        spacing: 8
        RowLayout {
            id: previewHeader
            Layout.fillWidth: true
            Text { Layout.fillWidth: true; text: qsTrId("presetPreview.title"); color: Theme.textPrimary; font.bold: true }
            Components.AppButton {
                objectName: "presetPreviewEnlarge-" + root.kind
                text: qsTrId("presetPreview.enlarge")
                enabled: root.ready
                compact: true
                onClicked: enlarged.open()
            }
            Components.AppComboBox {
                visible: root.kind === "initialDisplay"
                Layout.preferredWidth: 90
                model: ["CT", "MR"]
                onActivated: root.controller.setModality(currentText)
            }
        }
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Basic.ScrollView {
                id: previewScroll
                objectName: "presetPreviewScroll-" + root.kind
                anchors.fill: parent
                contentWidth: availableWidth
                contentHeight: previewImage.height
                clip: true
                Basic.ScrollBar.horizontal.policy: Basic.ScrollBar.AlwaysOff
                Image {
                    id: previewImage
                    objectName: "presetPreviewImage-" + root.kind
                    width: previewScroll.availableWidth
                    height: root.kind === "report" ? width * root.imageRatio : previewScroll.availableHeight
                    source: root.controller.pages[root.pageIndex] ?? ""
                    fillMode: Image.PreserveAspectFit
                    cache: false
                }
            }
            Text {
                anchors.centerIn: parent
                width: parent.width
                text: root.controller.error
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                color: Theme.textSecondary
            }
        }
        RowLayout {
            visible: root.controller.pages.length > 1
            Layout.alignment: Qt.AlignHCenter
            Components.AppButton { text: "‹"; Accessible.name: qsTrId("presetPreview.previous"); enabled: root.pageIndex > 0; onClicked: root.pageIndex-- }
            Text { text: (root.pageIndex+1) + " / " + root.controller.pages.length; color: Theme.textPrimary }
            Components.AppButton { text: "›"; Accessible.name: qsTrId("presetPreview.next"); enabled: root.pageIndex+1 < root.controller.pages.length; onClicked: root.pageIndex++ }
        }
        Text {
            id: previewCaption
            Layout.fillWidth: true
            text: root.controller.caption
            textFormat: Text.PlainText
            color: Theme.textSecondary
            wrapMode: Text.WrapAnywhere
        }
        Text {
            id: previewHint
            Layout.fillWidth: true
            text: qsTrId(root.kind === "report" ? "presetPreview.reportHint" : root.kind === "initialDisplay" ? "initialDisplay.previewHint" : "presetPreview.imageHint")
            color: Theme.textMuted
            font.pixelSize: 11
            wrapMode: Text.Wrap
        }
    }
}
