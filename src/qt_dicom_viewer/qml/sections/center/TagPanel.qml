pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../../components" as Components
import "../../theme"

Rectangle {
    id: panel
    objectName: "tagPanel"
    required property var tagController
    property bool active: true
    property bool completed: false
    readonly property bool populate: active && completed
    property bool restoring: true
    property string detailTitle: ""
    property string detailValue: ""
    property string detailMetadata: ""
    readonly property real treeWidth: Math.max(
        270, (width - 28) * 0.45, 210 + tagController.tagModel.maxVisibleDepth * 16)
    readonly property real tableWidth: Math.max(width - 30, treeWidth + vrWidth + 220)
    readonly property real vrWidth: 66
    color: Theme.workspaceBackground

    function restoreScroll() {
        panel.restoring = true
        Qt.callLater(function() {
            if (!panel.tagController)
                return
            tagList.contentY = Math.max(0, Math.min(
                panel.tagController.scrollPosition,
                tagList.contentHeight - tagList.height))
            panel.restoring = false
        })
    }

    // Worker results can reset delegates while the surrounding Loader incubates.
    // Attach models only after that component tree is completely constructed.
    Component.onCompleted: { completed = true; if (active) restoreScroll() }
    onActiveChanged: { if (active && completed) restoreScroll() }

    Connections {
        target: panel.tagController
        function onInstanceChanged() { tagList.positionViewAtBeginning() }
        function onQueryChanged() { tagList.positionViewAtBeginning() }
    }

    Connections {
        target: panel.tagController.tagModel
        function onModelAboutToBeReset() { panel.restoring = true }
        function onModelReset() { panel.restoreScroll() }
    }

    component Field: Components.AppTextField {
        color: Theme.textPrimary
        placeholderTextColor: Theme.textSubtle
        selectionColor: Theme.selectionBackground
        selectedTextColor: Theme.textPrimary
        font.pixelSize: 13
        implicitHeight: 36
        leftPadding: 10
        rightPadding: 10
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 12

        GridLayout {
            id: controls
            Layout.fillWidth: true
            columns: panel.width >= 1050 ? 2 : 1
            columnSpacing: 12
            rowSpacing: 8

            Rectangle {
                Layout.fillWidth: true
                objectName: "tagNavigationPanel"
                Layout.preferredWidth: 680
                Layout.alignment: Qt.AlignTop
                implicitHeight: navigation.implicitHeight + 20
                radius: 5
                color: Theme.panelBackground
                border.color: Theme.borderSubtle
                ColumnLayout {
                    id: navigation
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 10
                    spacing: 6
                    Text {
                        text: qsTrId("text.0899")
                        color: Theme.textMuted
                        font.pixelSize: 11
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        Components.AppButton {
                            objectName: "tagPrevious"
                            text: "‹"
                            compact: true
                            minimumButtonWidth: 30
                            enabled: panel.tagController.currentPage > 1
                            onClicked: panel.tagController.setPage(panel.tagController.currentPage - 1)
                            Components.AppToolTip {
                                visible: parent.hovered
                                text: qsTrId("text.0900")
                            }
                        }
                        Repeater {
                            model: panel.populate ? panel.tagController.pageItems : []
                            delegate: Components.AppButton {
                                required property int modelData
                                objectName: "tagPage-" + modelData
                                compact: true
                                minimumButtonWidth: 30
                                cornerRadius: 9
                                text: modelData ? String(modelData) : "…"
                                enabled: modelData > 0
                                checked: modelData === panel.tagController.currentPage
                                onClicked: panel.tagController.setPage(modelData)
                            }
                        }
                        Components.AppButton {
                            objectName: "tagNext"
                            text: "›"
                            compact: true
                            minimumButtonWidth: 30
                            enabled: panel.tagController.currentPage < panel.tagController.pageCount
                            onClicked: panel.tagController.setPage(panel.tagController.currentPage + 1)
                            Components.AppToolTip {
                                visible: parent.hovered
                                text: qsTrId("text.0901")
                            }
                        }
                        Item { Layout.fillWidth: true }
                        Field {
                            id: pageInput
                            objectName: "tagPageInput"
                            Layout.preferredWidth: 64
                            implicitHeight: 34
                            placeholderText: qsTrId("text.0902")
                            text: String(panel.tagController.currentPage)
                            enabled: panel.tagController.pageCount > 0
                            inputMethodHints: Qt.ImhDigitsOnly
                            onAccepted: panel.tagController.jumpToPage(text)
                        }
                        Components.AppButton {
                            objectName: "tagJump"
                            text: qsTrId("text.0903")
                            compact: true
                            enabled: panel.tagController.pageCount > 0
                            onClicked: panel.tagController.jumpToPage(pageInput.text)
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                objectName: "tagSearchPanel"
                Layout.preferredWidth: 300
                Layout.alignment: Qt.AlignTop
                implicitHeight: controls.columns === 1 ? 54 : navigation.implicitHeight + 20
                radius: 5
                color: Theme.panelBackground
                border.color: Theme.borderSubtle
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 6
                    Text {
                        visible: controls.columns === 2
                        text: qsTrId("text.0904")
                        color: Theme.textMuted
                        font.pixelSize: 11
                    }
                    Field {
                        id: search
                        implicitHeight: 34
                        objectName: "tagSearch"
                        Layout.fillWidth: true
                        placeholderText: qsTrId("text.0905")
                        text: panel.tagController.searchText
                        onTextEdited: panel.tagController.setSearchText(text)
                    }
                }
            }
        }

        Text {
            Layout.fillWidth: true
            visible: text !== ""
            text: panel.tagController.pageError
            color: Theme.warningColor
            font.pixelSize: 11
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: 5
            color: Theme.cardBackground
            border.color: Theme.borderSubtle
            clip: true

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 1
                spacing: 0

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 40
                    color: Theme.elevatedBackground
                    Row {
                        x: -tagList.contentX
                        width: panel.tableWidth
                        height: parent.height
                        Text {
                            width: panel.treeWidth
                            height: parent.height
                            leftPadding: 16
                            text: qsTrId("text.0906")
                            verticalAlignment: Text.AlignVCenter
                            color: Theme.textSecondary
                            font.pixelSize: 12
                        }
                        Text {
                            objectName: "tagVrHeader"
                            width: panel.vrWidth
                            height: parent.height
                            text: "VR"
                            verticalAlignment: Text.AlignVCenter
                            color: Theme.textSecondary
                            font.pixelSize: 12
                        }
                        Text {
                            height: parent.height
                            text: qsTrId("text.0907")
                            verticalAlignment: Text.AlignVCenter
                            color: Theme.textSecondary
                            font.pixelSize: 12
                        }
                    }
                }
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 29
                    color: Theme.panelBackgroundStrong
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 16
                        anchors.verticalCenter: parent.verticalCenter
                        objectName: "tagCount"
                        text: I18n.format(qsTrId("tags.count"), {count: panel.tagController.tagModel.matchCount, total: panel.tagController.tagModel.totalCount})
                        color: Theme.textMuted
                        font.pixelSize: 11
                    }
                    Text {
                        anchors.right: parent.right
                        anchors.rightMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        text: qsTrId("text.0909")
                        color: Theme.textSubtle
                        font.pixelSize: 11
                    }
                }

                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    ListView {
                        id: tagList
                        objectName: "tagList"
                        anchors.fill: parent
                        clip: true
                        model: panel.populate ? panel.tagController.tagModel : null
                        reuseItems: true
                        // Rows are virtualized and recycled, but not incubated offscreen:
                        // a search reset or tab close can invalidate their bound context
                        // before Qt finishes creating a buffered delegate on Windows.
                        cacheBuffer: 0
                        contentWidth: panel.tableWidth
                        flickableDirection: Flickable.AutoFlickDirection
                        boundsBehavior: Flickable.StopAtBounds
                        onContentYChanged: {
                            if (!panel.restoring && panel.tagController)
                                panel.tagController.saveScrollPosition(contentY)
                        }
                        Basic.ScrollBar.vertical: Basic.ScrollBar { }
                        Basic.ScrollBar.horizontal: Basic.ScrollBar { }

                        delegate: Rectangle {
                            id: row
                            required property string nodeId
                            required property int depth
                            required property string tagNumber
                            required property string tagName
                            required property string keyword
                            required property string vr
                            required property string valueText
                            required property bool hasChildren
                            required property bool expanded
                            required property bool isItem
                            required property bool matched
                            readonly property bool selected: panel.tagController.selectedNodeId === nodeId
                            objectName: "tagRow-" + nodeId
                            width: panel.tableWidth
                            height: isItem ? 38 : 78
                            color: selected ? Theme.selectionBackground
                                : hover.hovered ? Theme.cardBackgroundHover : Theme.cardBackground

                            Rectangle {
                                width: 3
                                height: parent.height
                                visible: row.selected
                                color: Theme.selectionBorder
                            }
                            Rectangle {
                                anchors.bottom: parent.bottom
                                width: parent.width
                                height: 1
                                color: Theme.borderSubtle
                                opacity: 0.35
                            }
                            HoverHandler { id: hover }
                            TapHandler {
                                onTapped: panel.tagController.selectNode(row.nodeId)
                                onDoubleTapped: {
                                    panel.detailTitle = row.tagName
                                    panel.detailMetadata = row.tagNumber + (row.vr ? " · VR " + row.vr : "")
                                    panel.detailValue = row.valueText
                                    detailDialog.open()
                                }
                            }
                            Components.AppButton {
                                objectName: "tagExpand-" + row.nodeId
                                x: 8 + row.depth * 16
                                anchors.verticalCenter: parent.verticalCenter
                                width: 24
                                height: 26
                                minimumButtonWidth: 24
                                compact: true
                                text: row.hasChildren ? (row.expanded ? "▾" : "▸") : "·"
                                normalColor: "transparent"
                                disabledColor: "transparent"
                                disabledTextColor: Theme.secondaryStrong
                                enabled: row.hasChildren && panel.tagController.searchText.trim() === ""
                                textColor: Theme.primaryColor
                                onClicked: panel.tagController.toggleNode(row.nodeId)
                            }
                            Column {
                                objectName: "tagIdentity-" + row.nodeId
                                x: 38 + row.depth * 16
                                width: panel.treeWidth - x - 14
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 3
                                Text {
                                    visible: !row.isItem
                                    text: row.tagNumber
                                    color: Theme.primaryColor
                                    font.family: "monospace"
                                    font.pixelSize: 12
                                }
                                Text {
                                    width: parent.width
                                    text: row.tagName
                                    textFormat: Text.PlainText
                                    color: row.matched ? Theme.primaryColor : Theme.textPrimary
                                    font.pixelSize: 13
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                }
                                Text {
                                    visible: row.keyword !== ""
                                    width: parent.width
                                    text: row.keyword
                                    color: Theme.textMuted
                                    font.family: "monospace"
                                    font.pixelSize: 11
                                    elide: Text.ElideRight
                                }
                            }
                            Text {
                                objectName: "tagVr-" + row.nodeId
                                x: panel.treeWidth
                                width: panel.vrWidth - 8
                                anchors.verticalCenter: parent.verticalCenter
                                text: row.vr
                                color: Theme.warningColor
                                font.family: "monospace"
                                font.pixelSize: 13
                                font.weight: Font.DemiBold
                            }
                            Text {
                                objectName: "tagValue-" + row.nodeId
                                x: panel.treeWidth + panel.vrWidth
                                width: Math.max(0, parent.width - x - 18)
                                anchors.verticalCenter: parent.verticalCenter
                                text: row.valueText.length > 500 ? row.valueText.slice(0, 500) + "…" : row.valueText
                                textFormat: Text.PlainText
                                color: Theme.textSecondary
                                font.family: "monospace"
                                font.pixelSize: 13
                                wrapMode: Text.WrapAnywhere
                                maximumLineCount: 2
                                elide: Text.ElideRight
                            }
                        }
                    }

                    ColumnLayout {
                        anchors.centerIn: parent
                        width: Math.max(100, parent.width - 60)
                        spacing: 12
                        visible: panel.tagController.loading || panel.tagController.errorMessage !== ""
                            || panel.tagController.tagModel.matchCount === 0
                        Basic.BusyIndicator {
                            Layout.alignment: Qt.AlignHCenter
                            visible: panel.tagController.loading
                            running: visible
                        }
                        Text {
                            Layout.fillWidth: true
                            objectName: "tagStatus"
                            text: panel.tagController.loading ? qsTrId("text.0437")
                                : panel.tagController.errorMessage !== "" ? I18n.format(qsTrId("tags.readError"), {detail: panel.tagController.errorMessage})
                                : panel.tagController.pageCount === 0 ? qsTrId("text.0911")
                                : panel.tagController.searchText.trim() !== "" ? qsTrId("text.0912")
                                : qsTrId("text.0913")
                            textFormat: Text.PlainText
                            color: panel.tagController.errorMessage !== "" ? Theme.warningColor : Theme.textMuted
                            font.pixelSize: 13
                            wrapMode: Text.WrapAnywhere
                            horizontalAlignment: Text.AlignHCenter
                        }
                        Components.AppButton {
                            objectName: "tagRetry"
                            Layout.alignment: Qt.AlignHCenter
                            visible: panel.tagController.errorMessage !== ""
                            text: qsTrId("text.0914")
                            onClicked: panel.tagController.retry()
                        }
                    }
                }
            }
        }
    }

    Components.AppDialog {
        id: detailDialog
        objectName: "tagValueDialog"
        anchors.centerIn: parent
        width: Math.max(0, Math.min(panel.width - 32, 640))
        height: Math.min(Math.max(0, panel.height - 32),
            header.implicitHeight + footer.implicitHeight + topPadding + bottomPadding
            + spacing * 2 + Math.max(80, Math.min(320, fullValue.implicitHeight)))
        padding: 16
        spacing: 0
        modal: true
        Basic.Overlay.modal: Rectangle { color: Theme.modalScrim }
        title: panel.detailTitle
        subtitle: panel.detailMetadata
        closeButtonName: "tagCloseValue"
        onOpened: fullValue.forceActiveFocus()

        contentItem: Basic.ScrollView {
            id: valueScroll
            objectName: "tagValueScroll"
            clip: true
            contentWidth: availableWidth
            Basic.ScrollBar.horizontal.policy: Basic.ScrollBar.AlwaysOff
            Basic.ScrollBar.vertical: Components.AppScrollBar {}
            background: Rectangle {
                color: Theme.workspaceBackground
                border.color: Theme.borderDefault
                radius: Theme.controlRadius
            }
            Basic.TextArea {
                id: fullValue
                objectName: "tagFullValue"
                width: valueScroll.availableWidth
                padding: 12
                text: panel.detailValue
                textFormat: TextEdit.PlainText
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.WrapAnywhere
                color: Theme.textPrimary
                selectionColor: Theme.selectionBackground
                selectedTextColor: Theme.textPrimary
                font.family: "monospace"
                font.pixelSize: 13
                background: null
                Accessible.name: qsTrId("text.0915")
            }
        }
        footer: Components.AppDialogFooter {
            Components.AppButton {
                objectName: "tagCopyValue"
                text: qsTrId("text.0916")
                actionRole: "primary"
                compact: true
                enabled: panel.detailValue.length > 0
                onClicked: {
                    fullValue.selectAll()
                    fullValue.copy()
                    fullValue.deselect()
                }
            }
        }
    }
}
