import QtQuick
import QtQuick.Controls.Basic as Basic

// Measure the complete caption in the actual label font. Never elide half a
// key combination, or let hiding the hint change a button's preferred width.
Basic.Label {
    id: label
    required property string title
    property string keyHint: ""
    readonly property string fullCaption: keyHint ? title + " (" + keyHint + ")" : title
    readonly property real preferredWidth: Math.ceil(measure.implicitWidth)
    property real captionWidth: width
    // Measure independently of the visible label's constrained width. The
    // button also uses this width when a dialog changes its default action.
    Text {
        id: measure
        visible: false
        font: label.font
        textFormat: label.textFormat
        text: label.fullCaption
    }
    text: keyHint && preferredWidth <= captionWidth ? fullCaption : title
    maximumLineCount: 1
    wrapMode: Text.NoWrap
    textFormat: Text.PlainText
    elide: Text.ElideRight
}
