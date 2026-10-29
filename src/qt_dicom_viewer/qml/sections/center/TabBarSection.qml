pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../../theme"
import "../../components" as Components

Basic.TabBar {
    id: workspaceTabs

    required property var workspaceController
    readonly property var windowManager: workspaceController.windowManager ?? null
    property real dropPosition: -1
    readonly property int dropIndex: insertionIndex(dropPosition + (contentItem.contentX ?? 0) - leftPadding)

    function typeLabel(type) {
        switch (String(type).toLowerCase()) {
        case "settings": case "manual": return ""
        case "petctfusion": return "PET/CT"
        case "compare2d": return qsTrId("tabs.type.compare2d")
        case "comparempr": return qsTrId("tabs.type.comparempr")
        case "montage": return qsTrId("tabs.type.montage")
        case "tag": return qsTrId("tabs.type.tag")
        default: return String(type).toUpperCase()
        }
    }

    function widthForTab(tab) {
        return ["settings", "manual"].includes(tab.tabType) ? Math.min(160, tabWidth) : tabWidth
    }

    function insertionOffset(index) {
        let offset = 0
        for (let i = 0; i < index; ++i)
            offset += widthForTab(workspaceController.tabs[i]) + spacing
        return offset
    }

    function insertionIndex(position) {
        let offset = 0
        for (let i = 0; i < tabCount; ++i) {
            const width = widthForTab(workspaceController.tabs[i])
            if (position < offset + width / 2)
                return i
            offset += width + spacing
        }
        return tabCount
    }
    function revealActiveTab() {
        if (dropPosition >= 0 || windowManager?.dragging) return
        const index = workspaceController.tabs.findIndex(tab => tab.tabId === workspaceController.activeTabId)
        if (index < 0 || !contentItem) return
        currentIndex = index
        contentItem.positionViewAtIndex(index, ListView.Contain)
    }

    // Defer until the side panels and mixed-width delegates have settled.
    Timer {
        id: revealTimer
        interval: 0
        onTriggered: workspaceTabs.revealActiveTab()
    }
    onWidthChanged: revealTimer.restart()
    onTabCountChanged: revealTimer.restart()
    Connections {
        target: workspaceTabs.workspaceController
        function onActiveTabChanged() { revealTimer.restart() }
    }
    Connections {
        target: workspaceTabs.contentItem
        function onWidthChanged() { revealTimer.restart() }
        function onContentWidthChanged() { revealTimer.restart() }
    }
    clip: true
    Component.onCompleted: {
        windowManager?.registerTabBar(workspaceController.windowId, workspaceTabs)
        revealTimer.restart()
    }
    readonly property int tabCount:
        workspaceTabs.workspaceController.tabs.length
    readonly property real tabWidth: Math.min(
        280,
        Math.max(
            224,
            (workspaceTabs.width - 8
                - Math.max(0, workspaceTabs.tabCount - 1)
                    * workspaceTabs.spacing)
                / Math.max(1, workspaceTabs.tabCount)
        )
    )
    spacing: 3
    leftPadding: 6

    Timer {
        interval: 16
        repeat: true
        running: workspaceTabs.dropPosition >= 0
            && (workspaceTabs.dropPosition < 28 || workspaceTabs.dropPosition > workspaceTabs.width - 28)
        onTriggered: {
            const list = workspaceTabs.contentItem
            const direction = workspaceTabs.dropPosition < 28 ? -1 : 1
            list.contentX = Math.max(0, Math.min(Math.max(0, list.contentWidth - list.width), list.contentX + direction * 9))
        }
    }

    Rectangle {
        z: 20
        visible: workspaceTabs.dropPosition >= 0
        x: Math.max(0, Math.min(workspaceTabs.width - width,
            workspaceTabs.leftPadding + workspaceTabs.insertionOffset(workspaceTabs.dropIndex)
                - (workspaceTabs.contentItem.contentX ?? 0)))
        y: 2
        width: 2
        height: workspaceTabs.height - 4
        color: Theme.primaryColor
    }

    component TabMenuItem: Basic.MenuItem {
        id: menuItem
        required property string iconName
        implicitHeight: 34
        contentItem: RowLayout {
            spacing: 10
            Components.AppIcon {
                objectName: menuItem.objectName + "-icon"
                iconName: menuItem.iconName
                iconSize: 18
                iconColor: menuItem.enabled ? Theme.iconDefault : Theme.iconDisabled
                Layout.alignment: Qt.AlignVCenter
            }
            Text {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: menuItem.text
                color: !menuItem.enabled ? Theme.textDisabled : Theme.textPrimary
                font.pixelSize: 13
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }
        }
        background: Rectangle {
            radius: 4
            color: menuItem.highlighted && menuItem.enabled ? Theme.controlHover : "transparent"
        }
    }

    Basic.Menu {
        id: tabMenu
        objectName: "tabContextMenu"
        parent: Basic.Overlay.overlay
        property string tabId: ""
        readonly property int tabIndex: workspaceTabs.workspaceController.tabs.findIndex(tab => tab.tabId === tabId)
        width: 238
        padding: 5
        popupType: Basic.Popup.Window
        modal: false
        focus: true
        closePolicy: Basic.Popup.CloseOnEscape | Basic.Popup.CloseOnPressOutside
        function openFor(id, point) {
            tabId = id
            popup(Math.max(0, Math.min(point.x, parent.width - width)),
                  Math.max(0, Math.min(point.y, parent.height - implicitHeight)))
        }
        background: Rectangle {
            color: Theme.panelBackground
            radius: 7
            border.color: Theme.controlBorder
        }
        TabMenuItem {
            objectName: "tabMenu-detach"
            iconName: "tab-detach"
            text: qsTrId("tabs.detach")
            visible: workspaceTabs.workspaceController.detached !== true
            height: visible ? implicitHeight : 0
            enabled: visible && !!workspaceTabs.windowManager && workspaceTabs.windowManager.canMoveTab(tabMenu.tabId)
            onTriggered: workspaceTabs.windowManager.detachTab(tabMenu.tabId)
        }
        TabMenuItem {
            objectName: "tabMenu-main"
            iconName: "tab-return"
            text: qsTrId("tabs.moveMain")
            visible: workspaceTabs.workspaceController.detached === true
            height: visible ? implicitHeight : 0
            enabled: visible && workspaceTabs.windowManager.canMoveTab(tabMenu.tabId)
            onTriggered: workspaceTabs.windowManager.moveToMain(tabMenu.tabId)
        }
        Basic.MenuSeparator { contentItem: Rectangle { implicitHeight: 1; color: Theme.borderSubtle } }
        TabMenuItem {
            objectName: "tabMenu-close"
            iconName: "close"
            text: qsTrId("tabs.closeCurrent")
            enabled: tabMenu.tabIndex >= 0
            onTriggered: workspaceTabs.workspaceController.closeTab(tabMenu.tabId)
        }
        TabMenuItem {
            objectName: "tabMenu-others"
            iconName: "tab-close-others"
            text: qsTrId("tabs.closeOthers")
            enabled: tabMenu.tabIndex >= 0 && workspaceTabs.tabCount > 1 && !!workspaceTabs.windowManager
            onTriggered: workspaceTabs.workspaceController.closeTabs(tabMenu.tabId, "others")
        }
        TabMenuItem {
            objectName: "tabMenu-right"
            iconName: "tab-close-right"
            text: qsTrId("tabs.closeRight")
            enabled: tabMenu.tabIndex >= 0 && tabMenu.tabIndex < workspaceTabs.tabCount - 1 && !!workspaceTabs.windowManager
            onTriggered: workspaceTabs.workspaceController.closeTabs(tabMenu.tabId, "right")
        }
        TabMenuItem {
            objectName: "tabMenu-all"
            iconName: "tab-close-all"
            text: qsTrId("tabs.closeAll")
            enabled: workspaceTabs.tabCount > 0 && !!workspaceTabs.windowManager
            onTriggered: workspaceTabs.workspaceController.closeTabs(tabMenu.tabId, "all")
        }
    }

    background: Rectangle {
        // 与下方留白使用同一工作区底色，避免色阶交界看起来像横向边框。
        color: Theme.workspaceBackground
    }

    Repeater {
        model: workspaceTabs.workspaceController.tabs

        delegate: Basic.TabButton {
            required property var modelData

            id: tabButton
            objectName: "workspaceTab-" + tabButton.modelData.tabId
            Accessible.name: String(tabButton.modelData.tabType).toUpperCase() + " · " + tabButton.modelData.tabLabel
            Accessible.description: tabButton.modelData.tabTooltip ?? tabButton.modelData.tabLabel
            Accessible.selected: checked
            Accessible.onPressAction: tabButton.click()
            width: workspaceTabs.widthForTab(modelData)
            implicitWidth: workspaceTabs.widthForTab(modelData)
            leftPadding: 10
            rightPadding: 6
            topPadding: 3
            bottomPadding: 3
            checked: tabButton.modelData.tabId
                === workspaceTabs.workspaceController.activeTabId

            HoverHandler { id: tabHover }
            Basic.ToolTip {
                id: identityTooltip
                objectName: "tabTooltip-" + tabButton.modelData.tabId
                visible: tabHover.hovered && !tabDragArea.pressed && !closeButton.hovered
                    && (descriptionLabel.truncated || patientLabel.truncated
                        || (patientLabel.text !== "" && !patientLabel.visible) || contextLabel.truncated)
                delay: 550
                text: tabButton.modelData.tabTooltip ?? tabButton.modelData.tabLabel
                width: Math.min(560, Math.max(240, workspaceTabs.width - 24))
                contentItem: Text {
                    text: identityTooltip.text
                    textFormat: Text.PlainText
                    color: Theme.textPrimary
                    font.pixelSize: 12
                    wrapMode: Text.Wrap
                }
                background: Rectangle {
                    radius: 5
                    color: Theme.panelBackground
                    border.color: Theme.controlBorder
                }
            }

            onClicked: {
                workspaceTabs.workspaceController.activateTabId(
                    tabButton.modelData.tabId
                )
            }
            MouseArea {
                id: tabDragArea
                objectName: "tabDrag-" + tabButton.modelData.tabId
                anchors.fill: parent
                anchors.rightMargin: 32
                acceptedButtons: Qt.LeftButton
                preventStealing: true
                cursorShape: pressed ? Qt.ClosedHandCursor : Qt.PointingHandCursor
                property bool dragConsumed: false
                onPressed: mouse => {
                    dragConsumed = false
                    const point = mapToGlobal(mouse.x, mouse.y)
                    workspaceTabs.windowManager?.beginDrag(workspaceTabs.workspaceController.windowId,
                        tabButton.modelData.tabId, point.x, point.y)
                }
                onPositionChanged: mouse => {
                    if (!pressed) return
                    const point = mapToGlobal(mouse.x, mouse.y)
                    workspaceTabs.windowManager?.updateDrag(point.x, point.y)
                    dragConsumed = dragConsumed || (workspaceTabs.windowManager?.dragging ?? false)
                }
                onReleased: mouse => {
                    const point = mapToGlobal(mouse.x, mouse.y)
                    const id = tabButton.modelData.tabId
                    const consumed = dragConsumed
                    const manager = workspaceTabs.windowManager
                    const controller = workspaceTabs.workspaceController
                    // Moving the model destroys this delegate; finish after the pointer handler returns.
                    Qt.callLater(() => {
                        manager?.finishDrag(point.x, point.y)
                        if (!consumed) controller.activateTabId(id)
                    })
                }
                onCanceled: workspaceTabs.windowManager?.cancelDrag()
            }
            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.RightButton | Qt.MiddleButton
                onClicked: mouse => {
                    if (mouse.button === Qt.RightButton)
                        tabMenu.openFor(tabButton.modelData.tabId, mapToItem(tabMenu.parent, mouse.x, mouse.y))
                    else workspaceTabs.workspaceController.closeTab(tabButton.modelData.tabId)
                }
            }
            contentItem: RowLayout {
                id: tabContent
                spacing: 7

                Basic.BusyIndicator {
                    objectName: "tabLoading-" + tabButton.modelData.tabId
                    Layout.preferredWidth: 14
                    Layout.preferredHeight: 14
                    visible: workspaceTabs.workspaceController.loadingStates[tabButton.modelData.tabId] === "loading"
                    running: visible
                }

                // 视图类型先作为上下文标识，再显示序列名称。
                Rectangle {
                    Layout.preferredWidth: Math.max(
                        30,
                        tabTypeLabel.implicitWidth + 12
                    )
                    Layout.preferredHeight: 22
                    radius: 5
                    color: tabButton.checked
                        ? Theme.selectionBackground
                        : Theme.secondarySoft
                    border.color: tabButton.checked
                        ? "transparent"
                        : "transparent"
                    border.width: 0

                    Components.AppIcon {
                        anchors.centerIn: parent
                        visible: ["settings", "manual"].includes(String(tabButton.modelData.tabType).toLowerCase())
                        iconName: String(tabButton.modelData.tabType).toLowerCase() === "manual" ? "manual" : "settings"
                        iconSize: 14
                        iconColor: tabButton.checked ? Theme.primaryColor : Theme.iconDefault
                    }
                    Text {
                        id: tabTypeLabel
                        objectName: "tabType-" + tabButton.modelData.tabId

                        anchors.centerIn: parent
                        font.pixelSize: 11
                        text: workspaceTabs.typeLabel(tabButton.modelData.tabType)
                        font.weight: tabButton.checked
                            ? Font.DemiBold : Font.Normal
                        color: tabButton.checked
                            ? Theme.primaryColor
                            : Theme.textMuted
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    spacing: 0
                    Text {
                        id: descriptionLabel
                        objectName: "tabPrimary-" + tabButton.modelData.tabId
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: tabButton.modelData.tabPrimary ?? tabButton.modelData.tabLabel
                        textFormat: Text.PlainText
                        color: tabButton.checked ? Theme.textPrimary : Theme.textMuted
                        font.pixelSize: 12
                        font.weight: tabButton.checked ? Font.DemiBold : Font.Normal
                        elide: Text.ElideRight
                    }
                    Item {
                        id: contextRow
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        clip: true
                        visible: patientLabel.text !== "" || contextLabel.text !== ""
                        implicitHeight: Math.max(patientLabel.implicitHeight, contextLabel.implicitHeight)
                        Text {
                            id: patientLabel
                            objectName: "tabPatient-" + tabButton.modelData.tabId
                            visible: text !== "" && width > 0
                            width: text === "" ? 0 : contextLabel.text === "" ? contextRow.width
                                : Math.min(implicitWidth, contextRow.width * 0.4,
                                    Math.max(0, contextRow.width - contextLabel.implicitWidth - contextSeparator.implicitWidth))
                            text: tabButton.modelData.tabPatient ?? ""
                            textFormat: Text.PlainText
                            color: Theme.textMuted
                            font.pixelSize: 10
                            elide: Text.ElideRight
                        }
                        Text {
                            id: contextSeparator
                            x: patientLabel.width
                            visible: patientLabel.width > 0 && contextLabel.text !== ""
                            width: visible ? implicitWidth : 0
                            text: " · "
                            color: Theme.textMuted
                            font.pixelSize: 10
                        }
                        Text {
                            id: contextLabel
                            objectName: "tabSecondary-" + tabButton.modelData.tabId
                            x: patientLabel.width + contextSeparator.width
                            width: Math.max(0, contextRow.width - x)
                            visible: text !== "" && width > 0
                            text: tabButton.modelData.tabSecondary ?? ""
                            textFormat: Text.PlainText
                            color: Theme.textMuted
                            font.pixelSize: 10
                            elide: Text.ElideRight
                        }
                    }
                }

                Basic.ToolButton {
                    id: closeButton
                    Accessible.name: I18n.format(qsTrId("tabs.close"), {name: tabButton.modelData.tabLabel})
                    implicitWidth: 24
                    implicitHeight: 24
                    opacity: tabButton.checked
                        || tabButton.hovered
                        || closeButton.hovered || closeButton.activeFocus ? 1 : 0

                    Behavior on opacity {
                        NumberAnimation { duration: 100 }
                    }

                    contentItem: Item {
                        Components.AppIcon {
                            anchors.centerIn: parent
                            iconName: "close"
                            iconSize: 16
                            iconColor: closeButton.hovered ? Theme.iconHover : Theme.iconDefault
                        }
                    }

                    background: Rectangle {
                        color: closeButton.hovered
                            ? Theme.controlHover
                            : "transparent"
                        radius: 4
                        border.width: closeButton.activeFocus ? 1 : 0
                        border.color: Theme.focusBorder
                    }

                    onClicked: {
                        workspaceTabs.workspaceController.closeTab(
                            tabButton.modelData.tabId
                        )
                    }
                }
            }

            background: Rectangle {
                objectName: "workspaceTabBackground-" + tabButton.modelData.tabId
                readonly property color visualBorderColor: tabButton.checked
                    ? Theme.tabSelectedBorder : Theme.borderSubtle
                radius: 6
                color: tabButton.checked
                    ? Theme.selectionBackground
                    : tabButton.hovered
                        ? Theme.controlHover
                        : Theme.panelBackgroundSoft
                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.leftMargin: 6
                    anchors.rightMargin: 6
                    height: 2
                    visible: tabButton.checked
                    color: Theme.activeIndicator
                }
                border.color: tabButton.activeFocus ? Theme.focusBorder : visualBorderColor
                border.width: 1
            }
        }
    }
}
