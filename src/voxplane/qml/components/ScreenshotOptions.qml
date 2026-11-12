pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../theme"
ColumnLayout {
    id: root
    property var options: ({})
    property bool showAnonymous: true
    property bool customSize: false
    signal edited(var options)
    function update(key, value) { const copy = Object.assign({}, options); copy[key] = value; edited(copy) }
    function setSize(index) {
        customSize = index === 4
        const copy = Object.assign({}, options)
        copy.size = index === 0 ? "current" : "longEdge"
        if (index > 0 && index < 4) copy.longEdge = [1920, 2560, 3840][index - 1]
        edited(copy)
    }
    readonly property int sizeIndex: options.size === "current" ? 0 : customSize ? 4 : [1920,2560,3840].includes(options.longEdge) ? [1920,2560,3840].indexOf(options.longEdge)+1 : 4
    spacing: 10
    Repeater {
        model: ["scope", "format"]
        delegate: ColumnLayout {
            id: row
            required property string modelData
            readonly property var values: modelData === "scope" ? ["viewport", "tab"] : ["png", "jpeg"]
            Layout.fillWidth: true
            spacing: 4
            Text { text: qsTrId("screenshot." + row.modelData); color: Theme.textSecondary }
            AppComboBox {
                Layout.fillWidth: true
                objectName: "screenshot-option-" + row.modelData
                model: row.values.map(v => qsTrId("screenshot." + v))
                currentIndex: Math.max(0, row.values.indexOf(root.options[row.modelData]))
                onActivated: root.update(row.modelData, row.values[currentIndex])
            }
        }
    }
    ColumnLayout {
        Layout.fillWidth: true
        spacing: 4
        Text { text: qsTrId("screenshot.size"); color: Theme.textSecondary }
        AppComboBox {
            Layout.fillWidth: true
            objectName: "screenshot-output-size"
            model: [qsTrId("screenshot.current"),qsTrId("screenshot.hd"),qsTrId("screenshot.2k"),qsTrId("screenshot.4k"),qsTrId("screenshot.custom")]
            currentIndex: root.sizeIndex
            onActivated: index => root.setSize(index)
        }
        Text {
            Layout.fillWidth: true
            text: qsTrId("screenshot.sizeHint")
            wrapMode: Text.Wrap
            color: Theme.textMuted
            font.pixelSize: 11
        }
    }
    Repeater {
        model: ["longEdge", "jpegQuality", "filenamePrefix"]
        delegate: ColumnLayout {
            id: fieldRow
            required property string modelData
            Layout.fillWidth: true
            spacing: 4
            visible: modelData === "filenamePrefix" || (modelData === "longEdge" ? root.sizeIndex === 4 : root.options.format === "jpeg")
            Text { text: qsTrId("screenshot." + fieldRow.modelData); color: Theme.textSecondary }
            AppTextField {
                Layout.fillWidth: true
                objectName: "screenshot-option-" + fieldRow.modelData
                text: String(root.options[fieldRow.modelData] ?? "")
                maximumLength: fieldRow.modelData === "filenamePrefix" ? 80 : 4
                onEditingFinished: {
                    root.update(fieldRow.modelData, fieldRow.modelData === "filenamePrefix" ? text : Number(text))
                    text = Qt.binding(() => String(root.options[fieldRow.modelData] ?? ""))
                }
            }
        }
    }
    Text { text: qsTrId("screenshot.overlays"); color: Theme.textPrimary; font.bold: true; Layout.topMargin: 4 }
    Repeater {
        model: ["measurements", "directions", "scale", "parameters"]
        delegate: AppCheckBox {
            required property string modelData
            objectName: modelData === "anonymous" ? "viewportExportAnonymous" : "screenshot-" + modelData
            Layout.fillWidth: true
            text: qsTrId("screenshot." + modelData)
            checked: root.options[modelData] ?? (modelData !== "revealAfter")
            onToggled: root.update(modelData, checked)
        }
    }
    Text { text: qsTrId("screenshot.privacyAndSave"); color: Theme.textPrimary; font.bold: true; Layout.topMargin: 4 }
    AppCheckBox {
        objectName: "viewportExportAnonymous"
        Layout.fillWidth: true
        visible: root.showAnonymous
        text: qsTrId("screenshot.anonymous")
        checked: root.options.anonymous ?? true
        onToggled: root.update("anonymous", checked)
    }
    Text {
        Layout.fillWidth: true
        visible: root.options.anonymous ?? true
        text: qsTrId("screenshot.anonymousHint")
        wrapMode: Text.Wrap
        color: Theme.textMuted
        font.pixelSize: 12
    }
    AppCheckBox {
        objectName: "screenshot-revealAfter"
        Layout.fillWidth: true
        text: qsTrId("screenshot.revealAfter")
        checked: root.options.revealAfter ?? false
        onToggled: root.update("revealAfter", checked)
    }

}
