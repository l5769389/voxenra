pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window

Item {
    id: root
    required property var controller
    property real screenScaleX: 1
    property real screenScaleY: 1
    readonly property var scalar: controller?.scalarDisplay ?? ({})
    readonly property bool available: !!scalar.source
    readonly property bool gpu: GraphicsInfo.api !== GraphicsInfo.Software && GraphicsInfo.api !== GraphicsInfo.Unknown
    readonly property bool useShader: available && gpu && effect.status !== ShaderEffect.Error
    Image {
        id: texture
        source: root.useShader ? root.scalar.source : ""
        visible: false
        cache: false
        smooth: false
    }
    Image {
        id: lutTexture
        source: root.useShader ? root.scalar.lut : ""
        visible: false
        smooth: false
    }
    ShaderEffect {
        id: effect
        objectName: "scalarDisplayShader"
        anchors.fill: parent
        visible: root.useShader
        property var source: texture
        property var colorLut: lutTexture
        property vector4d dataRange: Qt.vector4d(root.scalar.minimum ?? 0,root.scalar.span ?? 1,
                                               root.scalar.lower ?? 0,root.scalar.width ?? 1)
        property vector2d imageSize: Qt.vector2d(root.width,root.height)
        property real inverted: root.scalar.inverted ? 1 : 0
        fragmentShader: "../../../shaders/scalar_display.frag.qsb"
        blending: false
    }
    Image {
        objectName: "scalarDisplayFallback"
        anchors.fill: parent
        visible: !root.useShader
        source: root.useShader ? "" : root.available ? root.scalar.cpu : root.controller?.imageSource ?? ""
        cache: false
        // Software fallback also interpolates scalar values before windowing.
        sourceSize: root.available ? Qt.size(Math.max(1,Math.min(4096,Math.ceil(root.width*root.screenScaleX*Screen.devicePixelRatio))),
                                             Math.max(1,Math.min(4096,Math.ceil(root.height*root.screenScaleY*Screen.devicePixelRatio)))) : Qt.size(-1,-1)
        fillMode: Image.Stretch
        smooth: !root.available
    }
}
