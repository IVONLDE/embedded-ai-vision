import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

/* ── 边缘设备管理页面 ────────────────────────────────────
 *
 * 功能:
 *   - 设备列表 (在线/离线状态)
 *   - 设备注册
 *   - 场景切换
 *   - 模型推送 (OTA)
 *   - 版本回滚
 *   - 远程重启
 */

Rectangle {
    id: root
    color: Theme.bg

    // 全局颜色 (从 main_windows.qml 传入)
    property color bgDark: Theme.bg
    property color panelBg: Theme.panel
    property color primaryColor: Theme.primary
    property color secondaryColor: Theme.secondary
    property color textColor: Theme.text
    property color textMuted: Theme.muted
    property color borderColor: Theme.border

    // ── 数据模型 ─────────────────────────────────────────
    ListModel {
        id: deviceModel
    }

    ListModel {
        id: modelVersionModel
    }

    // ── 初始化 ───────────────────────────────────────────
    Component.onCompleted: {
        refreshDevices()
        refreshModelVersions()
    }

    function refreshDevices() {
        var devices = backendService.listEdgeDevices("")
        deviceModel.clear()
        for (var i = 0; i < devices.length; i++) {
            deviceModel.append(devices[i])
        }
    }

    function refreshModelVersions() {
        var versions = backendService.listModelVersions("", "")
        modelVersionModel.clear()
        for (var i = 0; i < versions.length; i++) {
            modelVersionModel.append(versions[i])
        }
    }

    // ── OTA 操作反馈 ─────────────────────────────────────
    Connections {
        target: backendService
        function onEdgeDeviceOperationCompleted(result) {
            otaStatusText.text = result.message || "操作完成"
            otaStatusText.color = result.status === "success" ? "#4CAF50" : "#F44336"
            refreshDevices()
        }
    }

    // ── 主布局 ───────────────────────────────────────────
    RowLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 16

        // ── 左侧: 设备列表 ──────────────────────────────
        Rectangle {
            Layout.fillHeight: true
            Layout.fillWidth: true
            Layout.minimumWidth: 400
            color: root.panelBg
            border.color: root.borderColor
            border.width: 1
            radius: 8

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 12

                // 标题 + 注册按钮
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12

                    Text {
                        text: "边缘设备"
                        font.pixelSize: 18
                        font.bold: true
                        color: root.textColor
                    }

                    Text {
                        text: deviceModel.count + " 台设备"
                        font.pixelSize: 13
                        color: root.textMuted
                    }

                    Button {
                        text: "刷新"
                        highlighted: true
                        onClicked: refreshDevices()
                    }

                    Button {
                        text: "注册设备"
                        highlighted: true
                        onClicked: registerDialog.open()
                    }

                    Item { Layout.fillWidth: true }
                }

                // 设备列表
                ListView {
                    id: deviceListView
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    model: deviceModel
                    clip: true
                    spacing: 8

                    delegate: Rectangle {
                        width: deviceListView.width
                        height: 80
                        color: root.bgDark
                        border.color: root.borderColor
                        border.width: 1
                        radius: 6

                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 12

                            // 在线状态指示灯
                            Rectangle {
                                width: 12; height: 12
                                radius: 6
                                color: model.status === "online" ? "#4CAF50" :
                                       model.status === "restarting" ? "#FF9800" : "#9E9E9E"
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2

                                Text {
                                    text: model.name || model.device_id
                                    font.pixelSize: 15
                                    font.bold: true
                                    color: root.textColor
                                }
                                Text {
                                    text: model.host + (model.scene ? " | 场景: " + model.scene : "")
                                    font.pixelSize: 12
                                    color: root.textMuted
                                }
                                Text {
                                    text: "模型: " + (model.model_version || "未知") +
                                          (model.fps > 0 ? " | FPS: " + Math.round(model.fps) : "")
                                    font.pixelSize: 12
                                    color: root.textMuted
                                }
                            }

                            // 操作按钮
                            RowLayout {
                                spacing: 6

                                Button {
                                    text: "场景"
                                    font.pixelSize: 12
                                    onClicked: sceneDialog.deviceId = model.device_id; sceneDialog.open()
                                }

                                Button {
                                    text: "推送"
                                    font.pixelSize: 12
                                    onClicked: deployDialog.targetDeviceId = model.device_id; deployDialog.open()
                                }

                                Button {
                                    text: "回滚"
                                    font.pixelSize: 12
                                    onClicked: {
                                        var result = backendService.rollbackDevice(model.device_id, "model")
                                        otaStatusText.text = result.message || "回滚完成"
                                        refreshDevices()
                                    }
                                }

                                Button {
                                    text: "重启"
                                    font.pixelSize: 12
                                    onClicked: {
                                        var result = backendService.restartDevice(model.device_id)
                                        otaStatusText.text = "设备重启中..."
                                        refreshDevices()
                                    }
                                }

                                Button {
                                    text: "删除"
                                    font.pixelSize: 12
                                    onClicked: {
                                        backendService.unregisterEdgeDevice(model.device_id)
                                        refreshDevices()
                                    }
                                }
                            }
                        }

                        MouseArea {
                            anchors.fill: parent
                            hoverEnabled: true
                            onEntered: parent.color = Qt.rgba(1, 1, 1, 0.05)
                            onExited: parent.color = root.bgDark
                            onClicked: {
                                // 显示设备详细信息
                                detailPanel.deviceId = model.device_id
                                detailPanel.deviceName = model.name || model.device_id
                                detailPanel.deviceHost = model.host
                                detailPanel.deviceStatus = model.status
                                detailPanel.deviceScene = model.scene || "-"
                                detailPanel.deviceModel = model.model_version || "-"
                                detailPanel.deviceFps = model.fps || 0
                                detailPanel.deviceNpu = model.npu_usage || 0
                                detailPanel.deviceCpuTemp = model.cpu_temp || 0
                            }
                        }
                    }
                }

                // OTA 状态提示
                Text {
                    id: otaStatusText
                    Layout.fillWidth: true
                    text: ""
                    font.pixelSize: 13
                    color: root.textMuted
                    wrapMode: Text.WordWrap
                }
            }
        }

        // ── 右侧: 设备详情 + 模型版本 ────────────────────
        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: 350
            color: root.panelBg
            border.color: root.borderColor
            border.width: 1
            radius: 8

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 12

                // 设备详情
                Text {
                    text: "设备详情"
                    font.pixelSize: 18
                    font.bold: true
                    color: root.textColor
                }

                QtObject {
                    id: detailPanel
                    property string deviceId: ""
                    property string deviceName: "-"
                    property string deviceHost: "-"
                    property string deviceStatus: "-"
                    property string deviceScene: "-"
                    property string deviceModel: "-"
                    property real deviceFps: 0
                    property real deviceNpu: 0
                    property real deviceCpuTemp: 0
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    columnSpacing: 8
                    rowSpacing: 4

                    Text { text: "设备ID:"; color: root.textMuted; font.pixelSize: 13 }
                    Text { text: detailPanel.deviceId; color: root.textColor; font.pixelSize: 13; Layout.fillWidth: true }

                    Text { text: "名称:"; color: root.textMuted; font.pixelSize: 13 }
                    Text { text: detailPanel.deviceName; color: root.textColor; font.pixelSize: 13 }

                    Text { text: "IP:"; color: root.textMuted; font.pixelSize: 13 }
                    Text { text: detailPanel.deviceHost; color: root.textColor; font.pixelSize: 13 }

                    Text { text: "状态:"; color: root.textMuted; font.pixelSize: 13 }
                    Text { text: detailPanel.deviceStatus; color: detailPanel.deviceStatus === "online" ? "#4CAF50" : "#9E9E9E"; font.pixelSize: 13 }

                    Text { text: "场景:"; color: root.textMuted; font.pixelSize: 13 }
                    Text { text: detailPanel.deviceScene; color: root.textColor; font.pixelSize: 13 }

                    Text { text: "模型版本:"; color: root.textMuted; font.pixelSize: 13 }
                    Text { text: detailPanel.deviceModel; color: root.textColor; font.pixelSize: 13 }

                    Text { text: "FPS:"; color: root.textMuted; font.pixelSize: 13 }
                    Text { text: Math.round(detailPanel.deviceFps); color: root.textColor; font.pixelSize: 13 }

                    Text { text: "NPU:"; color: root.textMuted; font.pixelSize: 13 }
                    Text { text: Math.round(detailPanel.deviceNpu) + "%"; color: root.textColor; font.pixelSize: 13 }

                    Text { text: "CPU温度:"; color: root.textMuted; font.pixelSize: 13 }
                    Text { text: Math.round(detailPanel.deviceCpuTemp) + "°C"; color: root.textColor; font.pixelSize: 13 }
                }

                Rectangle {
                    Layout.fillWidth: true
                    height: 1
                    color: root.borderColor
                }

                // 模型版本列表
                Text {
                    text: "模型版本"
                    font.pixelSize: 16
                    font.bold: true
                    color: root.textColor
                }

                ListView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    model: modelVersionModel
                    clip: true
                    spacing: 4

                    delegate: Rectangle {
                        width: parent.width
                        height: 40
                        color: root.bgDark
                        radius: 4

                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 8
                            spacing: 8

                            Text {
                                text: model.name
                                font.pixelSize: 13
                                font.bold: true
                                color: root.textColor
                            }
                            Text {
                                text: "v" + model.version
                                font.pixelSize: 12
                                color: root.primaryColor
                            }
                            Text {
                                text: model.scene
                                font.pixelSize: 12
                                color: root.textMuted
                            }
                            Item { Layout.fillWidth: true }
                            Text {
                                text: model.quantization
                                font.pixelSize: 11
                                color: root.textMuted
                            }
                        }
                    }
                }
            }
        }
    }

    // ── 注册设备对话框 ───────────────────────────────────
    Dialog {
        id: registerDialog
        title: "注册边缘设备"
        modal: true
        anchors.centerIn: parent

        ColumnLayout {
            spacing: 12

            TextField {
                id: regDeviceId
                placeholderText: "设备ID (如 rk3399pro-edge-001)"
                Layout.fillWidth: true
            }
            TextField {
                id: regDeviceName
                placeholderText: "设备名称 (如 入口摄像头)"
                Layout.fillWidth: true
            }
            TextField {
                id: regDeviceHost
                placeholderText: "IP地址 (如 192.168.1.50)"
                Layout.fillWidth: true
            }

            RowLayout {
                Layout.fillWidth: true
                Button {
                    text: "取消"
                    onClicked: registerDialog.close()
                }
                Button {
                    text: "注册"
                    highlighted: true
                    onClicked: {
                        var result = backendService.registerEdgeDevice(
                            regDeviceId.text, regDeviceName.text, regDeviceHost.text
                        )
                        otaStatusText.text = result.message || "注册完成"
                        refreshDevices()
                        registerDialog.close()
                    }
                }
            }
        }
    }

    // ── 场景切换对话框 ───────────────────────────────────
    Dialog {
        id: sceneDialog
        title: "切换推理场景"
        modal: true
        anchors.centerIn: parent

        property string deviceId: ""

        ColumnLayout {
            spacing: 12

            Text {
                text: "为设备 " + sceneDialog.deviceId + " 选择场景:"
                color: root.textColor
                font.pixelSize: 14
            }

            ComboBox {
                id: sceneCombo
                Layout.fillWidth: true
                model: ["face", "body", "vehicle", "defect"]
            }

            RowLayout {
                Layout.fillWidth: true
                Button { text: "取消"; onClicked: sceneDialog.close() }
                Button {
                    text: "切换"
                    highlighted: true
                    onClicked: {
                        var result = backendService.switchDeviceScene(
                            sceneDialog.deviceId, sceneCombo.currentText
                        )
                        otaStatusText.text = result.message || "切换完成"
                        refreshDevices()
                        sceneDialog.close()
                    }
                }
            }
        }
    }

    // ── 模型推送对话框 ───────────────────────────────────
    Dialog {
        id: deployDialog
        title: "推送模型到设备"
        modal: true
        anchors.centerIn: parent
        width: 400

        property string targetDeviceId: ""

        ColumnLayout {
            spacing: 12

            Text {
                text: "目标设备: " + deployDialog.targetDeviceId
                color: root.textColor
                font.pixelSize: 14
            }

            TextField {
                id: modelPathField
                placeholderText: "模型文件路径 (.rknn)"
                Layout.fillWidth: true
            }

            TextField {
                id: modelVersionField
                placeholderText: "模型版本号 (如 v2.0)"
                Layout.fillWidth: true
            }

            RowLayout {
                Layout.fillWidth: true
                Button { text: "取消"; onClicked: deployDialog.close() }
                Button {
                    text: "推送"
                    highlighted: true
                    onClicked: {
                        otaStatusText.text = "推送模型中..."
                        var result = backendService.pushModelToDevice(
                            deployDialog.targetDeviceId,
                            modelPathField.text,
                            modelVersionField.text
                        )
                        otaStatusText.text = result.message || "推送完成"
                        otaStatusText.color = result.status === "success" ? "#4CAF50" : "#F44336"
                        refreshDevices()
                        deployDialog.close()
                    }
                }
            }
        }
    }
}
