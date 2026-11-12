pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic as Basic
import "../../../components" as Components
import "../../../theme"
import "../../settings" as Settings

Components.AppDialog {
    id: root
    required property var reportController
    required property var settingsController
    property Item captureItem: null
    property bool qa: false
    property var options: ({})
    property var content: ({})
    property bool allTabs: false
    property bool currentStudy: false
    property var choices: []
    property var selected: []
    property bool useSelection: false
    function refreshChoices() { choices = reportController.availableResults(allTabs, currentStudy); selected = [] }
    readonly property var preview: reportController?.previewController ?? null
    readonly property bool busy: reportController?.busy ?? reportController?.reportBusy ?? false
    parent: Basic.Overlay.overlay
    defaultButton: previewButton
    escapeButton: closeButton
    modal: true
    title: qsTrId("report.configure")
    width: Math.min(980, parent?.width ?? 980)
    height: Math.min(850, parent?.height ?? 850)
    anchors.centerIn: parent
    onOpened: {
        options = Object.assign({}, settingsController.values.report)
        content = ({})
        useSelection = false
        allTabs = false
        currentStudy = false
        preview?.clear()
        if (!qa) refreshChoices()
    }
    onClosed: { reportController?.cancelPreview(); preview?.clear() }
    contentItem: GridLayout {
        columns: root.width < 650 ? 1 : 2
        columnSpacing: 16
        rowSpacing: 12
        Basic.ScrollView {
            id: optionsScroll
            objectName: "reportOptionsScroll"
            visible: root.width >= 650 || !root.preview?.ready
            contentWidth: availableWidth
            Layout.preferredWidth: root.width < 650 ? -1 : 220
            Layout.maximumWidth: root.width < 650 ? Infinity : 220
            Layout.fillWidth: root.width < 650
            Layout.preferredHeight: root.width < 650 ? root.height * .4 : -1
            Layout.fillHeight: root.width >= 650
            clip: true
            ColumnLayout {
                width: optionsScroll.availableWidth
                spacing: 8
                enabled: !root.busy && !root.preview?.ready
                Components.AppComboBox {
                    visible: !root.qa
                    Layout.fillWidth: true
                    model: [qsTrId("report.currentTab"), qsTrId("report.currentStudy"), qsTrId("report.allTabs")]
                    currentIndex: root.currentStudy ? 1 : root.allTabs ? 2 : 0
                    onActivated: { root.currentStudy = currentIndex === 1; root.allTabs = currentIndex > 0; root.refreshChoices() }
                }
                Components.AppCheckBox {
                    visible: !root.qa
                    text: qsTrId("report.selectResults")
                    checked: root.useSelection
                    onToggled: root.useSelection = checked
                }
                Components.AppButton {
                    visible: !root.qa && root.useSelection
                    text: qsTrId("report.refreshResults")
                    onClicked: root.refreshChoices()
                }
                Repeater {
                    model: root.useSelection && !root.qa ? root.choices : []
                    delegate: Components.AppCheckBox {
                        required property var modelData
                        text: modelData.label
                        checked: root.selected.indexOf(modelData.id) >= 0
                        onToggled: root.selected = checked ? root.selected.concat([modelData.id]) : root.selected.filter(id => id !== modelData.id)
                    }
                }
                Settings.ReportSettingsContent {
                    qa: root.qa
                    Layout.fillWidth: true
                    settingsController: root.settingsController
                    options: root.options
                    onEdited: options => root.options = options
                }
                Repeater {
                    model: ["title", "operator", "reviewer"]
                    delegate: Components.AppTextField {
                        required property string modelData
                        Layout.fillWidth: true
                        objectName: "reportContent_" + modelData
                        text: root.content[modelData] ?? ""
                        placeholderText: qsTrId("report." + modelData)
                        Accessible.name: placeholderText
                        maximumLength: 120
                        onTextEdited: { const next = Object.assign({}, root.content); next[modelData] = text; root.content = next }
                    }
                }
                Repeater {
                    model: ["notes", "conclusion"]
                    delegate: Basic.TextArea {
                        required property string modelData
                        Layout.fillWidth: true
                        Layout.minimumHeight: 90
                        objectName: "reportContent_" + modelData
                        text: root.content[modelData] ?? ""
                        placeholderText: qsTrId("report." + modelData)
                        Accessible.name: placeholderText
                        color: Theme.textPrimary
                        placeholderTextColor: Theme.textMuted
                        wrapMode: TextEdit.Wrap
                        background: Rectangle { color: Theme.panelBackgroundStrong; border.color: Theme.borderStrong; radius: 4 }
                        onTextChanged: {
                            if (text === (root.content[modelData] ?? "")) return
                            const next = Object.assign({}, root.content)
                            next[modelData] = text.slice(0, 4000)
                            root.content = next
                        }
                    }
                }
            }
        }
        Basic.ScrollView {
            id: previewScroll
            contentWidth: availableWidth
            Layout.minimumWidth: 100
            Layout.minimumHeight: 100
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            Column {
                width: previewScroll.availableWidth
                spacing: 12
                Repeater {
                    model: root.preview?.pages ?? []
                    delegate: Image {
                        required property string modelData
                        width: parent.width
                        height: width * (sourceSize.height / Math.max(1, sourceSize.width))
                        source: modelData
                        fillMode: Image.PreserveAspectFit
                        cache: false
                    }
                }
                Text {
                    width: parent.width
                    wrapMode: Text.Wrap
                    textFormat: Text.PlainText
                    text: root.preview?.error || root.reportController?.message || root.reportController?.reportMessage || qsTrId("report.previewHint")
                    color: Theme.textSecondary
                }
            }
        }
    }
    footer: Item {
        implicitHeight: footerActions.implicitHeight + 32
        GridLayout {
            id: footerActions
            anchors.fill: parent
            anchors.margins: 16
            columns: root.width < 650 ? 2 : 5
            columnSpacing: 8
            rowSpacing: 8
            Components.AppButton {
                id: previewButton
                objectName: "reportGeneratePreview"
                text: qsTrId("report.preview")
                enabled: !root.busy && (!root.useSelection || root.selected.length > 0)
                onClicked: {
                    if (root.qa) root.reportController.previewReport(root.captureItem, root.options, root.content)
                    else root.reportController.previewReport(root.allTabs, root.options, root.content, root.useSelection ? root.selected : [], root.currentStudy)
                }
            }
            Components.AppButton {
                text: qsTrId("report.edit")
                enabled: root.preview?.ready ?? false
                onClicked: root.preview.clear()
            }
            Item { Layout.fillWidth: true; visible: root.width >= 650 }
            Components.AppButton {
                objectName: "reportSavePdf"
                text: qsTrId("report.savePdf")
                enabled: (root.preview?.ready ?? false) && !root.busy
                onClicked: if (root.preview.save()) root.close()
            }
            Components.AppButton { id: closeButton; objectName: "reportClose"; text: qsTrId("report.close"); onClicked: root.close() }
        }
    }
}
