pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../../components" as Components
import "../../theme"

Rectangle {
    id: page
    objectName: "settingsPage"
    required property var pacsController
    required property var settingsController
    color: Theme.panelBackgroundStrong
    readonly property string selectedCategory: settingsController.activeCategory
    readonly property var categories: [
        {key: "appearance", title: qsTrId("appearance.title"), shortTitle: qsTrId("appearance.navigation"), subtitle: qsTrId("appearance.keywords"), group: qsTrId("text.0814")},
        {key: "workspace", title: qsTrId("text.0622"), subtitle: qsTrId("text.0813")},
        {key: "updates", title: qsTrId("updates.title"), subtitle: qsTrId("updates.enable")},
        {key: "sources", title: qsTrId("text.0815"), subtitle: qsTrId("text.0816"), group: qsTrId("text.0817")},
        {key: "export", title: qsTrId("text.0315"), subtitle: qsTrId("text.0818"), group: qsTrId("text.0819")},
        {key: "colormap", title: qsTrId("text.0309"), subtitle: qsTrId("text.0820"), group: qsTrId("text.0821")},
        {key: "window", title: qsTrId("text.0822"), subtitle: qsTrId("text.0823")},
        {key: "crosshair", title: qsTrId("text.0824"), subtitle: qsTrId("text.0825")},
        {key: "corners", title: qsTrId("text.0826"), subtitle: qsTrId("text.0827")},
        {key: "scale", title: qsTrId("text.0828"), subtitle: qsTrId("text.0829")},
        {key: "measurement", title: qsTrId("text.0830"), subtitle: qsTrId("text.0831"), group: qsTrId("text.0292")},
        {key: "roi", title: qsTrId("text.0832"), subtitle: qsTrId("text.0833")},
        {key: "services", title: qsTrId("settings.servicesTitle"), subtitle: qsTrId("settings.servicesKeywords"), group: qsTrId("settings.toolsGroup")}
    ]
    // Include the appearance/workspace entries when fitting the full navigation.
    readonly property bool compactNavigation: height < 720
    property real dragWidth: -1
    readonly property real navigationLimit: Math.max(156, Math.min(300, width - 360 - 8))
    readonly property real navigationWidth: Math.min(navigationLimit,
        dragWidth >= 0 ? dragWidth : settingsController.values.layout.settingsNavigationWidth)
    RowLayout {
        anchors.fill: parent
        spacing: 0
        Rectangle {
            objectName: "settingsNavigation"
            Layout.minimumWidth: page.navigationWidth
            Layout.preferredWidth: page.navigationWidth
            Layout.maximumWidth: page.navigationWidth
            Layout.fillHeight: true
            color: Theme.panelBackground
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: page.compactNavigation ? 8 : 10
                RowLayout {
                    Layout.fillWidth: true
                    Layout.topMargin: 4
                    spacing: 8
                    ColumnLayout {
                        objectName: "settingsHeading"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        spacing: 3
                        Text { Layout.fillWidth: true; Layout.minimumWidth: 0; elide: Text.ElideRight; Layout.minimumHeight: implicitHeight; text: qsTrId("text.0694"); color: Theme.textPrimary; font.pixelSize: 15; font.bold: true }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 4
                            Text {
                                objectName: "settingsApplicationVersion"
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                Layout.minimumHeight: Math.max(16, implicitHeight)
                                maximumLineCount: 1
                                verticalAlignment: Text.AlignVCenter
                                text: I18n.format(qsTrId("app.version"), {version: page.settingsController.applicationVersion})
                                color: Theme.textMuted
                                font.pixelSize: 11
                                elide: Text.ElideRight
                            }
                            Components.AppButton {
                                objectName: "settingsUpdateBadge"
                                visible: appController.updateController.hasUpdate
                                compact: true
                                minimumButtonWidth: 24
                                Layout.preferredWidth: 24
                                Layout.preferredHeight: 24
                                text: "↑"
                                textColor: Theme.primaryColor
                                normalColor: "transparent"
                                Accessible.name: qsTrId("updates.details")
                                onClicked: appController.updateController.show()
                                Components.AppToolTip { visible: parent.hovered; text: I18n.format(qsTrId("updates.newVersion"), {version: appController.updateController.latestVersion}) }
                            }
                        }
                    }
                    Components.AppButton {
                        id: projectLink
                        objectName: "settingsProjectLink"
                        Layout.alignment: Qt.AlignVCenter
                        Layout.preferredWidth: 40
                        Layout.preferredHeight: 40
                        iconName: "github"
                        iconSize: 28
                        padding: 6
                        minimumButtonWidth: 40
                        textColor: Theme.textMuted
                        normalColor: "transparent"
                        Accessible.name: qsTrId("settings.projectPage")
                        onClicked: Qt.openUrlExternally("https://github.com/l5769389/voxenra")
                        Components.AppToolTip {
                            text: qsTrId("settings.projectPage")
                            visible: projectLink.hovered
                        }
                    }
                }
                Components.AppTextField {
                    id: search
                    objectName: "settingsSearch"
                    Layout.fillWidth: true
                    placeholderText: qsTrId("text.0835")
                }
                Basic.ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    contentWidth: availableWidth
                    clip: true
                    ColumnLayout {
                        width: parent.width
                        spacing: page.compactNavigation ? 0 : 4
                        Repeater {
                            model: page.categories
                            delegate: ColumnLayout {
                                id: entry
                                required property var modelData
                                Layout.fillWidth: true
                                spacing: page.compactNavigation ? 0 : 4
                                visible: !search.text || (modelData.title + modelData.subtitle).toLowerCase().includes(search.text.toLowerCase())
                                Text {
                                    visible: !!entry.modelData.group && !search.text
                                    Layout.topMargin: page.compactNavigation ? 0 : 8
                                    text: entry.modelData.group ?? ""
                                    color: Theme.textSubtle; font.pixelSize: 10
                                }
                                Components.AppButton {
                                    id: category
                                    objectName: "settingsCategory-" + entry.modelData.key
                                    Layout.fillWidth: true
                                    Layout.minimumHeight: page.compactNavigation ? 28 : 34
                                    Layout.preferredHeight: Layout.minimumHeight
                                    Layout.maximumHeight: Layout.minimumHeight
                                    topPadding: 4
                                    bottomPadding: 4
                                    checked: page.selectedCategory === entry.modelData.key
                                    onClicked: page.settingsController.selectCategory(entry.modelData.key)
                                    Accessible.name: entry.modelData.title
                                    contentItem: Text {
                                        text: entry.modelData.shortTitle ?? entry.modelData.title; color: category.checked ? Theme.textPrimary : Theme.textSecondary
                                        elide: Text.ElideRight; maximumLineCount: 1
                                        font.pixelSize: 13; font.weight: category.checked ? Font.DemiBold : Font.Normal
                                        verticalAlignment: Text.AlignVCenter
                                    }
                                    background: Rectangle {
                                        radius: 4
                                        color: category.checked ? Theme.selectionBackground : category.hovered ? Theme.controlHover : "transparent"
                                        border.width: category.visualFocus ? 1 : 0; border.color: Theme.focusBorder
                                        Rectangle { width: 3; height: 16; radius: 1; anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; color: Theme.primaryColor; visible: category.checked }
                                    }
                                }
                            }
                        }
                    }
                }
                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.dividerColor }
                Components.AppButton {
                    objectName: "settingsFeedback"
                    Layout.fillWidth: true
                    text: qsTrId("feedback.title")
                    iconName: "manual"
                    normalColor: "transparent"
                    onClicked: appController.feedbackController.show()
                }
            }
        }
        Components.WidthResizeHandle {
            objectName: "settingsNavigationResizeHandle"
            Layout.preferredWidth: 8
            Layout.fillHeight: true
            currentWidth: page.navigationWidth
            minimumWidth: 156
            maximumWidth: page.navigationLimit
            onWidthDragged: value => page.dragWidth = value
            onWidthCommitted: value => {
                page.settingsController.setValue("layout", "settingsNavigationWidth", Math.round(value))
                page.dragWidth = -1
            }
        }
        Loader {
            Layout.minimumWidth: 360
            Layout.fillWidth: true
            Layout.fillHeight: true
            sourceComponent: page.selectedCategory === "sources" ? sourcesComponent : displayComponent
        }
    }
    Component { id: sourcesComponent; DataSourcesPage { pacsController: page.pacsController } }
    Component {
        id: displayComponent
        DisplaySettingsPage {
            settingsController: page.settingsController
            category: page.selectedCategory
            title: page.categories.find(item => item.key === page.selectedCategory)?.title ?? ""
        }
    }
}
