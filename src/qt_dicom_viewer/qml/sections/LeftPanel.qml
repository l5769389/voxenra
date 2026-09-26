pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../components" as Components
import "../theme"

Rectangle {
    id: leftPanel
    objectName: "leftPanel"
    required property var panelController
    readonly property real footerRowHeight: 36
    property bool compact: false
    property var pacsController: null
    property var workspaceController: null
    property var exportController: null
    property var documentController: null
    readonly property string activeSeriesUid: panelController.activeSeriesUid
    readonly property string activeSeriesModality: panelController.activeSeriesModality
    readonly property var navigationActions: [
        {label: qsTrId("text.0532"), type: "file", icon: "nav-load-file", supported: true},
        {label: qsTrId("text.0494"), type: "pacs", icon: "nav-pacs", supported: true},
        {label: qsTrId("text.0679"), type: "2d", icon: "nav-view-2d", supported: true},
        {label: qsTrId("text.0680"), type: "mpr", icon: "nav-view-mpr", supported: true},
        {label: qsTrId("text.0681"), type: "3d", icon: "nav-view-3d", supported: true},
        {label: qsTrId("text.0682"), type: "montage", icon: "nav-view-tile", supported: true},
        {label: qsTrId("text.0683"), type: "4d", icon: "nav-view-4d", supported: true},
        {label: qsTrId("text.0684"), type: "tag", icon: "nav-view-tag", supported: true},
        {label: qsTrId("text.0685"), type: "fusion", icon: "fusion", supported: true}
    ].filter(action => action.type === "file"
        ? !leftPanel.pacsController || leftPanel.pacsController.localEnabled
        : action.type !== "pacs" || (leftPanel.pacsController && leftPanel.pacsController.pacsEnabled))
    readonly property var primaryActions: navigationActions.slice(0, 4)
    readonly property var secondaryActions: navigationActions.slice(4)
    property string selectedSource: workspaceController?.activeTabType === "pacs" ? "pacs" : "file"
    readonly property string activeSource: navigationActions.some(action => action.type === selectedSource)
        ? selectedSource : navigationActions[0].type
    readonly property int sourceCount: navigationActions.filter(action => ["file", "pacs"].includes(action.type)).length
    property string scrollAnchorKey: ""
    property int scrollAnchorIndex: 0
    property real scrollAnchorOffset: 0
    property bool restorePending: false
    property bool resetScrollPending: false
    color: Theme.panelBackground
    border.color: Theme.panelBorder
    border.width: 1
    radius: 8
    clip: true

    function captureScroll(reset) {
        resetScrollPending = resetScrollPending || reset
        if (restorePending) return
        restorePending = true
        const index = seriesList.indexAt(1, seriesList.contentY + 1)
        const item = seriesList.itemAtIndex(index)
        scrollAnchorIndex = Math.max(0, index)
        scrollAnchorKey = panelController.sidebarModel.keyAt(index)
        scrollAnchorOffset = item ? item.y - seriesList.contentY : 0
    }

    function restoreScroll() {
        seriesList.forceLayout()
        if (resetScrollPending || seriesList.count === 0) {
            seriesList.positionViewAtBeginning()
        } else {
            const found = panelController.sidebarModel.indexOfKey(scrollAnchorKey)
            const index = found >= 0 ? found : Math.min(scrollAnchorIndex, seriesList.count - 1)
            seriesList.positionViewAtIndex(index, ListView.Beginning)
            const item = seriesList.itemAtIndex(index)
            if (item) {
                const lower = seriesList.originY
                const upper = lower + Math.max(0, seriesList.contentHeight - seriesList.height)
                seriesList.contentY = Math.max(lower, Math.min(item.y - scrollAnchorOffset, upper))
            }
        }
        restorePending = false
        resetScrollPending = false
    }

    Connections {
        target: leftPanel.panelController.sidebarModel
        function onStructureAboutToChange(reset) { leftPanel.captureScroll(reset) }
        function onStructureChanged(reset) { Qt.callLater(leftPanel.restoreScroll) }
    }

    Connections {
        target: leftPanel.workspaceController
        function onActiveTabChanged() {
            if (leftPanel.workspaceController.activeTabType === "pacs")
                leftPanel.selectedSource = "pacs"
        }
    }

    component NavigationActionButton: Components.ToolbarAction {
        tooltipPlacement: "right"
        id: navigationAction

        required property var actionData
        readonly property bool isFileAction: actionData.type === "file"
        readonly property bool isPacsAction: actionData.type === "pacs"

        buttonObjectName: isFileAction
            ? "sidebarOpenFolder"
            : isPacsAction ? "sidebarPacs" : "openView-" + actionData.type
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.preferredWidth: 1
        Layout.minimumWidth: 0
        label: isFileAction && leftPanel.panelController.scanning ? qsTrId("text.0620") : actionData.label
        shortLabel: actionData.label
        iconSize: Theme.navigationIconSize
        hoverWhenDisabled: true
        checked: (isFileAction || isPacsAction) && leftPanel.activeSource === actionData.type
        segmented: isFileAction || isPacsAction
        normalIconColor: segmented ? Theme.folderAccent : Theme.iconDefault
        disabledIconColor: normalIconColor
        iconName: actionData.icon
        readonly property string viewError: leftPanel.panelController.activeMrViewErrors[actionData.type] ?? ""
        tooltipText: viewError || label
        placeholder: !actionData.supported
        actionEnabled: isFileAction
            ? true
            : isPacsAction ? leftPanel.workspaceController !== null
            : leftPanel.activeSeriesUid !== ""
                && actionData.supported
                && (leftPanel.activeSeriesModality !== "PT"
                    || ["2d", "tag", "mpr", "3d", "fusion"].includes(actionData.type))
                && (actionData.type !== "montage" || !leftPanel.panelController.scanning)
                && (
                    actionData.type !== "4d"
                    || leftPanel.panelController.activeSeriesSupportsFourD
                )

        onTriggered: {
            if (isFileAction || isPacsAction)
                leftPanel.selectedSource = actionData.type
            if (isFileAction)
                leftPanel.panelController.openImportDialog()
            else if (isPacsAction)
                leftPanel.workspaceController.openPacs()
            else if (actionData.type === "fusion")
                leftPanel.panelController.requestFusionView()
            else
                leftPanel.panelController.openSeriesView(
                    leftPanel.activeSeriesUid,
                    actionData.type
                )
        }

    }

    CompactSeriesRail {
        anchors.fill: parent
        anchors.bottomMargin: footer.height
        visible: leftPanel.compact
        panelController: leftPanel.panelController
        pacsController: leftPanel.pacsController
        workspaceController: leftPanel.workspaceController
        onContextRequested: (uid, sceneX, sceneY) => seriesContextMenu.openFor(uid, sceneX, sceneY)
    }

    ColumnLayout {
        visible: !leftPanel.compact
        anchors.fill: parent
        anchors.topMargin: 12
        anchors.bottomMargin: footer.height + 4
        anchors.leftMargin: 1
        anchors.rightMargin: 1
        spacing: 10

        Rectangle {
            Layout.fillWidth: true
            Layout.leftMargin: 10
            Layout.rightMargin: 10
            Layout.preferredHeight: Theme.toolbarButtonHeight * 2 + 4
            color: "transparent"

            ColumnLayout {
                anchors.fill: parent
                spacing: 4

                Item {
                    implicitHeight: Theme.toolbarButtonHeight
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Rectangle {
                        objectName: "sourceEntryGroup"
                        width: ((primaryRow.width - 3 * primaryRow.spacing) / 4) * leftPanel.sourceCount
                            + primaryRow.spacing * (leftPanel.sourceCount - 1)
                        height: parent.height
                        radius: Theme.controlRadius
                        color: Theme.folderSurface
                        border.color: Theme.selectionBorder
                        Rectangle {
                            visible: leftPanel.sourceCount === 2
                            anchors.centerIn: parent
                            width: 1
                            height: parent.height - 16
                            color: Theme.selectionBorder
                            opacity: 0.45
                        }
                    }
                    RowLayout {
                        id: primaryRow
                        anchors.fill: parent
                        spacing: 4
                        Repeater {
                            model: leftPanel.primaryActions
                            delegate: NavigationActionButton {
                                required property var modelData
                                actionData: modelData
                            }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 4

                    Repeater {
                        model: leftPanel.secondaryActions
                        delegate: NavigationActionButton {
                            required property var modelData
                            actionData: modelData
                        }
                    }
                }
            }
        }

        Components.AppTextField {
            objectName: "sidebarPatientSearch"
            Layout.fillWidth: true
            Layout.leftMargin: 10
            Layout.rightMargin: 10
            implicitHeight: 36
            placeholderText: qsTrId("text.0686")
            text: leftPanel.panelController.patientSearch
            onTextEdited: leftPanel.panelController.setPatientSearch(text)
            color: Theme.textPrimary
            placeholderTextColor: Theme.textSubtle
            selectionColor: Theme.selectionBackground
            font.pixelSize: 13
            leftPadding: 10
        }

        Text {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.leftMargin: 10
            Layout.rightMargin: 10
            elide: Text.ElideRight
            color: Theme.textMuted
            font.pixelSize: 11
            text: I18n.format(qsTrId("sidebar.selected"), {count: leftPanel.panelController.selectedSeriesUids.length})
        }

        ListView {
            id: seriesList
            objectName: "sidebarSeriesList"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 0
            Layout.preferredHeight: 0
            model: leftPanel.panelController.sidebarModel
            clip: true
            reuseItems: true
            boundsBehavior: Flickable.StopAtBounds
            Basic.ScrollBar.vertical: Components.AppScrollBar { }

            delegate: Rectangle {
                id: entry
                required property var modelData
                readonly property bool isSeries: modelData.kind === "series"
                readonly property bool selected: isSeries && leftPanel.panelController.selectedSeriesUids.includes(modelData.seriesInstanceUid)
                objectName: isSeries ? "series-" + modelData.seriesInstanceUid : "sidebar-" + modelData.key
                width: seriesList.width
                height: isSeries ? 58 : modelData.kind === "patient" ? 30 : 26
                Accessible.role: Accessible.Button
                Accessible.name: modelData.label + (modelData.subtitle ? " · " + modelData.subtitle : "")
                Accessible.onPressAction: {
                    if (entry.isSeries)
                        leftPanel.panelController.openSeriesView(entry.modelData.seriesInstanceUid, "2d")
                    else if (leftPanel.panelController.patientSearch.trim() === "")
                        leftPanel.panelController.toggleGroup(entry.modelData.key)
                }
                color: selected ? Theme.selectionBackground
                    : mouse.containsMouse ? Theme.cardBackgroundHover
                    : isSeries ? "transparent" : Theme.panelBackgroundStrong

                Rectangle {
                    width: 3
                    height: parent.height
                    visible: entry.selected
                    color: Theme.primaryColor
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: entry.modelData.kind === "study" ? 23 : 10
                    anchors.rightMargin: 26
                    spacing: leftPanel.width < 230 ? 6 : 9
                    Components.AppIcon {
                        objectName: "seriesGroupChevron-" + entry.modelData.key
                        visible: !entry.isSeries
                        Layout.preferredWidth: 20
                        Layout.preferredHeight: 20
                        iconName: entry.modelData.expanded ? "chevron-down" : "chevron-right"
                        iconSize: 20
                        iconColor: Theme.textSecondary
                    }
                    Item {
                        visible: entry.isSeries
                        Layout.preferredWidth: 16
                        Layout.preferredHeight: 16
                    }
                    Rectangle {
                        visible: entry.isSeries
                        Layout.preferredWidth: 42
                        Layout.preferredHeight: 42
                        radius: 7
                        color: Theme.canvasBackground
                        border.color: Theme.borderSubtle
                        Image {
                            id: thumbnail
                            objectName: "seriesThumbnail-" + entry.modelData.seriesInstanceUid
                            anchors.fill: parent
                            anchors.margins: 3
                            source: entry.modelData.thumbnailUrl
                            fillMode: Image.PreserveAspectFit
                            smooth: true
                            mipmap: true
                            cache: false
                        }
                        Text {
                            anchors.centerIn: parent
                            visible: thumbnail.status !== Image.Ready
                            text: entry.modelData.modality || "—"
                            color: Theme.textSubtle
                            font.pixelSize: 12
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 5
                        Text {
                            Layout.fillWidth: true
                            text: entry.modelData.label
                            textFormat: Text.PlainText
                            elide: Text.ElideRight
                            font.pixelSize: entry.modelData.kind === "patient" ? 14 : 12
                            font.weight: entry.modelData.kind === "study" ? Font.Normal : Font.DemiBold
                            color: entry.modelData.kind === "study" ? Theme.textMuted : Theme.textPrimary
                        }
                        RowLayout {
                            visible: entry.isSeries
                            Layout.fillWidth: true
                            spacing: 6
                            Components.ModalityBadge {
                                objectName: "seriesModality-" + entry.modelData.seriesInstanceUid
                                modality: entry.modelData.modality
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: entry.modelData.seriesNumber >= 0 ? "Series " + entry.modelData.seriesNumber : ""
                                textFormat: Text.PlainText
                                elide: Text.ElideRight
                                font.pixelSize: 10
                                color: Theme.textMuted
                            }
                        }
                    }
                    Text {
                        visible: entry.isSeries
                        objectName: "seriesCount-" + entry.modelData.seriesInstanceUid
                        text: entry.modelData.countLabel
                        color: entry.selected ? Theme.textSecondary : Theme.textMuted
                        font.pixelSize: 12
                    }
                }

                Components.SeriesDragArea {
                    id: mouse
                    seriesUid: entry.isSeries ? entry.modelData.seriesInstanceUid : ""
                    panelController: leftPanel.panelController
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    cursorShape: Qt.PointingHandCursor
                    onClicked: event => {
                        if (entry.isSeries && event.button === Qt.RightButton) {
                            leftPanel.panelController.selectContextSeries(entry.modelData.seriesInstanceUid)
                            const point = entry.mapToItem(null, event.x, event.y)
                            seriesContextMenu.openFor(entry.modelData.seriesInstanceUid, point.x, point.y)
                        } else if (entry.isSeries) {
                            leftPanel.panelController.selectSeriesWithModifiers(entry.modelData.seriesInstanceUid,
                                (event.modifiers & (Qt.ControlModifier | Qt.MetaModifier)) !== 0)
                        } else if (leftPanel.panelController.patientSearch.trim() === "") {
                            leftPanel.panelController.toggleGroup(entry.modelData.key)
                        }
                    }
                    onDoubleClicked: event => {
                        if (entry.isSeries && event.button === Qt.LeftButton)
                            leftPanel.panelController.openSeriesView(entry.modelData.seriesInstanceUid, "2d")
                    }
                }
                Components.AppCheckBox {
                    objectName: "selectSeries-" + entry.modelData.seriesInstanceUid
                    visible: entry.isSeries
                    x: 4
                    anchors.verticalCenter: parent.verticalCenter
                    width: 28
                    height: 40
                    z: 2
                    checked: entry.selected
                    Accessible.name: entry.modelData.label
                    onClicked: leftPanel.panelController.selectSeriesWithModifiers(entry.modelData.seriesInstanceUid, true)
                }
                Components.AppToolTip {
                    visible: mouse.containsMouse
                    delay: 900
                    text: entry.modelData.label + (entry.modelData.subtitle ? "\n" + entry.modelData.subtitle : "")
                }
            }

            Text {
                anchors.centerIn: parent
                visible: seriesList.count === 0
                text: leftPanel.panelController.patientSearch.trim() !== "" ? qsTrId("text.0689")
                    : leftPanel.panelController.scanning ? qsTrId("text.0690") : qsTrId("text.0691")
                color: Theme.textSubtle
                font.pixelSize: 12
                horizontalAlignment: Text.AlignHCenter
                lineHeight: 1.4
            }
        }
    }

    Item {
        id: footer
        objectName: "sidebarSettingsFooter"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: 1
        anchors.rightMargin: 1
        height: leftPanel.footerRowHeight * (leftPanel.compact ? 6 : 1)
        Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.dividerColor }
        Components.ToolbarAction {
            tooltipPlacement: "right"
            id: exportEntry
            buttonObjectName: "sidebarExport"
            x: leftPanel.compact ? (parent.width - width) / 2 : 8
            y: (leftPanel.footerRowHeight - height) / 2
            width: 28
            height: 28
            label: qsTrId("text.0647")
            tooltipText: qsTrId("text.0647")
            primaryAction: true
            normalIconColor: Theme.textOnPrimary
            iconName: "export"
            iconSize: 18
            actionEnabled: leftPanel.activeSeriesUid !== "" && !leftPanel.panelController.scanning
                && leftPanel.exportController !== null && !leftPanel.exportController.busy
            onTriggered: leftPanel.exportController.openSeries(leftPanel.activeSeriesUid, false)
        }
        Components.ToolbarAction {
            tooltipPlacement: "right"
            buttonObjectName: "sidebarClear"
            x: leftPanel.compact ? (parent.width - width) / 2 : exportEntry.x + exportEntry.width + 4
            y: (leftPanel.footerRowHeight - height) / 2 + (leftPanel.compact ? leftPanel.footerRowHeight : 0)
            width: 28
            height: 28
            label: qsTrId("text.0692")
            tooltipText: qsTrId("text.0692")
            iconName: "delete"
            iconSize: 18
            resetAction: true
            actionEnabled: leftPanel.panelController.hasSeries && !leftPanel.panelController.scanning
            onTriggered: leftPanel.panelController.clearSeries()
        }
        Components.ToolbarAction {
            tooltipPlacement: "right"
            buttonObjectName: "sidebarWorkspace"
            x: leftPanel.compact ? (parent.width - width) / 2 : 72
            y: (leftPanel.footerRowHeight - height) / 2 + (leftPanel.compact ? 2 * leftPanel.footerRowHeight : 0)
            width: 28; height: 28
            label: qsTrId("text.0622")
            tooltipText: qsTrId("text.0693") + (leftPanel.documentController?.recoveryStatusText ?? "")
            iconName: "workspace"
            iconSize: 18
            onTriggered: leftPanel.workspaceController.showDocumentRequested()
            Components.WorkspaceSaveIndicator {
                objectName: "sidebarWorkspaceStatus"
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                width: 12; height: 12
                badge: true
                tooltipEnabled: false
                controller: leftPanel.documentController
            }
        }
        Components.ToolbarAction {
            tooltipPlacement: "right"
            buttonObjectName: "sidebarManual"
            x: leftPanel.compact ? (parent.width - width) / 2 : settingsEntry.x - width - 4
            y: (leftPanel.footerRowHeight - height) / 2 + (leftPanel.compact ? 3 * leftPanel.footerRowHeight : 0)
            width: 28
            height: 28
            label: qsTrId("text.0495")
            tooltipText: qsTrId("text.0495")
            iconName: "manual"
            iconSize: 18
            checked: leftPanel.workspaceController?.activeTabType === "manual"
            visible: leftPanel.workspaceController !== null
            onTriggered: leftPanel.workspaceController.openManual("")
        }
        Components.ToolbarAction {
            tooltipPlacement: "right"
            id: settingsEntry
            buttonObjectName: "sidebarSettings"
            x: leftPanel.compact ? (parent.width - width) / 2 : parent.width - width - 40
            y: (leftPanel.footerRowHeight - height) / 2 + (leftPanel.compact ? 4 * leftPanel.footerRowHeight : 0)
            width: 28
            height: 28
            label: qsTrId("text.0694")
            tooltipText: qsTrId("text.0694")
            iconName: "settings"
            iconSize: 18
            checked: leftPanel.workspaceController && leftPanel.workspaceController.activeTabType === "settings"
            visible: leftPanel.workspaceController !== null
            onTriggered: leftPanel.workspaceController.openSettings()
        }
    }

    component SeriesMenuItem: Basic.MenuItem {
        id: seriesMenuItem

        required property string actionCode
        required property string iconName
        property bool actionEnabled: true
        property bool danger: false

        objectName: "seriesContextAction-" + actionCode
        readonly property string viewError: leftPanel.panelController.seriesViewError(seriesContextMenu.contextSeriesUid, actionCode)
        Components.AppToolTip {
            text: seriesMenuItem.viewError
            visible: seriesMenuItem.viewError !== "" && reasonHover.hovered
        }
        HoverHandler { id: reasonHover }
        enabled: actionEnabled && (leftPanel.panelController.seriesModality(seriesContextMenu.contextSeriesUid) !== "PT"
            || !["montage", "4d"].includes(actionCode))
        implicitWidth: 244
        implicitHeight: 30
        leftPadding: 9
        rightPadding: 10
        topPadding: 5
        bottomPadding: 5
        hoverEnabled: true

        contentItem: RowLayout {
            spacing: 9

            Components.AppIcon {
                Layout.preferredWidth: 16
                Layout.preferredHeight: 16
                iconName: seriesMenuItem.iconName
                iconSize: 16
                iconColor: !seriesMenuItem.enabled
                    ? Theme.textDisabled
                    : seriesMenuItem.danger
                        ? Theme.dangerColor
                        : seriesMenuItem.highlighted
                            ? Theme.iconHover
                            : Theme.iconDefault
            }

            Text {
                Layout.fillWidth: true
                text: seriesMenuItem.text
                color: !seriesMenuItem.enabled
                    ? Theme.textDisabled
                    : seriesMenuItem.danger
                        ? Theme.dangerColor
                        : Theme.textPrimary
                font.pixelSize: 12
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }
        }

        background: Rectangle {
            radius: 2
            color: seriesMenuItem.enabled && seriesMenuItem.highlighted
                ? seriesMenuItem.danger
                    ? Theme.dangerSurface
                    : Theme.controlHover
                : "transparent"
        }

        onTriggered: seriesContextMenu.triggerAction(actionCode)

        Components.AppToolTip {
            visible: parent.hovered && !parent.actionEnabled
            delay: 350
            text: ["montage", "4d"].includes(parent.actionCode)
                ? qsTrId("text.0695") : qsTrId("text.0697")
        }
    }

    component SeriesMenuSeparator: Basic.MenuSeparator {
        implicitHeight: 7
        topPadding: 3
        bottomPadding: 3
        contentItem: Rectangle {
            implicitHeight: 1
            color: Theme.dividerColor
        }
    }

    Basic.Menu {
        id: seriesContextMenu
        objectName: "seriesContextMenu"
        parent: Basic.Overlay.overlay
        property string contextSeriesUid: ""
        property real requestedSceneX: 0
        property real requestedSceneY: 0
        width: Math.min(252, parent.width - 16)
        padding: 4
        // A separate popup window stays above the native VTK child window.
        popupType: leftPanel.workspaceController?.activeViewport?.viewportType === "volume"
            ? Basic.Popup.Window : Basic.Popup.Item
        modal: false
        focus: true
        closePolicy: Basic.Popup.CloseOnEscape | Basic.Popup.CloseOnPressOutside
        z: 1000
        onOpened: reposition()
        onHeightChanged: {
            if (opened)
                reposition()
        }

        function reposition() {
            x = Math.max(8, Math.min(requestedSceneX, parent.width - width - 8))
            y = Math.max(8, Math.min(requestedSceneY, parent.height - height - 8))
        }

        function openFor(seriesUid, sceneX, sceneY) {
            contextSeriesUid = seriesUid
            requestedSceneX = sceneX
            requestedSceneY = sceneY
            open()
            Qt.callLater(reposition)
        }

        function triggerAction(action) {
            const seriesUid = contextSeriesUid
            close()
            if (action === "comparempr") {
                leftPanel.panelController.compareController.requestMpr(seriesUid)
            } else if (action === "compare2d") {
                leftPanel.panelController.compareController.request(seriesUid)
            } else if (action === "fusion") {
                leftPanel.panelController.requestFusionView()
            } else if (["2d", "mpr", "tag", "3d", "4d", "montage"].includes(action)) {
                leftPanel.panelController.openSeriesView(seriesUid, action)
            } else if (action === "directory") {
                if (!leftPanel.panelController.openSeriesDirectory(seriesUid))
                    directoryErrorDialog.open()
            } else if (action === "deidentify") {
                leftPanel.exportController.openSeries(seriesUid, true)
            } else if (action === "remove") {
                leftPanel.panelController.removeSeries(seriesUid)
                contextSeriesUid = ""
            }
        }

        background: Rectangle {
            color: Theme.elevatedBackground
            border.color: Theme.borderStrong
            border.width: 1
            radius: 3
        }

        SeriesMenuItem {
            actionCode: "2d"
            iconName: "nav-view-2d"
            text: qsTrId("text.0698")
        }
        SeriesMenuItem {
            actionCode: "compare2d"
            iconName: "nav-compare-2d"
            text: qsTrId("compare.title")
            actionEnabled: leftPanel.panelController.compareController.supportsSeries(seriesContextMenu.contextSeriesUid)
        }
        SeriesMenuItem {
            actionCode: "comparempr"
            iconName: "nav-compare-mpr"
            text: qsTrId("compare.mpr.title")
            actionEnabled: leftPanel.panelController.compareController.supportsMprSeries(seriesContextMenu.contextSeriesUid)
        }
        SeriesMenuItem {
            actionCode: "montage"
            iconName: "nav-view-tile"
            text: qsTrId("text.0699")
            actionEnabled: !leftPanel.panelController.scanning
        }
        SeriesMenuItem {
            actionCode: "mpr"
            iconName: "nav-view-mpr"
            text: qsTrId("text.0700")
        }
        SeriesMenuItem {
            actionCode: "fusion"
            iconName: "fusion"
            text: qsTrId("text.0675")
        }
        SeriesMenuItem {
            actionCode: "3d"
            iconName: "nav-view-3d"
            text: qsTrId("text.0701")
        }
        SeriesMenuItem {
            actionCode: "4d"
            iconName: "nav-view-4d"
            text: qsTrId("text.0702")
            actionEnabled: leftPanel.panelController.seriesSupportsFourD(
                seriesContextMenu.contextSeriesUid
            )
        }
        SeriesMenuItem {
            actionCode: "tag"
            iconName: "nav-view-tag"
            text: qsTrId("text.0703")
        }

        SeriesMenuSeparator { }

        SeriesMenuItem {
            actionCode: "directory"
            iconName: "nav-load-file"
            text: qsTrId("text.0704")
        }
        SeriesMenuItem {
            actionCode: "deidentify"
            iconName: "shield"
            text: qsTrId("text.0705")
            actionEnabled: !leftPanel.panelController.scanning && leftPanel.exportController !== null
                && !leftPanel.exportController.busy
        }

        SeriesMenuSeparator { }

        SeriesMenuItem {
            actionCode: "remove"
            iconName: "close"
            text: qsTrId("text.0707")
            danger: true
        }
    }

    CompareSeriesDialog {
        controller: leftPanel.panelController.compareController
        thumbnails: leftPanel.panelController.fusionThumbnails
        nativePopup: leftPanel.workspaceController?.activeViewport?.viewportType === "volume"
    }

    FusionSeriesDialog { controller: leftPanel.panelController }

    Components.AppDialog {
        id: directoryErrorDialog
        objectName: "seriesDirectoryErrorDialog"
        parent: Basic.Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(360, parent.width - 32)
        height: 160
        title: qsTrId("text.0708")
        modal: true
        contentItem: Text {
            text: qsTrId("text.0709")
            color: Theme.textPrimary
            font.pixelSize: 13
            wrapMode: Text.Wrap
        }

    }
}
