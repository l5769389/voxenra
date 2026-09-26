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
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 10
        RowLayout {
            Layout.fillWidth: true
            Text { Layout.fillWidth: true; text: page.title; color: Theme.textPrimary; font.pixelSize: 18; font.bold: true }
            Text { text: qsTrId("text.0842"); color: Theme.textSubtle; font.pixelSize: 11 }
            Components.AppButton { objectName: "resetDisplaySettings"; text: qsTrId("text.0843"); compact: true; normalColor: "transparent"; baseBorderWidth: 1; onClicked: page.settingsController.resetSection(page.category) }
        }
        Item { Layout.fillWidth: true; Layout.preferredHeight: 2 }
        Text {
            objectName: "settingsError"
            Layout.fillWidth: true
            visible: text.length > 0
            text: page.settingsController.message
            color: Theme.dangerColor
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
                width: Math.min(scroll.availableWidth, ["window", "services"].includes(page.category) ? 760 : 1000)
                sourceComponent: ({colormap: colorsPage, window: windowsPage, crosshair: crosshairPage,
                    corners: cornersPage, scale: scalePage, measurement: measurementPage, roi: roiPage,
                    export: exportPage, workspace: workspacePage, appearance: appearancePage, services: servicesPage, updates: updatesPage})[page.category]
            }
        }
    }
    Component { id: colorsPage; ColorMapsPage { settingsController: page.settingsController } }
    Component { id: windowsPage; WindowTemplatesPage { settingsController: page.settingsController } }
    Component { id: crosshairPage; CrosshairSettingsPage { settingsController: page.settingsController } }
    Component { id: cornersPage; CornerSettingsPage { settingsController: page.settingsController } }
    Component { id: scalePage; ScaleSettingsPage { settingsController: page.settingsController } }
    Component { id: measurementPage; MeasurementSettingsPage { settingsController: page.settingsController } }
    Component { id: servicesPage; ServiceToolsSettingsPage { settingsController: page.settingsController } }
    Component { id: roiPage; RoiSettingsPage { settingsController: page.settingsController } }
    Component { id: exportPage; ExportSettingsPage { settingsController: page.settingsController } }
    Component { id: workspacePage; WorkspaceSettingsPage { settingsController: page.settingsController } }
    Component { id: appearancePage; AppearanceSettingsPage { settingsController: page.settingsController } }
    Component { id: updatesPage; UpdateSettingsPage { settingsController: page.settingsController } }
}
