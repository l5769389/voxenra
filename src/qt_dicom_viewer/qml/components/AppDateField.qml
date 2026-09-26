pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../theme"
AppTextField {
    id: root
    rightPadding: 32
    placeholderText: "YYYY-MM-DD"
    Accessible.name: qsTrId("text.0711")
    readonly property bool validDate: {
        if (!text) return true
        if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return false
        const parts = text.split("-").map(Number)
        const d = new Date(parts[0], parts[1] - 1, parts[2])
        return d.getFullYear() === parts[0] && d.getMonth() === parts[1] - 1 && d.getDate() === parts[2]
    }
    color: validDate ? Theme.textPrimary : Theme.dangerColor
    function chooseDate(d) {
        text = d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0")
        calendar.close()
    }
    AppButton {
        objectName: root.objectName + "-calendar"
        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
        width: 28; height: 28; minimumButtonWidth: 28; compact: true
        text: "▦"; Accessible.name: qsTrId("text.0712"); normalColor: "transparent"
        onClicked: calendar.open()
    }
    Basic.Popup {
        id: calendar
        objectName: root.objectName + "-popup"
        parent: Basic.Overlay.overlay
        x: parent ? Math.max(8, Math.min(parent.width - width - 8, root.mapToItem(parent, 0, 0).x)) : 0
        y: parent ? Math.max(8, Math.min(parent.height - height - 8, root.mapToItem(parent, 0, root.height).y)) : 0
        width: Math.min(292, (parent?.width ?? 308) - 16)
        padding: 10; modal: true; focus: true
        Basic.Overlay.modal: Rectangle { color: Theme.dateModalScrim }
        property date displayed: new Date()
        onOpened: {
            if (root.text && root.validDate) {
                const p = root.text.split("-").map(Number)
                displayed = new Date(p[0], p[1] - 1, 1)
            } else displayed = new Date()
        }
        function moveMonth(amount) { displayed = new Date(displayed.getFullYear(), displayed.getMonth() + amount, 1) }
        background: Rectangle { color: Theme.panelBackground; border.color: Theme.borderStrong; radius: 6 }
        contentItem: ColumnLayout {
            spacing: 8
            RowLayout {
                Layout.fillWidth: true
                Text { Layout.fillWidth: true; text: qsTrId("text.0712"); color: Theme.textSecondary; font.pixelSize: 12 }
                AppButton {
                    objectName: root.objectName + "-close"
                    iconName: "close"; iconSize: 14
                    Layout.preferredWidth: 24; Layout.preferredHeight: 24
                    minimumButtonWidth: 24; compact: true
                    normalColor: "transparent"; Accessible.name: qsTrId("text.0621")
                    onClicked: calendar.close()
                }
            }
            RowLayout {
                Layout.fillWidth: true
                AppButton { text: "‹"; minimumButtonWidth: 24; compact: true; Accessible.name: qsTrId("text.0713"); onClicked: calendar.moveMonth(-1) }
                AppNumberField {
                    objectName: root.objectName + "-year"
                    Layout.fillWidth: true; Layout.minimumWidth: 55
                    minimum: 1900; maximum: 2200; decimals: 0
                    horizontalAlignment: Text.AlignHCenter
                    numberValue: calendar.displayed.getFullYear()
                    Accessible.name: qsTrId("text.0714")
                    onEdited: value => calendar.displayed = new Date(value, calendar.displayed.getMonth(), 1)
                }
                AppComboBox {
                    objectName: root.objectName + "-month"
                    Layout.preferredWidth: 74
                    model: [qsTrId("text.0715"), qsTrId("text.0716"), qsTrId("text.0717"), qsTrId("text.0718"), qsTrId("text.0719"), qsTrId("text.0720"), qsTrId("text.0721"), qsTrId("text.0722"), qsTrId("text.0723"), qsTrId("text.0724"), qsTrId("text.0725"), qsTrId("text.0726")]
                    currentIndex: calendar.displayed.getMonth()
                    onActivated: index => calendar.displayed = new Date(calendar.displayed.getFullYear(), index, 1)
                }
                AppButton { text: "›"; minimumButtonWidth: 24; compact: true; Accessible.name: qsTrId("text.0727"); onClicked: calendar.moveMonth(1) }
            }
            GridLayout {
                Layout.fillWidth: true; columns: 7; columnSpacing: 2; rowSpacing: 2; uniformCellWidths: true
                Repeater {
                    model: [qsTrId("text.0728"), qsTrId("text.0729"), qsTrId("text.0730"), qsTrId("text.0731"), qsTrId("text.0732"), qsTrId("text.0733"), qsTrId("text.0734")]
                    Text { required property string modelData; Layout.fillWidth: true; text: modelData; horizontalAlignment: Text.AlignHCenter; color: Theme.textMuted; font.pixelSize: 11 }
                }
                Repeater {
                    model: 42
                    AppButton {
                        required property int index
                        readonly property date day: new Date(calendar.displayed.getFullYear(), calendar.displayed.getMonth(), 1 + index - (new Date(calendar.displayed.getFullYear(), calendar.displayed.getMonth(), 1).getDay() + 6) % 7)
                        objectName: root.objectName + "-day-" + day.getDate() + (day.getMonth() === calendar.displayed.getMonth() ? "" : "-outside")
                        Layout.fillWidth: true; Layout.preferredHeight: 28; minimumButtonWidth: 24; compact: true
                        checked: root.text === day.getFullYear() + "-" + String(day.getMonth() + 1).padStart(2, "0") + "-" + String(day.getDate()).padStart(2, "0")
                        text: day.getDate()
                        textColor: day.getMonth() === calendar.displayed.getMonth() ? Theme.textPrimary : Theme.textSubtle
                        onClicked: root.chooseDate(day)
                    }
                }
            }
            RowLayout {
                AppButton { text: qsTrId("text.0735"); compact: true; onClicked: root.chooseDate(new Date()) }
                Item { Layout.fillWidth: true }
                AppButton { objectName: root.objectName + "-clear"; text: qsTrId("text.0736"); compact: true; onClicked: { root.text = ""; calendar.close() } }
            }
        }
    }
}
