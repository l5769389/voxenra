pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic as Basic
import "../../../components" as Components
import "../../../theme"

Components.AppDialog {
    id: root
    required property var preview
    objectName: "screenshotPreviewDialog"
    parent: Basic.Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(1100, (parent?.width ?? 1132)-32)
    height: Math.min(850, (parent?.height ?? 882)-32)
    modal: true
    title: qsTrId("screenshot.preview")
    defaultButton: saveButton
    escapeButton: cancelButton
    Connections {
        target: root.preview ?? null
        function onChanged() { if (root.preview.ready && !root.visible) root.open() }
    }
    onClosed: preview?.clear()
    contentItem: ColumnLayout {
        Image {
            id: previewImage
            readonly property bool ready: status === Image.Ready
            objectName: "actualScreenshotPreview"
            Layout.fillWidth: true
            Layout.fillHeight: true
            source: root.preview?.source ?? ""
            fillMode: Image.PreserveAspectFit
            cache: false
        }
        Text { text: root.preview?.dimensions ?? ""; color: Theme.textPrimary }
        Text { Layout.fillWidth: true; text: root.preview?.error ?? ""; visible: text.length>0; color: Theme.dangerColor; wrapMode: Text.Wrap }
    }
    footer: Components.AppDialogFooter {
        Components.AppButton { id: cancelButton; text: qsTrId("text.0539"); onClicked: root.reject() }
        Components.AppButton {
            id: saveButton
            objectName: "saveScreenshotPreview"
            text: qsTrId("screenshot.save")
            enabled: !!root.preview?.ready && previewImage.ready
            onClicked: if (root.preview.save()) root.accept()
        }
    }
}
