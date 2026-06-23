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
            liveData.liveStatus = "online"

            // 统计类别
            if (data.detections && data.detections.length > 0) {
                liveData.liveLastClass = data.detections[0].class_id
            }

            // 历史记录 (最近30帧)
            var hist = liveData.detectionHistory
            hist.push(data.detections ? data.detections.length : 0)
            if (hist.length > 30) hist.shift()
            liveData.detectionHistory = hist

            // 更新设备列表中的状态
            for (var i = 0; i < deviceModel.count; i++) {
                if (deviceModel.get(i).device_id === did) {
                    deviceModel.setProperty(i, "status", "online")
                    break
                }
            }

            // 更新详情面板
            detailPanel.deviceStatus = "online"
            detectionCounter++
        }

        // 心跳实时更新 (含遥测: CPU温度、GPU温度、NPU、FPS、内存等)
        function onEdgeHealthReceived(data) {
            var did = data.device_id
            liveData.liveStatus = data.status

            // 更新遥测数据
            if (data.fps !== undefined) liveData.liveFps = data.fps
            if (data.npu_usage !== undefined) detailPanel.deviceNpu = data.npu_usage
            if (data.cpu_temp !== undefined) detailPanel.deviceCpuTemp = data.cpu_temp
            if (data.gpu_temp !== undefined) detailPanel.deviceGpuTemp = data.gpu_temp
            if (data.mem_total_mb !== undefined) detailPanel.memTotalMb = data.mem_total_mb
            if (data.mem_used_mb !== undefined) detailPanel.memUsedMb = data.mem_used_mb
            if (data.mem_avail_mb !== undefined) detailPanel.memAvailMb = data.mem_avail_mb
            if (data.disk_total !== undefined) detailPanel.diskTotal = data.disk_total
            if (data.disk_used !== undefined) detailPanel.diskUsed = data.disk_used
            if (data.disk_free !== undefined) detailPanel.diskFree = data.disk_free
            if (data.disk_pct !== undefined) detailPanel.diskPct = data.disk_pct
            if (data.proc_cpu_pct !== undefined) detailPanel.procCpuPct = data.proc_cpu_pct
            if (data.proc_mem_pct !== undefined) detailPanel.procMemPct = data.proc_mem_pct
            if (data.load1 !== undefined) detailPanel.load1 = data.load1
            if (data.load5 !== undefined) detailPanel.load5 = data.load5
            if (data.load15 !== undefined) detailPanel.load15 = data.load15
            if (data.uptime_sec !== undefined) detailPanel.uptimeSec = data.uptime_sec
            if (data.cpu_cores !== undefined) detailPanel.cpuCores = data.cpu_cores
            if (data.kernel !== undefined) detailPanel.kernel = data.kernel
            if (data.os_name !== undefined) detailPanel.osName = data.os_name
            if (data.cpu_part !== undefined) detailPanel.cpuPart = data.cpu_part
            if (data.video_devs !== undefined) detailPanel.videoDevs = data.video_devs
            if (data.serial_ports !== undefined) detailPanel.serialPorts = data.serial_ports
            if (data.i2c_buses !== undefined) detailPanel.i2cBuses = data.i2c_buses
            if (data.usb_count !== undefined) detailPanel.usbCount = data.usb_count

            // 更新设备列表中的状态
            for (var i = 0; i < deviceModel.count; i++) {
                if (deviceModel.get(i).device_id === did) {
                    deviceModel.setProperty(i, "status", data.status)
                    if (data.fps !== undefined) deviceModel.setProperty(i, "fps", data.fps)
                    if (data.npu_usage !== undefined) deviceModel.setProperty(i, "npu_usage", data.npu_usage)
                    if (data.cpu_temp !== undefined) deviceModel.setProperty(i, "cpu_temp", data.cpu_temp)
                    break
                }
            }

            // 如果是选中设备，更新详情
            if (did === liveData.selectedDeviceId) {
                detailPanel.deviceStatus = data.status
                if (data.fps !== undefined) detailPanel.deviceFps = data.fps
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

                            // 操作按钮 — 常用操作直接显示，其余收入"更多"菜单
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
                                    text: "录制"
                                    font.pixelSize: 11
                                    highlighted: true
                                    onClicked: {
                                        var result = backendService.startDeviceRecording(model.device_id)
                                        otaStatusText.text = result.message || "录制命令已发送"
                                        otaStatusText.color = result.status === "success" ? root.successColor : root.dangerColor
                                    }
                                }
                                Button {
                                    text: "RTSP"
                                    font.pixelSize: 11
                                    highlighted: true
                                    onClicked: {
                                        var result = backendService.startDeviceRtsp(model.device_id)
                                        otaStatusText.text = result.message || "RTSP 启动命令已发送"
                                        otaStatusText.color = result.status === "success" ? root.successColor : root.dangerColor
                                    }
                                }

                                // "更多"下拉菜单 — 管理操作
                                Button {
                                    text: "更多 ▾"
                                    font.pixelSize: 11
                                    onClicked: {
                                        moreMenu.targetDeviceId = model.device_id
                                        moreMenu.targetDeviceName = model.name || model.device_id
                                        moreMenu.popup()
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
            Layout.preferredWidth: 420
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
                    property real deviceGpuTemp: 0
                    property int memTotalMb: 0
                    property int memUsedMb: 0
                    property int memAvailMb: 0
                    property string diskTotal: "-"
                    property string diskUsed: "-"
                    property string diskFree: "-"
                    property string diskPct: "-"
                    property real procCpuPct: 0
                    property real procMemPct: 0
                    property string load1: "0"
                    property string load5: "0"
                    property string load15: "0"
                    property int uptimeSec: 0
                    property int cpuCores: 0
                    property string kernel: "-"
                    property string osName: "-"
                    property string cpuPart: "-"
                    property int videoDevs: 0
                    property string serialPorts: "-"
                    property string i2cBuses: "-"
                    property int usbCount: 0
                }

                ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    contentWidth: availableWidth

                    ColumnLayout {
                        width: parent.width
                        spacing: 8
                        visible: liveData.selectedDeviceId !== ""

                        // ══ 1. 实时检测 ═════════════════════════
                        Rectangle {
                            Layout.fillWidth: true; Layout.preferredHeight: 110
                            color: root.bgDark; border.color: root.borderColor; border.width: 1; radius: 6
                            ColumnLayout {
                                anchors.fill: parent; anchors.margins: 12; spacing: 6
                                Text { text: "实时检测"; font.pixelSize: 14; font.bold: true; color: root.primaryColor }
                                RowLayout {
                                    Layout.fillWidth: true; spacing: 12
                                    ColumnLayout { spacing: 2
                                        Text { text: "帧号"; font.pixelSize: 11; color: root.textMuted }
                                        Text { text: liveData.liveFrameIndex; font.pixelSize: 20; font.bold: true; color: root.primaryColor }
                                    }
                                    ColumnLayout { spacing: 2
                                        Text { text: "检测目标"; font.pixelSize: 11; color: root.textMuted }
                                        Text { text: liveData.liveDetectionCount; font.pixelSize: 20; font.bold: true; color: liveData.liveDetectionCount > 0 ? root.dangerColor : root.textMuted }
                                    }
                                    ColumnLayout { spacing: 2
                                        Text { text: "FPS"; font.pixelSize: 11; color: root.textMuted }
                                        Text { text: Math.round(detailPanel.deviceFps); font.pixelSize: 20; font.bold: true; color: root.successColor }
                                    }
                                    ColumnLayout { spacing: 2
                                        Text { text: "状态"; font.pixelSize: 11; color: root.textMuted }
                                        Text { text: liveData.liveStatus; font.pixelSize: 20; font.bold: true; color: liveData.liveStatus === "online" ? root.successColor : "#9E9E9E" }
                                    }
                                }
                            }
                        }

                        // ══ 2. 系统资源 (带进度条) ════════════════
                        Rectangle {
                            Layout.fillWidth: true; Layout.preferredHeight: 195
                            color: root.bgDark; border.color: root.borderColor; border.width: 1; radius: 6
                            ColumnLayout {
                                anchors.fill: parent; anchors.margins: 12; spacing: 5
                                Text { text: "系统资源"; font.pixelSize: 14; font.bold: true; color: root.primaryColor }
                                RowLayout { spacing: 6
                                    Text { text: "CPU温度"; color: root.textMuted; font.pixelSize: 12; Layout.preferredWidth: 55 }
                                    Rectangle { Layout.fillWidth: true; height: 14; radius: 3; color: Qt.rgba(0,0,0,0.2)
                                        Rectangle { height: 14; radius: 3; width: Math.min(parent.width, parent.width * detailPanel.deviceCpuTemp / 100)
                                            color: detailPanel.deviceCpuTemp > 70 ? root.dangerColor : (detailPanel.deviceCpuTemp > 50 ? "#FF9800" : root.successColor) } }
                                    Text { text: Math.round(detailPanel.deviceCpuTemp) + "°C"; color: root.textColor; font.pixelSize: 12; Layout.preferredWidth: 38 }
                                }
                                RowLayout { spacing: 6
                                    Text { text: "GPU温度"; color: root.textMuted; font.pixelSize: 12; Layout.preferredWidth: 55 }
                                    Rectangle { Layout.fillWidth: true; height: 14; radius: 3; color: Qt.rgba(0,0,0,0.2)
                                        Rectangle { height: 14; radius: 3; width: Math.min(parent.width, parent.width * detailPanel.deviceGpuTemp / 100)
                                            color: detailPanel.deviceGpuTemp > 70 ? root.dangerColor : (detailPanel.deviceGpuTemp > 50 ? "#FF9800" : root.successColor) } }
                                    Text { text: Math.round(detailPanel.deviceGpuTemp) + "°C"; color: root.textColor; font.pixelSize: 12; Layout.preferredWidth: 38 }
                                }
                                RowLayout { spacing: 6
                                    Text { text: "NPU使用"; color: root.textMuted; font.pixelSize: 12; Layout.preferredWidth: 55 }
                                    Rectangle { Layout.fillWidth: true; height: 14; radius: 3; color: Qt.rgba(0,0,0,0.2)
                                        Rectangle { height: 14; radius: 3; width: Math.min(parent.width, parent.width * detailPanel.deviceNpu / 100)
                                            color: detailPanel.deviceNpu > 80 ? root.dangerColor : root.primaryColor } }
                                    Text { text: Math.round(detailPanel.deviceNpu) + "%"; color: root.textColor; font.pixelSize: 12; Layout.preferredWidth: 38 }
                                }
                                RowLayout { spacing: 6
                                    Text { text: "推理CPU"; color: root.textMuted; font.pixelSize: 12; Layout.preferredWidth: 55 }
                                    Rectangle { Layout.fillWidth: true; height: 14; radius: 3; color: Qt.rgba(0,0,0,0.2)
                                        Rectangle { height: 14; radius: 3; width: Math.min(parent.width, parent.width * detailPanel.procCpuPct / 200)
                                            color: root.secondaryColor } }
                                    Text { text: Math.round(detailPanel.procCpuPct) + "%"; color: root.textColor; font.pixelSize: 12; Layout.preferredWidth: 38 }
                                }
                                RowLayout { spacing: 6
                                    Text { text: "推理内存"; color: root.textMuted; font.pixelSize: 12; Layout.preferredWidth: 55 }
                                    Rectangle { Layout.fillWidth: true; height: 14; radius: 3; color: Qt.rgba(0,0,0,0.2)
                                        Rectangle { height: 14; radius: 3; width: Math.min(parent.width, parent.width * detailPanel.procMemPct / 100)
                                            color: root.secondaryColor } }
                                    Text { text: Math.round(detailPanel.procMemPct * 10) / 10 + "%"; color: root.textColor; font.pixelSize: 12; Layout.preferredWidth: 38 }
                                }
                            }
                        }

                        // ══ 3. 内存/磁盘/负载 ═════════════════════
                        Rectangle {
                            Layout.fillWidth: true; Layout.preferredHeight: 115
                            color: root.bgDark; border.color: root.borderColor; border.width: 1; radius: 6
                            ColumnLayout {
                                anchors.fill: parent; anchors.margins: 12; spacing: 3
                                Text { text: "内存 & 磁盘 & 负载"; font.pixelSize: 14; font.bold: true; color: root.primaryColor }
                                RowLayout { spacing: 4
                                    Text { text: "内存:"; color: root.textMuted; font.pixelSize: 12; Layout.preferredWidth: 45 }
                                    Text { text: detailPanel.memUsedMb + " / " + detailPanel.memTotalMb + " MB"; color: root.textColor; font.pixelSize: 12 }
                                    Text { text: "(可用 " + detailPanel.memAvailMb + " MB)"; color: root.successColor; font.pixelSize: 11 }
                                }
                                RowLayout { spacing: 4
                                    Text { text: "磁盘:"; color: root.textMuted; font.pixelSize: 12; Layout.preferredWidth: 45 }
                                    Text { text: detailPanel.diskUsed + " / " + detailPanel.diskTotal + " (剩余 " + detailPanel.diskFree + ")"; color: root.textColor; font.pixelSize: 12 }
                                    Text { text: detailPanel.diskPct; color: detailPanel.diskPct > "80%" ? root.dangerColor : root.textMuted; font.pixelSize: 11 }
                                }
                                RowLayout { spacing: 4
                                    Text { text: "负载:"; color: root.textMuted; font.pixelSize: 12; Layout.preferredWidth: 45 }
                                    Text { text: "1min " + detailPanel.load1 + "  5min " + detailPanel.load5 + "  15min " + detailPanel.load15; color: root.textColor; font.pixelSize: 12 }
                                }
                                RowLayout { spacing: 4
                                    Text { text: "运行:"; color: root.textMuted; font.pixelSize: 12; Layout.preferredWidth: 45 }
                                    Text { text: detailPanel.uptimeSec > 0 ? formatUptime(detailPanel.uptimeSec) : "-"; color: root.textColor; font.pixelSize: 12 }
                                }
                            }
                        }

                        // ══ 4. 硬件信息 ══════════════════════════
                        Rectangle {
                            Layout.fillWidth: true; Layout.preferredHeight: 175
                            color: root.bgDark; border.color: root.borderColor; border.width: 1; radius: 6
                            ColumnLayout {
                                anchors.fill: parent; anchors.margins: 12; spacing: 3
                                Text { text: "硬件信息"; font.pixelSize: 14; font.bold: true; color: root.primaryColor }
                                RowLayout { spacing: 4
                                    Text { text: "系统:"; color: root.textMuted; font.pixelSize: 12; Layout.preferredWidth: 45 }
                                    Text { text: detailPanel.osName; color: root.textColor; font.pixelSize: 12; elide: Text.ElideRight }
                                }
                                RowLayout { spacing: 4
                                    Text { text: "内核:"; color: root.textMuted; font.pixelSize: 12; Layout.preferredWidth: 45 }
                                    Text { text: detailPanel.kernel; color: root.textColor; font.pixelSize: 12 }
                                }
                                RowLayout { spacing: 4
                                    Text { text: "CPU:"; color: root.textMuted; font.pixelSize: 12; Layout.preferredWidth: 45 }
                                    Text { text: detailPanel.cpuCores + " 核 (ARM part " + detailPanel.cpuPart + ")"; color: root.textColor; font.pixelSize: 12 }
                                }
                                RowLayout { spacing: 4
                                    Text { text: "摄像头:"; color: root.textMuted; font.pixelSize: 12; Layout.preferredWidth: 45 }
                                    Text { text: detailPanel.videoDevs + " 个 (/dev/video*)"; color: root.textColor; font.pixelSize: 12 }
                                }
                                RowLayout { spacing: 4
                                    Text { text: "串口:"; color: root.textMuted; font.pixelSize: 12; Layout.preferredWidth: 45 }
                                    Text { text: detailPanel.serialPorts !== "-" && detailPanel.serialPorts !== "" ? detailPanel.serialPorts : "无"; color: root.textColor; font.pixelSize: 12; elide: Text.ElideRight }
                                }
                                RowLayout { spacing: 4
                                    Text { text: "I2C:"; color: root.textMuted; font.pixelSize: 12; Layout.preferredWidth: 45 }
                                    Text { text: detailPanel.i2cBuses !== "-" && detailPanel.i2cBuses !== "" ? detailPanel.i2cBuses : "无"; color: root.textColor; font.pixelSize: 12; elide: Text.ElideRight }
                                }
                                RowLayout { spacing: 4
                                    Text { text: "USB:"; color: root.textMuted; font.pixelSize: 12; Layout.preferredWidth: 45 }
                                    Text { text: detailPanel.usbCount + " 个设备"; color: root.textColor; font.pixelSize: 12 }
                                }
                            }
                        }

                        // ══ 5. 设备信息 ══════════════════════════
                        Rectangle {
                            Layout.fillWidth: true; Layout.preferredHeight: 140
                            color: root.bgDark; border.color: root.borderColor; border.width: 1; radius: 6
                            ColumnLayout {
                                anchors.fill: parent; anchors.margins: 12; spacing: 3
                                Text { text: "设备信息"; font.pixelSize: 14; font.bold: true; color: root.primaryColor }
                                RowLayout { spacing: 4
                                    Text { text: "设备ID:"; color: root.textMuted; font.pixelSize: 12; Layout.preferredWidth: 55 }
                                    Text { text: detailPanel.deviceId; color: root.textColor; font.pixelSize: 12; elide: Text.ElideRight }
                                }
                                RowLayout { spacing: 4
                                    Text { text: "名称:"; color: root.textMuted; font.pixelSize: 12; Layout.preferredWidth: 55 }
                                    Text { text: detailPanel.deviceName; color: root.textColor; font.pixelSize: 12 }
                                }
                                RowLayout { spacing: 4
                                    Text { text: "IP:"; color: root.textMuted; font.pixelSize: 12; Layout.preferredWidth: 55 }
                                    Text { text: detailPanel.deviceHost; color: root.textColor; font.pixelSize: 12 }
                                }
                                RowLayout { spacing: 4
                                    Text { text: "状态:"; color: root.textMuted; font.pixelSize: 12; Layout.preferredWidth: 55 }
                                    Text { text: detailPanel.deviceStatus; color: detailPanel.deviceStatus === "online" ? root.successColor : "#9E9E9E"; font.pixelSize: 12; font.bold: true }
                                }
                                RowLayout { spacing: 4
                                    Text { text: "场景:"; color: root.textMuted; font.pixelSize: 12; Layout.preferredWidth: 55 }
                                    Text { text: detailPanel.deviceScene; color: root.textColor; font.pixelSize: 12 }
                                }
                                RowLayout { spacing: 4
                                    Text { text: "模型:"; color: root.textMuted; font.pixelSize: 12; Layout.preferredWidth: 55 }
                                    Text { text: detailPanel.deviceModel; color: root.textColor; font.pixelSize: 12; elide: Text.ElideRight }
                                }
                            }
                        }
                    }
                }

                // 未选中设备时的提示
                Text {
                    Layout.alignment: Qt.AlignCenter
                    visible: liveData.selectedDeviceId === ""
                    text: "点击左侧设备查看实时数据"
                    font.pixelSize: 13
                    color: root.textMuted
                }
            }
        }
    }

    // ── 工具函数 ──────────────────────────────────────────
    function formatUptime(sec) {
        var d = Math.floor(sec / 86400)
        var h = Math.floor((sec % 86400) / 3600)
        var m = Math.floor((sec % 3600) / 60)
        if (d > 0) return d + "天" + h + "小时"
        if (h > 0) return h + "小时" + m + "分"
        return m + "分钟"
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

    // ── "更多"操作菜单 ───────────────────────────────────
    Menu {
        id: moreMenu

        property string targetDeviceId: ""
        property string targetDeviceName: ""

        MenuItem {
            text: "停止录制"
            onTriggered: {
                var result = backendService.stopDeviceRecording(moreMenu.targetDeviceId)
                otaStatusText.text = result.message || "停止录制命令已发送"
                otaStatusText.color = result.status === "success" ? root.successColor : root.dangerColor
            }
        }
        MenuItem {
            text: "回滚模型"
            onTriggered: {
                var result = backendService.rollbackDevice(moreMenu.targetDeviceId, "model")
                otaStatusText.text = result.message || "回滚完成"
                otaStatusText.color = result.status === "success" ? root.successColor : root.dangerColor
                refreshDevices()
            }
        }
        MenuItem {
            text: "重启设备"
            onTriggered: {
                var result = backendService.restartDevice(moreMenu.targetDeviceId)
                otaStatusText.text = "设备重启中..."
                otaStatusText.color = root.textMuted
                refreshDevices()
            }
        }
        MenuSeparator { }
        MenuItem {
            text: "删除设备"
            onTriggered: {
                deleteConfirmDialog.targetDeviceId = moreMenu.targetDeviceId
                deleteConfirmDialog.targetDeviceName = moreMenu.targetDeviceName
                deleteConfirmDialog.open()
            }
        }
    }

    // ── 删除确认对话框 ───────────────────────────────────
    Dialog {
        id: deleteConfirmDialog
        title: "确认删除"
        modal: true
        anchors.centerIn: parent

        property string targetDeviceId: ""
        property string targetDeviceName: ""

        ColumnLayout {
            spacing: 12

            Text {
                text: "确定要删除设备 \"" + deleteConfirmDialog.targetDeviceName + "\" 吗？"
                color: root.textColor
                font.pixelSize: 14
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }

            Text {
                text: "此操作将永久删除设备记录，无法撤销。"
                color: root.dangerColor
                font.pixelSize: 12
            }

            RowLayout {
                Layout.fillWidth: true
                Button {
                    text: "取消"
                    onClicked: deleteConfirmDialog.close()
                }
                Item { Layout.fillWidth: true }
                Button {
                    text: "确认删除"
                    highlighted: true
                    onClicked: {
                        var result = backendService.unregisterEdgeDevice(deleteConfirmDialog.targetDeviceId)
                        otaStatusText.text = result.message || (result.status === "success" ? "设备已删除" : "删除失败")
                        otaStatusText.color = result.status === "success" ? root.successColor : root.dangerColor
                        refreshDevices()
                        deleteConfirmDialog.close()
                        liveData.selectedDeviceId = ""
                    }
                }
            }
        }
    }
}
