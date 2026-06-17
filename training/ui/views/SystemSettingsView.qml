import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import ".."

Item {
    id: root
    anchors.fill: parent

    readonly property color bgDark: Theme.bg
    readonly property color panelBg: Theme.panel
    readonly property color primaryColor: Theme.primary
    readonly property color textColor: Theme.text
    readonly property color textMuted: Theme.muted
    readonly property color borderColor: Theme.border
    readonly property color successColor: Theme.success
    readonly property color tableHoverBg: Theme.hover

    property string storageRoot: ""
    property int taskMaxWorkers: 2
    property int previewMaxSamples: 100
    property int logRetentionDays: 30
    property bool settingsLoaded: false
    property string toastMessage: ""

    ListModel { id: settingsOverviewModel }
    ListModel { id: operationLogsModel }

    HelpIcon {
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.topMargin: -16
        anchors.rightMargin: -16
        title: "系统设置帮助"
        body: "本页用于查看系统运行状态，并调整全局设置。\n\n1. 顶部概览区显示数据库状态、存储目录和磁盘空间，帮助判断当前环境是否可正常导入、生成和训练数据。\n2. 主题设置可切换界面显示风格。修改后会立即应用，并通过后端设置服务持久化。\n3. 存储目录用于保存数据集、任务输出、生成样本和日志。修改前请确认新目录可读写，并预留足够磁盘空间。\n4. 并发任务数控制后台同时运行的任务数量。数值越大资源占用越高；如果机器显存或内存有限，建议保持较小值。\n5. 预览样本上限控制数据列表和样本预览的加载数量，较大的值会显示更多内容，但可能降低页面响应速度。\n6. 日志保留天数用于控制历史操作日志保存周期，便于排查问题和追踪任务操作。\n7. 操作日志区域展示最近的系统动作、资源类型和时间。点击“刷新”可重新拉取最新记录。\n8. 修改设置后如果业务页面没有立即体现，可切换页面或重启应用以确保所有模块重新读取配置。"
    }

    Connections {
        target: backendService

        function onSettingsUpdated(result) {
            var payload = result && result.data ? result.data : {}
            var themeValue = payload["ui.theme"] ? payload["ui.theme"].value : "light"
            root.storageRoot = payload["storage.root_dir"] ? String(payload["storage.root_dir"].value) : ""
            root.taskMaxWorkers = payload["task.max_workers"] ? Number(payload["task.max_workers"].value) : 2
            root.previewMaxSamples = payload["preview.max_samples"] ? Number(payload["preview.max_samples"].value) : 100
            root.logRetentionDays = payload["log.retention_days"] ? Number(payload["log.retention_days"].value) : 30

            var idxMap = {"light":0, "seamist":1, "blue":2, "ocean":3, "deepsea":4, "dark":5}
            themeSelector.currentIndex = idxMap[themeValue] !== undefined ? idxMap[themeValue] : 0

            Theme.setMode(themeValue)
            root.settingsLoaded = true
            root.refreshOverview()
        }

        function onSystemStatusUpdated(result) {
            var payload = result && result.data ? result.data : {}
            settingsOverviewModel.setProperty(0, "value", payload.database_available ? "数据库可用" : "数据库异常")
            settingsOverviewModel.setProperty(0, "status", payload.storage_available ? "运行中" : "存储异常")
            settingsOverviewModel.setProperty(1, "value", payload.storage_dir || root.storageRoot || "-")
            settingsOverviewModel.setProperty(2, "value", (payload.disk_free_gb || 0) + " GB 可用")
            settingsOverviewModel.setProperty(2, "status", (payload.disk_used_gb || 0) + " GB 已用")
        }

        function onOperationLogsUpdated(result) {
            operationLogsModel.clear()
            var items = result && result.items ? result.items : []
            for (var i = 0; i < items.length; i++) {
                operationLogsModel.append({
                    level: items[i].level || "",
                    action: items[i].action || "",
                    message: items[i].message || "",
                    createdAt: items[i].created_at || ""
                })
            }
        }
    }

    Component.onCompleted: {
        settingsOverviewModel.append({ title: "运行状态", value: "-", status: "-" })
        settingsOverviewModel.append({ title: "存储目录", value: "-", status: "后端设置" })
        settingsOverviewModel.append({ title: "磁盘状态", value: "-", status: "-" })
        backendService.getSettings()
        backendService.getSystemStatus()
        backendService.getOperationLogs(1, 8, "")
    }

    function refreshOverview() {
        if (settingsOverviewModel.count < 3) return
        settingsOverviewModel.setProperty(1, "value", root.storageRoot || "-")
    }

    function showToast(message) {
        root.toastMessage = message
        toastMsg.open()
        toastAnim.restart()
        toastCloseTimer.restart()
    }

    function persistSetting(key, value, successMessage) {
        var result = backendService.updateSetting(key, value)
        if (result && result.ok) {
            root.showToast(successMessage)
            backendService.getSettings()
            backendService.getSystemStatus()
            backendService.getOperationLogs(1, 8, "")
        } else {
            root.showToast((result && result.message) ? result.message : "设置保存失败")
        }
    }

    Popup {
        id: toastMsg
        modal: false
        closePolicy: Popup.NoAutoClose
        z: 2147483647
        x: Math.round((root.width - width) / 2)
        y: 40
        height: 40
        leftPadding: 20
        rightPadding: 20
        opacity: 0
        background: Rectangle { color: root.successColor; radius: 20 }
        contentItem: Text {
            id: toastText
            text: root.toastMessage
            color: "black"
            font.pixelSize: 14; font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        SequentialAnimation {
            id: toastAnim
            NumberAnimation { target: toastMsg; property: "opacity"; to: 1.0; duration: 300 }
        }
    }

    Timer {
        id: toastCloseTimer
        interval: 2300
        onTriggered: {
            toastMsg.opacity = 0
            toastMsg.close()
        }
    }

    Component.onDestruction: {
        toastCloseTimer.stop()
    }

    ScrollView {
        anchors.fill: parent
        contentWidth: availableWidth
        clip: true

        ColumnLayout {
            width: parent.width
            spacing: 20

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 88
                color: root.panelBg
                radius: 8
                border.color: root.borderColor
                border.width: 1

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 20
                    spacing: 4
                    Text { text: "系统设置"; color: root.textColor; font.pixelSize: 22; font.bold: true }
                    Text { text: "后端设置、运行状态和最近操作日志。"; color: root.textMuted; font.pixelSize: 13 }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 104
                color: root.panelBg
                radius: 8
                border.color: root.borderColor
                border.width: 1

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 12

                    Repeater {
                        model: settingsOverviewModel
                        delegate: Rectangle {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            color: Theme.control
                            radius: 6
                            border.color: root.borderColor
                            border.width: 1

                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 10
                                spacing: 4
                                Text { text: title; color: root.textMuted; font.pixelSize: 12; Layout.fillWidth: true; elide: Text.ElideRight }
                                Text { text: value; color: root.textColor; font.pixelSize: 13; font.bold: true; Layout.fillWidth: true; elide: Text.ElideRight }
                                Text { text: status; color: root.primaryColor; font.pixelSize: 12; Layout.fillWidth: true; elide: Text.ElideRight }
                            }
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 240
                color: root.panelBg
                radius: 8
                border.color: root.borderColor
                border.width: 1

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 20
                    spacing: 16

                    Text { text: "基础设置"; color: root.textColor; font.pixelSize: 16; font.bold: true }

                    RowLayout {
                        spacing: 16
                        Text { text: "界面主题"; color: root.textMuted; Layout.preferredWidth: 110 }
                        StableComboBox {
                            id: themeSelector
                            model: ["晨光", "海雾", "碧蓝", "海渊", "深海", "夜航"]
                            Layout.preferredWidth: 160
                            onActivated: function(index) {
                                var m = ["light","seamist","blue","ocean","deepsea","dark"]
                                var mode = index >= 0 && index < m.length ? m[index] : "light"
                                Theme.setMode(mode)
                                if (root.settingsLoaded) {
                                    root.persistSetting("ui.theme", mode, "主题设置已保存")
                                }
                            }
                        }
                    }

                    RowLayout {
                        spacing: 16
                        Text { text: "存储根目录"; color: root.textMuted; Layout.preferredWidth: 110 }
                        Rectangle {
                            Layout.fillWidth: true
                            height: 36
                            color: root.bgDark
                            radius: 4
                            border.color: root.borderColor
                            border.width: 1

                            TextInput {
                                id: storageRootInput
                                anchors.fill: parent
                                leftPadding: 10
                                verticalAlignment: TextInput.AlignVCenter
                                color: root.primaryColor
                                text: root.storageRoot
                                selectByMouse: true
                            }
                        }
                    }

                    RowLayout {
                        spacing: 16
                        Text { text: "任务并发数"; color: root.textMuted; Layout.preferredWidth: 110 }
                        SpinBox {
                            id: workerSpinBox
                            from: 1; to: 16; value: root.taskMaxWorkers
                            background: Rectangle { color: root.bgDark; border.color: root.borderColor; border.width: 1; radius: 4 }
                        }
                        Text { text: "预览上限"; color: root.textMuted; Layout.preferredWidth: 80 }
                        SpinBox {
                            id: previewSpinBox
                            from: 10; to: 1000; stepSize: 10; value: root.previewMaxSamples
                            background: Rectangle { color: root.bgDark; border.color: root.borderColor; border.width: 1; radius: 4 }
                        }
                        Text { text: "日志保留"; color: root.textMuted; Layout.preferredWidth: 80 }
                        SpinBox {
                            id: retentionSpinBox
                            from: 1; to: 365; value: root.logRetentionDays
                            background: Rectangle { color: root.bgDark; border.color: root.borderColor; border.width: 1; radius: 4 }
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 240
                color: root.panelBg
                radius: 8
                border.color: root.borderColor
                border.width: 1

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 20
                    spacing: 12

                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: "最近操作日志"; color: root.textColor; font.pixelSize: 16; font.bold: true }
                        Item { Layout.fillWidth: true }
                        Button {
                            text: "刷新"
                            background: Rectangle { color: parent.hovered ? root.tableHoverBg : root.bgDark; border.color: root.borderColor; border.width: 1; radius: 4 }
                            contentItem: Text { text: parent.text; color: root.textColor; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                            onClicked: {
                                backendService.getOperationLogs(1, 8, "")
                                root.showToast("日志已刷新")
                            }
                        }
                    }

                    ListView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        spacing: 8
                        model: operationLogsModel

                        Text {
                            visible: operationLogsModel.count === 0
                            anchors.centerIn: parent
                            text: "暂无操作日志"
                            color: root.textMuted
                            font.pixelSize: 13
                        }

                        delegate: Rectangle {
                            width: ListView.view.width
                            height: 44
                            color: index % 2 === 0 ? root.bgDark : "transparent"
                            radius: 4

                            RowLayout {
                                anchors.fill: parent
                                anchors.margins: 10
                                spacing: 12
                                Text { text: level; color: root.primaryColor; font.pixelSize: 12; font.bold: true; Layout.preferredWidth: 48 }
                                Text { text: action; color: root.textColor; font.pixelSize: 12; Layout.preferredWidth: 140; elide: Text.ElideRight }
                                Text { text: message; color: root.textMuted; font.pixelSize: 12; Layout.fillWidth: true; elide: Text.ElideRight }
                                Text { text: createdAt; color: root.textMuted; font.pixelSize: 11; Layout.preferredWidth: 180; elide: Text.ElideRight }
                            }
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }

                Button {
                    text: "恢复默认"
                    background: Rectangle { color: parent.hovered ? root.tableHoverBg : root.bgDark; border.color: root.borderColor; border.width: 1; radius: 4 }
                    contentItem: Text { text: parent.text; color: root.textColor; font.pixelSize: 13; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: {
                        themeSelector.currentIndex = 0
                        storageRootInput.text = "./data"
                        workerSpinBox.value = 2
                        previewSpinBox.value = 100
                        retentionSpinBox.value = 30
                    }
                }

                Button {
                    text: "保存全部设置"
                    background: Rectangle { color: root.primaryColor; radius: 4 }
                    contentItem: Text { text: parent.text; color: "white"; font.pixelSize: 13; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: {
                        root.persistSetting("storage.root_dir", storageRootInput.text, "存储目录已保存")
                        root.persistSetting("task.max_workers", workerSpinBox.value, "并发设置已保存")
                        root.persistSetting("preview.max_samples", previewSpinBox.value, "预览设置已保存")
                        root.persistSetting("log.retention_days", retentionSpinBox.value, "日志设置已保存")
                    }
                }
            }
        }
    }
}
