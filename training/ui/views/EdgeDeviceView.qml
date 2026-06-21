import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import ".."

/* ── 边缘设备管理页面 ────────────────────────────────────
 *
 * 功能:
 *   - 设备列表 (在线/离线状态, MQTT心跳驱动)
 *   - 实时检测数据展示 (目标数/类别统计)
 *   - 设备注册
 *   - 场景切换 / 模型推送 / 回滚 / 重启
 */

Rectangle {
    id: root
    color: Theme.bg

    property color bgDark: Theme.bg
    property color panelBg: Theme.panel
    property color primaryColor: Theme.primary
    property color secondaryColor: Theme.secondary
    property color textColor: Theme.text
    property color textMuted: Theme.muted
    property color borderColor: Theme.border
    property color successColor: Theme.success
    property color dangerColor: Theme.danger

    // ── 数据模型 ─────────────────────────────────────────
    ListModel {
        id: deviceModel
    }

    ListModel {
        id: modelVersionModel
    }

    // ── MQTT 实时状态 ────────────────────────────────────
    // 每个设备的实时遥测, key=device_id
    QtObject {
        id: liveData
        // 当前选中设备的实时数据
        property string selectedDeviceId: ""
        property int liveFrameIndex: 0
        property int liveDetectionCount: 0
        property string liveLastClass: ""
        property real liveFps: 0
        property string liveStatus: "offline"
        property var detectionHistory: []   // 最近N帧目标数
    }

    // ── 设备扫描 ────────────────────────────────────────────
    Timer {
        id: scanTimer
        interval: 6000  // 扫描需要约5秒
        repeat: false
        onTriggered: {
            var devices = backendService.scanEdgeDevices()
            if (devices.length > 0) {
                scanResultModel.clear()
                for (var i = 0; i < devices.length; i++) {
                    scanResultModel.append(devices[i])
                }
                scanResultDialog.open()
                otaStatusText.text = "发现 " + devices.length + " 台设备"
                otaStatusText.color = root.successColor
            } else {
                otaStatusText.text = "未发现设备 (确保设备已开机且在同一局域网)"
                otaStatusText.color = root.textMuted
            }
        }
    }

    ListModel {
        id: scanResultModel
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

    // ── MQTT 信号连接 ─────────────────────────────────────
    Connections {
        target: backendService

        function onEdgeDeviceOperationCompleted(result) {
            otaStatusText.text = result.message || "操作完成"
            otaStatusText.color = result.status === "success" ? root.successColor : root.dangerColor
            refreshDevices()
        }

        // 检测结果实时更新
        function onEdgeDetectionReceived(data) {
            var did = data.device_id
            if (did !== liveData.selectedDeviceId) return

            liveData.liveFrameIndex = data.frame_index
            liveData.liveDetectionCount = (data.detections || []).length

            // 统计类别
            if (data.detections && data.detections.length > 0) {
                liveData.liveLastClass = data.detections[0].class_id
            }

            // 历史记录 (最近30帧)
            var hist = liveData.detectionHistory
            hist.push(data.detections ? data.detections.length : 0)
            if (hist.length > 30) hist.shift()
            liveData.detectionHistory = hist

            // 估算 FPS (基于 timestamp_us 差值)
            detectionCounter++
        }

        // 心跳实时更新
        function onEdgeHealthReceived(data) {
            var did = data.device_id
            liveData.liveStatus = data.status

            // 更新设备列表中的状态
            for (var i = 0; i < deviceModel.count; i++) {
                if (deviceModel.get(i).device_id === did) {
                    deviceModel.setProperty(i, "status", data.status)
                    break
                }
            }

            // 如果是选中设备，更新详情
            if (did === liveData.selectedDeviceId) {
                detailPanel.deviceStatus = data.status
                heartbeatCounter++
            }
        }
    }

    // 心跳/检测计数器，用于视觉反馈
    property int heartbeatCounter: 0
    property int detectionCounter: 0

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

                // 标题 + 按钮
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

                    // MQTT 连接状态指示
                    Rectangle {
                        width: 8; height: 8; radius: 4
                        color: heartbeatCounter > 0 ? root.successColor : "#9E9E9E"
                    }
                    Text {
                        text: heartbeatCounter > 0 ? "MQTT 已连接" : "MQTT 未连接"
                        font.pixelSize: 11
                        color: root.textMuted
                    }

                    Item { Layout.fillWidth: true }

                    Button {
                        text: "刷新"
                        font.pixelSize: 12
                        onClicked: refreshDevices()
                    }

                    Button {
                        text: "扫描设备"
                        font.pixelSize: 12
                        highlighted: true
                        onClicked: {
                            otaStatusText.text = "正在扫描局域网设备..."
                            otaStatusText.color = root.textMuted
                            scanTimer.start()
                        }
                    }

                    Button {
                        text: "注册设备"
                        font.pixelSize: 12
                        highlighted: true
                        onClicked: registerDialog.open()
                    }
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
                        height: 72
                        color: model.device_id === liveData.selectedDeviceId ? Qt.rgba(0.11, 0.31, 0.85, 0.08) : root.bgDark
                        border.color: model.device_id === liveData.selectedDeviceId ? root.primaryColor : root.borderColor
                        border.width: model.device_id === liveData.selectedDeviceId ? 2 : 1
                        radius: 6

                        // MouseArea 放在按钮 RowLayout 之前声明，
                        // 这样按钮的 Z 顺序更高，点击事件不会被 MouseArea 拦截
                        MouseArea {
                            anchors.fill: parent
                            hoverEnabled: true
                            propagateComposedEvents: true
                            onEntered: parent.color = Qt.rgba(1, 1, 1, 0.05)
                            onExited: parent.color = model.device_id === liveData.selectedDeviceId ? Qt.rgba(0.11, 0.31, 0.85, 0.08) : root.bgDark
                            onClicked: {
                                liveData.selectedDeviceId = model.device_id
                                detailPanel.deviceId = model.device_id
                                detailPanel.deviceName = model.name || model.device_id
                                detailPanel.deviceHost = model.host
                                detailPanel.deviceStatus = model.status
                                detailPanel.deviceScene = model.scene || "-"
                                detailPanel.deviceModel = model.model_version || "-"
                                detailPanel.deviceFps = model.fps || 0
                                detailPanel.deviceNpu = model.npu_usage || 0
                                detailPanel.deviceCpuTemp = model.cpu_temp || 0
                                // 重置实时数据
                                liveData.liveFrameIndex = 0
                                liveData.liveDetectionCount = 0
                                liveData.detectionHistory = []
                                liveData.liveStatus = model.status
                                mouse.accepted = false
                            }
                        }

                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 12

                            // 在线状态指示灯 (脉冲动画)
                            Rectangle {
                                width: 12; height: 12; radius: 6
                                color: model.status === "online" ? root.successColor :
                                       model.status === "restarting" ? "#FF9800" : "#9E9E9E"

                                // 在线时脉冲动画
                                SequentialAnimation on opacity {
                                    running: model.status === "online"
                                    loops: Animation.Infinite
                                    NumberAnimation { from: 1.0; to: 0.4; duration: 1000 }
                                    NumberAnimation { from: 0.4; to: 1.0; duration: 1000 }
                                }
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
                                spacing: 4

                                Button {
                                    text: "场景"
                                    font.pixelSize: 11
                                    onClicked: { sceneDialog.deviceId = model.device_id; sceneDialog.open() }
                                }
                                Button {
                                    text: "推送"
                                    font.pixelSize: 11
                                    onClicked: { deployDialog.targetDeviceId = model.device_id; deployDialog.open() }
                                }
                                Button {
                                    text: "回滚"
                                    font.pixelSize: 11
                                    onClicked: {
                                        var result = backendService.rollbackDevice(model.device_id, "model")
                                        otaStatusText.text = result.message || "回滚完成"
                                        refreshDevices()
                                    }
                                }
                                Button {
                                    text: "重启"
                                    font.pixelSize: 11
                                    onClicked: {
                                        var result = backendService.restartDevice(model.device_id)
                                        otaStatusText.text = "设备重启中..."
                                        refreshDevices()
                                    }
                                }
                                Button {
                                    text: "删除"
                                    font.pixelSize: 11
                                    onClicked: {
                                        backendService.unregisterEdgeDevice(model.device_id)
                                        refreshDevices()
                                    }
                                }
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

        // ── 右侧: 实时数据 + 设备详情 + 模型版本 ────────
        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: 380
            color: root.panelBg
            border.color: root.borderColor
            border.width: 1
            radius: 8

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 12

                // ══ 实时检测数据 ════════════════════════════
                Text {
                    text: "实时检测"
                    font.pixelSize: 18
                    font.bold: true
                    color: root.textColor
                }

                Rectangle {
                    Layout.fillWidth: true
                    height: liveData.selectedDeviceId === "" ? 80 : 120
                    color: root.bgDark
                    border.color: root.borderColor
                    border.width: 1
                    radius: 6

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 6
                        visible: liveData.selectedDeviceId !== ""

                        // 帧号 + 目标数
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 16

                            ColumnLayout {
                                spacing: 2
                                Text { text: "帧号"; font.pixelSize: 11; color: root.textMuted }
                                Text {
                                    text: liveData.liveFrameIndex
                                    font.pixelSize: 22; font.bold: true
                                    color: root.primaryColor
                                }
                            }
                            ColumnLayout {
                                spacing: 2
                                Text { text: "检测目标"; font.pixelSize: 11; color: root.textMuted }
                                Text {
                                    text: liveData.liveDetectionCount
                                    font.pixelSize: 22; font.bold: true
                                    color: liveData.liveDetectionCount > 0 ? root.dangerColor : root.textMuted
                                }
                            }
                            ColumnLayout {
                                spacing: 2
                                Text { text: "状态"; font.pixelSize: 11; color: root.textMuted }
                                Text {
                                    text: liveData.liveStatus
                                    font.pixelSize: 22; font.bold: true
                                    color: liveData.liveStatus === "online" ? root.successColor : "#9E9E9E"
                                }
                            }
                        }

                        // 检测历史条形图 (最近30帧)
                        Canvas {
                            id: detectionChart
                            Layout.fillWidth: true
                            Layout.preferredHeight: 32

                            onPaint: {
                                var ctx = getContext('2d')
                                ctx.clearRect(0, 0, width, height)
                                var hist = liveData.detectionHistory
                                if (hist.length === 0) return

                                var barW = Math.max(2, width / 30 - 1)
                                var maxVal = Math.max(1, Math.max.apply(null, hist))

                                for (var i = 0; i < hist.length; i++) {
                                    var h = (hist[i] / maxVal) * (height - 4)
                                    var x = i * (barW + 1)
                                    ctx.fillStyle = hist[i] > 0 ? "#1D4ED8" : "#E0E0E0"
                                    ctx.fillRect(x, height - h, barW, h)
                                }
                            }

                            Connections {
                                target: liveData
                                function onDetectionHistoryChanged() {
                                    detectionChart.requestPaint()
                                }
                            }
                        }
                    }

                    // 未选中设备时的提示
                    Text {
                        anchors.centerIn: parent
                        visible: liveData.selectedDeviceId === ""
                        text: "点击左侧设备查看实时数据"
                        font.pixelSize: 13
                        color: root.textMuted
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    height: 1
                    color: root.borderColor
                }

                // ══ 设备详情 ════════════════════════════════
                Text {
                    text: "设备详情"
                    font.pixelSize: 16
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
                    Text { text: detailPanel.deviceId; color: root.textColor; font.pixelSize: 13; Layout.fillWidth: true; elide: Text.ElideRight }

                    Text { text: "名称:"; color: root.textMuted; font.pixelSize: 13 }
                    Text { text: detailPanel.deviceName; color: root.textColor; font.pixelSize: 13 }

                    Text { text: "IP:"; color: root.textMuted; font.pixelSize: 13 }
                    Text { text: detailPanel.deviceHost; color: root.textColor; font.pixelSize: 13 }

                    Text { text: "状态:"; color: root.textMuted; font.pixelSize: 13 }
                    Text { text: detailPanel.deviceStatus; color: detailPanel.deviceStatus === "online" ? root.successColor : "#9E9E9E"; font.pixelSize: 13 }

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

                // ══ 模型版本 ════════════════════════════════
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
                        height: 36
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
                            regDeviceId.text, regDeviceName.text, regDeviceHost.text, 50051
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

    // ── 扫描结果对话框 ────────────────────────────────────
    Dialog {
        id: scanResultDialog
        title: "发现边缘设备"
        modal: true
        anchors.centerIn: parent
        width: 500
        height: 400

        ColumnLayout {
            anchors.fill: parent
            spacing: 12

            Text {
                text: "以下设备在局域网中被发现，点击注册可添加到设备列表："
                color: root.textColor
                font.pixelSize: 14
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }

            ListView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                model: scanResultModel
                clip: true
                spacing: 8

                delegate: Rectangle {
                    width: ListView.view.width
                    height: 60
                    color: root.bgDark
                    radius: 6
                    border.color: root.borderColor
                    border.width: 1

                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 12

                        // 设备图标
                        Rectangle {
                            width: 36; height: 36; radius: 18
                            color: root.successColor

                            Text {
                                anchors.centerIn: parent
                                text: "AI"
                                font.pixelSize: 12
                                font.bold: true
                                color: "white"
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2

                            Text {
                                text: model.name || "未知设备"
                                font.pixelSize: 14
                                font.bold: true
                                color: root.textColor
                            }
                            Text {
                                text: model.host + ":" + model.port
                                font.pixelSize: 12
                                color: root.textMuted
                            }
                            Text {
                                text: model.properties ? "场景: " + (model.properties.scene || "未知") + " | 版本: " + (model.properties.app_version || "未知") : ""
                                font.pixelSize: 11
                                color: root.textMuted
                            }
                        }

                        Button {
                            text: "注册"
                            font.pixelSize: 11
                            highlighted: true
                            onClicked: {
                                var result = backendService.registerEdgeDevice(
                                    model.name || ("discovered-" + model.host),
                                    model.name || "自动发现设备",
                                    model.host,
                                    model.port || 50051
                                )
                                otaStatusText.text = result.message || "注册完成"
                                refreshDevices()
                            }
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Button {
                    text: "注册全部"
                    highlighted: true
                    onClicked: {
                        for (var i = 0; i < scanResultModel.count; i++) {
                            var item = scanResultModel.get(i)
                            backendService.registerEdgeDevice(
                                item.name || ("discovered-" + item.host),
                                item.name || "自动发现设备",
                                item.host,
                                item.port || 50051
                            )
                        }
                        refreshDevices()
                        scanResultDialog.close()
                        otaStatusText.text = "已注册 " + scanResultModel.count + " 台设备"
                    }
                }
                Item { Layout.fillWidth: true }
                Button {
                    text: "关闭"
                    onClicked: scanResultDialog.close()
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
                placeholderText: "模型文件路径 (.onnx 或 .rknn)"
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
                        var path = modelPathField.text
                        var result
                        if (path.endsWith(".onnx")) {
                            // 方案B: ONNX推送, 板子端转换
                            result = backendService.pushOnnxToDevice(
                                deployDialog.targetDeviceId,
                                modelPathField.text,
                                modelVersionField.text
                            )
                        } else {
                            // 直接推送 RKNN
                            result = backendService.pushModelToDevice(
                                deployDialog.targetDeviceId,
                                modelPathField.text,
                                modelVersionField.text
                            )
                        }
                        otaStatusText.text = result.message || "推送中..."
                        otaStatusText.color = result.status === "success" ? root.successColor : root.textMuted
                        deployDialog.close()
                    }
                }
            }
        }
    }
}
