pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../../components" as Components
import "../../theme"

Item {
    id: page
    required property var settingsController
    required property string category
    required property string title
    onCategoryChanged: resetDialog.close()
    function requestReset(section, title) {
        resetDialog.section = section
        resetDialog.sectionTitle = title
        resetDialog.open()
    }
    function resetImpact(section) {
        const summaries = {
            appearance: qsTrId("settings.reset.appearance"), input: qsTrId("settings.reset.input"),
            shortcuts: qsTrId("settings.reset.shortcuts"),
            privacy: qsTrId("settings.reset.privacy"), workspace: qsTrId("settings.reset.workspace"),
            updates: qsTrId("settings.reset.updates"), export: qsTrId("settings.reset.export"),
            colormap: qsTrId("settings.reset.colormap"), crosshair: qsTrId("settings.reset.crosshair"),
            corners: qsTrId("settings.reset.corners"), scale: qsTrId("settings.reset.scale"),
            measurement: qsTrId("settings.reset.measurement"), roi: qsTrId("settings.reset.roi"),
            services: qsTrId("settings.reset.services"), ai: qsTrId("settings.reset.ai")
        }
        return section === "window" ? I18n.format(qsTrId("settings.reset.window"), {
            count: page.settingsController.values.window.custom.length
        }) : summaries[section] ?? ""
    }
    Components.AppDialog {
        id: resetDialog
        objectName: "settingsResetDialog"
        property string section: ""
        property string sectionTitle: ""
        parent: Basic.Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(500, (parent?.width ?? 532) - 32)
        title: I18n.format(qsTrId("settings.reset.title"), {section: sectionTitle})
        contentItem: Text {
            objectName: "settingsResetImpact"
            text: page.resetImpact(resetDialog.section) + "\n\n" + qsTrId("settings.reset.scope")
            textFormat: Text.PlainText
            color: Theme.textSecondary
            font.pixelSize: 13
            wrapMode: Text.Wrap
        }
        footer: Components.AppDialogFooter {
            Components.AppButton {
                objectName: "cancelSettingsReset"
                text: qsTrId("text.0539")
                onClicked: resetDialog.reject()
            }
            Components.AppButton {
                objectName: "confirmSettingsReset"
                text: qsTrId("settings.reset.confirm")
                actionRole: resetDialog.section === "window" ? "danger" : "primary"
                onClicked: {
                    if (page.settingsController.resetSection(resetDialog.section)) resetDialog.accept()
                    else resetDialog.reject()
                }
            }
        }
        onOpened: contentItem.forceActiveFocus()
    }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 10
        RowLayout {
            Layout.fillWidth: true
            Text { Layout.fillWidth: true; text: page.title; color: Theme.textPrimary; font.pixelSize: 18; font.bold: true }
            Text { text: qsTrId("text.0842"); color: Theme.textSubtle; font.pixelSize: 11 }
            Components.AppButton {
                objectName: "resetDisplaySettings"
                text: qsTrId("text.0843"); compact: true; normalColor: "transparent"; baseBorderWidth: 1
                onClicked: page.requestReset(page.category, page.title)
            }
        }
        Item { Layout.fillWidth: true; Layout.preferredHeight: 2 }
        Text {
            objectName: "settingsError"
            Layout.fillWidth: true
            visible: text.length > 0
            text: page.settingsController.message
            color: page.settingsController.messageIsError ? Theme.dangerColor : Theme.textSecondary
            wrapMode: Text.Wrap
        }
        Basic.ScrollView {
            id: scroll
            objectName: "displaySettingsScroll"
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            rightPadding: 12
            clip: true
            Basic.ScrollBar.horizontal.policy: Basic.ScrollBar.AlwaysOff
            Basic.ScrollBar.vertical: Components.AppScrollBar {}
            Loader {
                id: content
                objectName: "settingsCategoryContent"
                width: Math.min(scroll.availableWidth, ["window", "services", "ai"].includes(page.category) ? 760 : 1000)
                sourceComponent: ({input: inputPage, privacy: privacyPage, colormap: colorsPage, window: windowsPage, crosshair: crosshairPage,
                    corners: cornersPage, scale: scalePage, measurement: measurementPage, roi: roiPage,
                    export: exportPage, workspace: workspacePage, appearance: appearancePage, services: servicesPage, ai: aiPage, updates: updatesPage})[page.category]
            }
        }
    }
    Component {
        id: inputPage
        InputSettingsPage {
            settingsController: page.settingsController
            onResetShortcutsRequested: page.requestReset("shortcuts", qsTrId("input.shortcuts"))
        }
    }
    Component { id: privacyPage; PrivacySettingsPage { settingsController: page.settingsController } }
    Component { id: colorsPage; ColorMapsPage { settingsController: page.settingsController } }
    Component {
        id: windowsPage
        WindowTemplatesPage {
            settingsController: page.settingsController
            onRevealEditor: item => {
                const flick = scroll.contentItem
                const top = item.mapToItem(flick.contentItem, 0, 0).y
                flick.contentY = Math.max(0, Math.min(top, flick.contentHeight - flick.height))
            }
        }
    }
    Component { id: crosshairPage; CrosshairSettingsPage { settingsController: page.settingsController } }
    Component { id: cornersPage; CornerSettingsPage { settingsController: page.settingsController } }
    Component { id: scalePage; ScaleSettingsPage { settingsController: page.settingsController } }
    Component { id: measurementPage; MeasurementSettingsPage { settingsController: page.settingsController } }
    Component { id: servicesPage; ServiceToolsSettingsPage { settingsController: page.settingsController } }
    Component { id: aiPage; AiSettingsPage { settingsController: page.settingsController } }
    Component { id: roiPage; RoiSettingsPage { settingsController: page.settingsController } }
    Component { id: exportPage; ExportSettingsPage { settingsController: page.settingsController } }
    Component { id: workspacePage; WorkspaceSettingsPage { settingsController: page.settingsController } }
    Component { id: appearancePage; AppearanceSettingsPage { settingsController: page.settingsController } }
    Component { id: updatesPage; UpdateSettingsPage { settingsController: page.settingsController } }
}
