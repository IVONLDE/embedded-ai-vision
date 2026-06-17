import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    width: 32
    height: 32
    z: 100

    property string title: "操作帮助"
    property string body: ""

    Rectangle {
        anchors.fill: parent
        radius: 16
        color: helpMouse.containsMouse ? Theme.primary : Theme.control
        border.color: Theme.border
        border.width: 1

        Text {
            text: "?"
            anchors.centerIn: parent
            color: helpMouse.containsMouse ? "#FFFFFF" : Theme.primary
            font.pixelSize: 16
            font.bold: true
        }

        MouseArea {
            id: helpMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: helpPopup.open()
        }
    }

    Popup {
        id: helpPopup
        width: 360
        height: Math.max(220, Math.min(520, helpBody.contentHeight + 104))
        modal: false
        focus: true
        x: Math.min(0, root.width - width)
        y: root.height + 8
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle {
            color: Theme.panel
            border.color: Theme.border
            border.width: 1
            radius: 8
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 18
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                Text {
                    text: root.title
                    color: Theme.text
                    font.pixelSize: 16
                    font.bold: true
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
                Button {
                    id: closeButton
                    text: "关闭"
                    Layout.preferredWidth: 58
                    Layout.preferredHeight: 28
                    background: Rectangle {
                        color: "transparent"
                        border.color: Theme.border
                        radius: 4
                    }
                    contentItem: Text {
                        text: closeButton.text
                        color: Theme.muted
                        font.pixelSize: 12
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: helpPopup.close()
                }
            }

            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }

            ScrollView {
                id: helpScroll
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true

                Text {
                    id: helpBody
                    width: helpScroll.availableWidth
                    text: root.body
                    color: Theme.muted
                    font.pixelSize: 13
                    lineHeight: 1.35
                    wrapMode: Text.WordWrap
                }
            }
        }
    }
}
