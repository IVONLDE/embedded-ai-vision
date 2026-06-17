import QtQuick
import QtQuick.Controls
import "."

ComboBox {
    id: control

    popup: Popup {
        y: control.height + 2
        width: control.width
        padding: 4
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent

        background: Rectangle {
            color: Theme.panel
            border.color: Theme.border
            radius: 6
        }

        contentItem: ListView {
            clip: true
            implicitHeight: Math.min(contentHeight, 300)
            model: control.delegateModel
            currentIndex: control.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator {}
        }
    }
}
