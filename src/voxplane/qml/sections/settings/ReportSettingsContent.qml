pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../components" as Components
import "../../theme"

ColumnLayout {
    id: root
    required property var settingsController
    property bool qa: false
    property var options: ({})
    signal edited(var options)
    function update(key, value) { const next = Object.assign({}, options); next[key] = value; edited(next) }
    spacing: 8
    Repeater {
        model: [ {key:"orientation", label:"report.orientation", choices:["report.portrait", "report.landscape"], values:["portrait", "landscape"]},
                 {key:"fontSize", label:"report.fontSize", choices:["report.standard", "report.large"], values:["standard", "large"]},
                 {key:"tableDetail", label:"report.tableDetail", choices:["report.summary", "report.detailed"], values:["summary", "detailed"]},
                 {key:"imageColumns", label:"report.imageColumns", choices:["report.oneColumn", "report.twoColumns"], values:[1, 2]} ]
        delegate: ColumnLayout {
            required property var modelData
            visible: !root.qa || modelData.key !== "imageColumns"
            Layout.fillWidth: true
            Text { text: qsTrId(parent.modelData.label); color: Theme.textSecondary }
            Components.AppComboBox {
                Layout.fillWidth: true
                objectName: "reportOption_" + parent.modelData.key
                model: parent.modelData.choices.map(key => qsTrId(key))
                currentIndex: Math.max(0, parent.modelData.values.indexOf(root.options[parent.modelData.key]))
                onActivated: root.update(parent.modelData.key, parent.modelData.values[currentIndex])
            }
        }
    }
    Repeater {
        model: ["organization", "department", "softwareName"]
        delegate: ColumnLayout {
            id: labelField
            required property string modelData
            Layout.fillWidth: true
            spacing: 4
            Text { text: qsTrId("report." + labelField.modelData); color: Theme.textSecondary }
            Components.AppTextField {
                Layout.fillWidth: true
                objectName: "reportOption_" + labelField.modelData
                text: root.options[labelField.modelData] ?? ""
                placeholderText: qsTrId("report.optional")
                Accessible.name: qsTrId("report." + labelField.modelData)
                maximumLength: labelField.modelData === "softwareName" ? 80 : 120
                onEditingFinished: root.update(labelField.modelData, text)
            }
        }
    }

    Repeater {
        model: ["pageNumbers", "anonymous", "includeImages"]
        delegate: Components.AppCheckBox {
            required property string modelData
            Layout.fillWidth: true
            objectName: "reportOption_" + modelData
            text: qsTrId("report." + modelData)
            checked: root.options[modelData] ?? true
            onToggled: root.update(modelData, checked)
        }
    }
    ExportPresetPicker {
        Layout.fillWidth: true
        settingsController: root.settingsController
        kind: "report"
        options: root.options
        onSelected: options => root.edited(options)
    }
}
