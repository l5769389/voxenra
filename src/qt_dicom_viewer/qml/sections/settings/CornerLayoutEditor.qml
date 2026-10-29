pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import QtQuick.Controls.Basic as Basic
import "../../components" as Components
import "../../theme"

ColumnLayout {
    id: editor
    required property var settingsController
    readonly property var values: settingsController.values.corners
    readonly property var fields: settingsController.cornerFields
    readonly property var corners: ["topLeft", "topRight", "bottomLeft", "bottomRight"]
    readonly property var titles: [qsTrId("text.0789"), qsTrId("text.0790"), qsTrId("text.0791"), qsTrId("text.0792")]
    readonly property int sampleFontSize: values.fontSize ?? 12
    readonly property real sampleLineHeight: values.lineHeight ?? 1.2
    readonly property color sampleColor: values.colorMode === "custom" ? values.color : Theme.overlayText
    readonly property real rowHeight: Math.max(38, 20 + sampleFontSize * sampleLineHeight)
    readonly property real rowStep: rowHeight + 4
    property string activeCorner: "topLeft"
    property string sourceCorner: ""
    property string sourceField: ""
    property string targetCorner: ""
    property int targetSlot: -1
    property bool dragging: false
    property point startPoint
    property point pointer
    property string error: ""
    readonly property var samples: ({studyDate: "2026/10/29", viewPosition: "Axial · S: 12.0 mm", manufacturer: "Example", seriesDescription: "Chest", studyDescription: "CT Chest", modality: "CT", slice: "12 / 120", patientName: "Example", patientId: "DEMO-001", exposure: "120 kV · 100 mAs", sliceThickness: "1.0 mm", window: "WW: 400 · WL: 40", cursor: "X: 128 · Y: 128 · 35 HU", zoom: "100%", transform: "Rot: 0° · Flip: —", instanceNumber: "12", matrix: "512 × 512", spacing: "0.7 × 0.7 mm", seriesUid: "1.2.840…"})
    function label(key) { return fields.find(item => item.key === key)?.label ?? key }
    function cancel() { dragging = false; sourceCorner = ""; sourceField = ""; targetCorner = ""; targetSlot = -1 }
    function updateTarget() {
        targetCorner = ""; targetSlot = -1; error = ""
        for (let i = 0; i < tiles.count; ++i) {
            const tile = tiles.itemAt(i)
            const p = tile.mapFromItem(editor.Window.window.contentItem, pointer.x, pointer.y)
            if (p.x < 0 || p.x > tile.width || p.y < 0 || p.y > tile.height) continue
            const key = corners[i], list = values[key]
            targetCorner = key
            if (key !== sourceCorner && list.includes(sourceField)) error = qsTrId("corners.duplicate")
            else if (key !== sourceCorner && list.length >= 8) error = qsTrId("corners.full")
            targetSlot = Math.max(0, Math.min(list.length, Math.floor((p.y - 40 + editor.rowStep / 2) / editor.rowStep)))
            break
        }
    }
    function finish() {
        const source = sourceCorner, field = sourceField, target = targetCorner, slot = targetSlot
        const commit = dragging && target !== "" && slot >= 0 && error === ""
        cancel()
        if (commit) Qt.callLater(function() {
            if (!editor.settingsController.transferCornerField(source, field, target, slot)) editor.error = editor.settingsController.message
        })
    }
    onVisibleChanged: if (!visible) cancel()
    onWidthChanged: cancel()
    Connections { target: editor.Window.window; function onActiveChanged() { if (!editor.Window.window.active) editor.cancel() } }
    Shortcut { sequence: "Escape"; enabled: editor.dragging; onActivated: { editor.cancel(); editor.error = "" } }
    Timer {
        interval: 30; repeat: true; running: editor.dragging
        onTriggered: {
            let p = editor.parent
            while (p && p.contentY === undefined) p = p.parent
            if (!p) return
            const point = p.mapFromItem(editor.Window.window.contentItem, editor.pointer.x, editor.pointer.y)
            const delta = point.y < 48 ? -12 : point.y > p.height - 48 ? 12 : 0
            if (delta) { p.contentY = Math.max(0, Math.min(p.contentHeight - p.height, p.contentY + delta)); editor.updateTarget() }
        }
    }
    Text { Layout.fillWidth: true; text: qsTrId("corners.directHint"); color: Theme.textSecondary; font.pixelSize: 12; wrapMode: Text.Wrap }
    Rectangle {
        id: board
        objectName: "cornerEditorBoard"
        Layout.fillWidth: true
        implicitHeight: grid.implicitHeight + 24
        color: Theme.canvasBackground; radius: 6; border.color: Theme.borderSubtle
        GridLayout {
            id: grid
            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 12
            columns: 2; columnSpacing: 24; rowSpacing: 32; uniformCellWidths: true
            Repeater {
                id: tiles
                model: editor.corners
                delegate: Rectangle {
                    id: tile
                    required property string modelData
                    required property int index
                    objectName: "cornerPreview-" + modelData
                    Layout.fillWidth: true; Layout.minimumWidth: 0
                    Layout.preferredHeight: Math.max(138, 48 + editor.values[modelData].length * editor.rowStep)
                    Layout.alignment: index < 2 ? Qt.AlignTop : Qt.AlignBottom
                    readonly property bool rightSide: index % 2 === 1
                    color: "transparent"; radius: 4
                    border.color: editor.targetCorner === modelData ? (editor.error ? Theme.dangerColor : Theme.primaryColor) : Theme.borderSubtle
                    RowLayout {
                        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 6
                        Text { Layout.fillWidth: true; text: editor.titles[tile.index]; color: Theme.overlayMuted; font.pixelSize: 12 }
                        Components.AppButton {
                            objectName: "cornerAddOpen-" + tile.modelData
                            text: "+"; compact: true; minimumButtonWidth: 26; Layout.preferredWidth: 26; Layout.preferredHeight: 26
                            Accessible.name: qsTrId("text.0807") + editor.titles[tile.index]
                            enabled: !editor.dragging && editor.values[tile.modelData].length < 8
                            onClicked: { editor.activeCorner = tile.modelData; search.text = ""; addPopup.open() }
                        }
                    }
                    Column {
                        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                        anchors.topMargin: 40; anchors.leftMargin: 5; anchors.rightMargin: 5
                        spacing: 4
                        Repeater {
                            model: editor.values[tile.modelData]
                            delegate: Rectangle {
                                id: row
                                required property string modelData
                                required property int index
                                width: parent.width; height: editor.rowHeight; radius: 4
                                opacity: editor.dragging && editor.sourceCorner === tile.modelData && editor.sourceField === modelData ? 0.45 : 1
                                color: mouse.containsMouse || mouse.pressed ? Theme.overlayDivider : Theme.overlayCard
                                RowLayout {
                                    anchors.fill: parent; anchors.margins: 4; spacing: 4
                                    Text { text: "⠿"; color: Theme.overlayMuted; font.pixelSize: 15 }
                                    ColumnLayout {
                                        Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 1
                                        Text { Layout.fillWidth: true; text: editor.label(row.modelData); font.pixelSize: 11; color: Theme.overlayMuted; elide: Text.ElideRight; horizontalAlignment: tile.rightSide ? Text.AlignRight : Text.AlignLeft }
                                        Text { Layout.fillWidth: true; text: editor.samples[row.modelData] ?? "—"; font.pixelSize: editor.sampleFontSize; lineHeight: editor.sampleLineHeight; color: editor.sampleColor; elide: Text.ElideRight; horizontalAlignment: tile.rightSide ? Text.AlignRight : Text.AlignLeft }
                                    }
                                    Components.AppButton {
                                        objectName: "cornerRemove-" + tile.modelData + "-" + row.index
                                        text: "×"; compact: true; minimumButtonWidth: 22; Layout.preferredWidth: 22; Layout.preferredHeight: 24
                                        enabled: !editor.dragging
                                        Accessible.name: qsTrId("text.0804") + editor.label(row.modelData)
                                        onClicked: editor.settingsController.removeCornerField(tile.modelData, row.index)
                                    }
                                }
                                MouseArea {
                                    id: mouse
                                    objectName: "cornerDrag-" + tile.modelData + "-" + row.index
                                    anchors.fill: parent; anchors.rightMargin: 30
                                    hoverEnabled: true; preventStealing: true; activeFocusOnTab: true
                                    cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                                    Accessible.name: editor.label(row.modelData)
                                    onPressed: event => {
                                        forceActiveFocus(); editor.error = ""
                                        editor.sourceCorner = tile.modelData; editor.sourceField = row.modelData
                                        editor.startPoint = mapToItem(editor.Window.window.contentItem, event.x, event.y)
                                    }
                                    onPositionChanged: event => {
                                        if (!pressed || !editor.sourceField) return
                                        editor.pointer = mapToItem(editor.Window.window.contentItem, event.x, event.y)
                                        if (!editor.dragging && Math.hypot(editor.pointer.x - editor.startPoint.x, editor.pointer.y - editor.startPoint.y) < 8) return
                                        editor.dragging = true; editor.updateTarget()
                                    }
                                    onReleased: editor.finish()
                                    onCanceled: editor.cancel()
                                    Keys.onPressed: event => {
                                        if ((event.modifiers & Qt.AltModifier) && [Qt.Key_Up, Qt.Key_Down].includes(event.key)) {
                                            editor.settingsController.moveCornerField(tile.modelData, row.index, event.key === Qt.Key_Up ? -1 : 1); event.accepted = true
                                        }
                                    }
                                }
                            }
                        }
                        Text { visible: !editor.values[tile.modelData].length; text: qsTrId("corners.dropHere"); color: Theme.overlayMuted; font.pixelSize: 11 }
                    }
                    Rectangle {
                        visible: editor.dragging && editor.targetCorner === tile.modelData && !editor.error
                        x: 5; y: 39 + editor.targetSlot * editor.rowStep; width: parent.width - 10; height: 2; color: Theme.primaryColor
                    }
                }
            }
        }
    }
    Text { Layout.fillWidth: true; visible: editor.error !== ""; text: editor.error; color: Theme.dangerColor; wrapMode: Text.Wrap; font.pixelSize: 12 }
    Rectangle {
        parent: editor.Window.window ? editor.Window.window.contentItem : editor
        visible: editor.dragging
        x: Math.min(parent.width - width, editor.pointer.x + 14)
        y: Math.max(0, Math.min(parent.height - height, editor.pointer.y + 14))
        width: Math.min(260, parent.width); height: ghostText.implicitHeight + 16; z: 1000
        radius: 4; color: Theme.panelBackground; border.color: editor.error ? Theme.dangerColor : Theme.primaryColor
        Text { id: ghostText; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 8; text: editor.error || editor.label(editor.sourceField); color: editor.error ? Theme.dangerColor : Theme.textPrimary; wrapMode: Text.Wrap; font.pixelSize: 12 }
    }
    Basic.Popup {
        id: addPopup
        parent: editor.Window.window ? editor.Window.window.contentItem : editor
        x: Math.max(0, (parent.width - width) / 2); y: Math.max(0, (parent.height - height) / 2)
        width: Math.min(340, parent.width - 24); padding: 12; modal: true; focus: true
        background: Rectangle { color: Theme.panelBackground; radius: 6; border.color: Theme.borderStrong }
        contentItem: ColumnLayout {
            spacing: 10
            Text { text: editor.titles[editor.corners.indexOf(editor.activeCorner)]; color: Theme.textPrimary }
            Components.AppTextField { id: search; objectName: "cornerFieldSearch"; Layout.fillWidth: true; placeholderText: qsTrId("text.0806") }
            Components.AppComboBox {
                id: choice; objectName: "cornerChoice-" + editor.activeCorner; Layout.fillWidth: true
                model: editor.fields.filter(item => !editor.values[editor.activeCorner].includes(item.key) && (item.label + item.key).toLowerCase().includes(search.text.toLowerCase()))
                textRole: "label"; valueRole: "key"
            }
            Components.AppButton {
                objectName: "cornerAdd-" + editor.activeCorner; text: qsTrId("text.0807"); enabled: choice.currentIndex >= 0
                onClicked: { if (editor.settingsController.addCornerField(editor.activeCorner, choice.currentValue)) addPopup.close() }
            }
        }
    }
}
