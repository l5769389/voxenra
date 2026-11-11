import QtQuick
import QtQuick.Layouts

GridLayout {
    id: root
    default property alias contents: form.data
    property real previewMaximumWidth: 280
    property Component preview
    readonly property bool wide: width >= 720
    columns: wide ? 2 : 1
    columnSpacing: 28
    rowSpacing: 18
    data: [
        ColumnLayout {
            id: form
            objectName: "settingsParameterColumn"
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.preferredWidth: 480
            Layout.alignment: Qt.AlignTop
            spacing: 12
        },
        Loader {
            objectName: "settingsPreviewColumn"
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.preferredWidth: root.wide ? 260 : root.width
            Layout.maximumWidth: root.wide ? root.previewMaximumWidth : root.width
            Layout.alignment: Qt.AlignTop
            sourceComponent: root.preview
        }
    ]
}
