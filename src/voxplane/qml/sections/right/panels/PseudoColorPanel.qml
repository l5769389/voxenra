pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../../../theme"
import "../../../components/ShortcutCaption.js" as KeysText
import "../../../components" as Components

ColumnLayout {
    id: pseudoColorPanel
    objectName: "pseudoColorPanel"
    required property var viewportController
    property Item headingHost: null
    property string buttonPrefix: "colorMap-"
    property var settingsController: typeof appController !== "undefined" ? appController.settingsController ?? null : null
    readonly property var favorites: settingsController?.values?.paletteList?.favorites ?? []
    readonly property var bindings: typeof appController !== "undefined" ? appController.shortcutController?.bindings ?? [] : []
    readonly property var options: {
        const all = viewportController?.colorMapOptions ?? []
        return all.filter(entry => favorites.includes(entry.colorMap)).concat(all.filter(entry => !favorites.includes(entry.colorMap)))
    }
    readonly property int shortcutCount: Math.min(9, options.length)
    function selectShortcutIndex(index) {
        const row = rows.itemAt(index)
        if (!row) return
        // Keep the keyboard selection visible without moving focus off the image.
        for (let view = row.parent; view; view = view.parent) {
            if (!(view instanceof Flickable)) continue
            const top = row.mapToItem(view.contentItem, 0, 0).y
            if (top < view.contentY) view.contentY = top
            else if (top + row.height > view.contentY + view.height)
                view.contentY = top + row.height - view.height
            break
        }
        row.click()
    }
    function toggleFavorite(key, restoreFocus) {
        const next = favorites.includes(key) ? favorites.filter(id => id !== key) : favorites.concat([key])
        if (settingsController.setValue("paletteList", "favorites", next) && restoreFocus) {
            Qt.callLater(function() {
                const index = options.findIndex(entry => entry.colorMap === key)
                rows.itemAt(index)?.favoriteButton.forceActiveFocus(Qt.TabFocusReason)
            })
        }
    }
    signal colorSelected()
    property string description: qsTrId("text.1068")
    spacing: 6

    Item {
        id: inlineHeading
        Layout.fillWidth: true
        implicitHeight: heading.implicitHeight
        visible: !pseudoColorPanel.headingHost
        Components.PanelHeading {
            id: heading
            parent: pseudoColorPanel.headingHost ?? inlineHeading
            width: parent.width
            height: implicitHeight
            objectName: "PseudoColorPanelHeading"
            title: qsTrId("text.0309")
            explanation: pseudoColorPanel.description
        }
    }

    Repeater {
        id: rows
        model: pseudoColorPanel.options

        delegate: Components.AppButton {
            id: colorMapButton
            required property int index
            required property var modelData
            readonly property alias favoriteButton: star
            readonly property string hint: index < pseudoColorPanel.shortcutCount ? KeysText.hint("list-" + (index + 1), pseudoColorPanel.bindings) : ""
            Accessible.description: hint
            objectName: pseudoColorPanel.buttonPrefix + modelData.colorMap
            Accessible.name: modelData.label
            Accessible.checkable: true
            Accessible.checked: checked
            Layout.fillWidth: true
            implicitHeight: 36
            topPadding: 6
            bottomPadding: 6
            Layout.minimumWidth: 0
            checked: pseudoColorPanel.viewportController?.activeColorMap === modelData.colorMap
            onClicked: {
                pseudoColorPanel.viewportController.applyColorMap(modelData.colorMap)
                pseudoColorPanel.colorSelected()
            }
            Components.AppToolTip {
                requested: (colorMapButton.hovered || colorMapButton.visualFocus) && !star.hovered
                    && (caption.truncated || caption.text !== caption.fullCaption)
                text: caption.fullCaption
            }

            contentItem: RowLayout {
                spacing: 8

                Components.AppButton {
                    id: star
                    objectName: pseudoColorPanel.buttonPrefix + "favorite-" + colorMapButton.modelData.colorMap
                    visible: !!pseudoColorPanel.settingsController
                    Layout.preferredWidth: 26
                    Layout.preferredHeight: 26
                    minimumButtonWidth: 0
                    compact: true
                    padding: 0
                    normalColor: "transparent"
                    checked: pseudoColorPanel.favorites.includes(colorMapButton.modelData.colorMap)
                    iconName: checked ? "star-filled" : "star"
                    iconSize: 17
                    Accessible.name: qsTrId(checked ? "palette.unfavorite" : "palette.favorite") + " · " + colorMapButton.modelData.label
                    Accessible.checkable: true
                    Accessible.checked: checked
                    onClicked: pseudoColorPanel.toggleFavorite(colorMapButton.modelData.colorMap, visualFocus)
                    Components.AppToolTip {
                        requested: star.hovered || star.visualFocus
                        text: qsTrId(star.checked ? "palette.unfavorite" : "palette.favorite")
                    }
                }
                Canvas {
                    id: gradientPreview
                    Layout.preferredWidth: Math.min(56, colorMapButton.width * 0.20)
                    Layout.preferredHeight: 16

                    onWidthChanged: requestPaint()
                    onHeightChanged: requestPaint()
                    onPaint: {
                        const context = getContext("2d")
                        context.reset()
                        const gradient = context.createLinearGradient(
                            0, 0, width, 0
                        )
                        for (const stop of colorMapButton.modelData.stops)
                            gradient.addColorStop(stop.position, stop.color)
                        context.fillStyle = gradient
                        context.fillRect(0, 0, width, height)
                    }
                }

                Components.ShortcutLabel {
                    id: caption
                    objectName: "paletteCaption"
                    Layout.fillWidth: true
                    title: colorMapButton.modelData.label
                    keyHint: colorMapButton.hint
                    color: colorMapButton.checked
                        ? Theme.textPrimary : Theme.textSecondary
                    Layout.minimumWidth: 0
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                    font.pixelSize: 12
                    font.weight: colorMapButton.checked
                        ? Font.DemiBold : Font.Normal
                }

                Text {
                    visible: colorMapButton.checked
                    text: "✓"
                    color: Theme.iconActive
                    font.pixelSize: 16
                    font.bold: true
                }
            }

            normalColor: "transparent"
            cornerRadius: 5
        }
    }

    Item { Layout.fillHeight: true }
}
