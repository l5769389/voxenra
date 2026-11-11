import QtQuick
Canvas {
    id: root
    required property var colors
    implicitHeight: 30
    onColorsChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onPaint: {
        const ctx = getContext("2d")
        ctx.clearRect(0, 0, width, height)
        const gradient = ctx.createLinearGradient(0, 0, width, 0)
        colors.forEach((color, i) => gradient.addColorStop(i / (colors.length - 1), color))
        ctx.fillStyle = gradient
        ctx.fillRect(0, 0, width, height)
    }
}
