pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic as Basic
import "../../components" as Components
import "../../theme"

Item {
    id: emptyState
    objectName: "workspaceEmptyState"

    required property var panelController
    property var pacsController: null
    property var workspaceController: null
    property var documentController: null
    readonly property bool scanning: panelController?.scanning ?? false
    readonly property int seriesCount: panelController?.seriesItems?.length ?? 0
    readonly property bool hasSeries: seriesCount > 0
    readonly property var recentItems: documentController?.recentWorkspaces ?? []
    readonly property bool documentBusy: documentController?.busy ?? false
    onVisibleChanged: { if (visible) documentController?.refreshRecent() }

    component SecondaryAction: Components.AppButton {
        Layout.fillWidth: true
        Layout.preferredHeight: 36
        iconSize: 17
        textColor: Theme.textSecondary
        normalColor: "transparent"
        baseBorderWidth: 1
        baseBorderColor: Theme.borderDefault
    }

    Flickable {
        id: scroller
        objectName: "homeScroll"
        anchors.fill: parent
        clip: true
        contentWidth: width
        contentHeight: Math.max(height, content.implicitHeight + 48)
        boundsBehavior: Flickable.StopAtBounds
        Basic.ScrollBar.vertical: Components.AppScrollBar { }

        ColumnLayout {
            id: content
            x: (scroller.width - width) / 2
            y: Math.max(24, (scroller.height - implicitHeight) / 2)
            width: Math.min(480, Math.max(0, scroller.width - 48))
            spacing: 12

            Rectangle {
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: 64
                Layout.preferredHeight: 64
                radius: 18
                color: Theme.primarySoft
                border.color: Theme.selectionBorder
                Components.AppIcon {
                    objectName: "homeFolderIcon"
                    anchors.centerIn: parent
                    visible: !emptyState.hasSeries
                    iconName: "nav-load-file"
                    iconSize: 30
                    iconColor: Theme.primaryColor
                    opacity: emptyState.scanning ? 0.55 : 1
                }
                Text {
                    anchors.centerIn: parent
                    visible: emptyState.hasSeries
                    text: emptyState.seriesCount
                    color: Theme.primaryHover
                    font.pixelSize: 21
                    font.weight: Font.DemiBold
                }
            }
            Text {
                Layout.fillWidth: true
                Layout.topMargin: 4
                text: emptyState.scanning && !emptyState.hasSeries ? qsTrId("text.0917")
                    : emptyState.hasSeries ? qsTrId("text.0918") : qsTrId("home.start")
                color: Theme.textPrimary
                font.pixelSize: 22
                font.weight: Font.DemiBold
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
            }
            Text {
                Layout.fillWidth: true
                text: emptyState.scanning && !emptyState.hasSeries ? qsTrId("text.0920")
                    : emptyState.hasSeries ? I18n.format(qsTrId("workspace.seriesFound"), {count: emptyState.seriesCount})
                    : emptyState.pacsController?.localEnabled === false ? qsTrId("text.0924") : qsTrId("home.dropHint")
                color: Theme.textMuted
                font.pixelSize: 13
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
            }
            Components.AppButton {
                objectName: "homeOpenImport"
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: 8
                Layout.preferredWidth: Math.min(180, content.width)
                visible: !emptyState.pacsController || emptyState.pacsController.localEnabled
                enabled: !emptyState.documentBusy
                text: emptyState.scanning ? qsTrId("text.0620") : qsTrId("home.openImages")
                iconName: "nav-load-file"
                iconSize: 18
                actionRole: "primary"
                onClicked: emptyState.panelController.openImportDialog()
            }
            GridLayout {
                id: secondaryActions
                objectName: "homeSecondaryActions"
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: 8
                readonly property real rowWidth: quickStart.implicitWidth
                    + (openWorkspace.visible ? openWorkspace.implicitWidth + columnSpacing : 0)
                    + (openPacs.visible ? openPacs.implicitWidth + columnSpacing : 0)
                Layout.preferredWidth: Math.min(content.width, rowWidth)
                columns: content.width >= rowWidth ? 3 : 1
                columnSpacing: 8
                rowSpacing: 8
                SecondaryAction {
                    id: quickStart
                    objectName: "homeQuickStart"
                    enabled: !emptyState.documentBusy
                    text: qsTrId("home.quickStart")
                    iconName: "manual"
                    onClicked: emptyState.workspaceController?.openManual("quick-start")
                }
                SecondaryAction {
                    id: openWorkspace
                    objectName: "homeOpenWorkspace"
                    visible: !!emptyState.documentController
                    enabled: !emptyState.documentBusy && !emptyState.scanning
                    text: qsTrId("home.openWorkspace")
                    iconName: "workspace"
                    onClicked: emptyState.documentController.open()
                }
                SecondaryAction {
                    id: openPacs
                    objectName: "homeOpenPacs"
                    visible: emptyState.pacsController?.pacsEnabled ?? false
                    enabled: !emptyState.documentBusy
                    text: qsTrId("home.importPacs")
                    iconName: "nav-pacs"
                    onClicked: emptyState.workspaceController.openPacs()
                }
            }
            ColumnLayout {
                objectName: "homeRecentSection"
                Layout.fillWidth: true
                Layout.topMargin: 18
                spacing: 4
                visible: emptyState.recentItems.length > 0
                Text {
                    Layout.fillWidth: true
                    Layout.bottomMargin: 6
                    text: qsTrId("home.continue")
                    color: Theme.textSecondary
                    font.pixelSize: 14
                    font.weight: Font.DemiBold
                }
                Repeater {
                    model: emptyState.recentItems
                    delegate: RowLayout {
                        id: recentRow
                        required property var modelData
                        required property int index
                        Layout.fillWidth: true
                        spacing: 4
                        Components.AppButton {
                            id: openRecent
                            objectName: "homeRecentOpen-" + recentRow.index
                            Layout.fillWidth: true
                            Layout.preferredHeight: 52
                            enabled: !emptyState.documentBusy && !emptyState.scanning
                            normalColor: "transparent"
                            Accessible.name: recentRow.modelData.name
                            Accessible.description: recentRow.modelData.missing ? qsTrId("home.missing") : recentRow.modelData.date
                            contentItem: RowLayout {
                                spacing: 12
                                Components.AppIcon {
                                    iconName: "workspace"
                                    iconSize: 20
                                    iconColor: Theme.textSecondary
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2
                                    Text {
                                        objectName: "homeRecentName-" + recentRow.index
                                        Layout.fillWidth: true
                                        text: recentRow.modelData.name
                                        textFormat: Text.PlainText
                                        font.pixelSize: 14
                                        color: recentRow.modelData.missing ? Theme.textMuted : Theme.textPrimary
                                        elide: Text.ElideRight
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: recentRow.modelData.missing ? qsTrId("home.missing") : recentRow.modelData.date
                                        font.pixelSize: 12
                                        color: Theme.textMuted
                                    }
                                }
                            }
                            Components.AppToolTip { visible: openRecent.hovered; text: recentRow.modelData.path }
                            onClicked: emptyState.documentController.openRecent(recentRow.modelData.path)
                        }
                        Components.AppButton {
                            objectName: "homeRecentRemove-" + recentRow.index
                            Layout.preferredWidth: 30
                            Layout.preferredHeight: 30
                            compact: true
                            iconName: "close"
                            iconSize: 14
                            normalColor: "transparent"
                            Accessible.name: qsTrId("home.removeRecent")
                            Components.AppToolTip { visible: parent.hovered; text: qsTrId("home.removeRecent") }
                            onClicked: emptyState.documentController.removeRecent(recentRow.modelData.path)
                        }
                    }
                }
            }
        }
    }
}
