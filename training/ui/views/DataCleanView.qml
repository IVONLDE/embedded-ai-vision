import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import QtMultimedia
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
    readonly property color dangerColor: Theme.danger
    readonly property color tableHoverBg: Theme.hover

    HelpIcon {
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.topMargin: -16
        anchors.rightMargin: -16
        title: "数据清洗帮助"
        body: "本页用于对数据集执行质量检测、清洗建议生成和清洗任务管理。\n\n1. 左侧历史区展示清洗任务记录，可查看任务状态、源数据集、使用算法、参数和建议数量。\n2. 点击“新建清洗任务”后，先选择源数据集。可通过数据阶段筛选只看原始、生成或清洗后的数据集。\n3. 系统会按数据模态加载清洗算法，例如图像清洗、文本清洗、音频清洗和表格清洗。可以同时勾选多个策略。\n4. 每个算法支持动态参数配置，例如阈值、处理强度、检测模式等。参数会随任务提交给后端。\n5. 启动任务后可查看进度和状态。若任务失败，错误弹窗会提示原因，通常需要检查源文件、参数范围或算法依赖。\n6. 任务完成后，详情区会展示清洗建议和样本明细。可预览样本内容，并根据建议类型判断是否需要删除、修复或保留。\n7. 支持保存清洗工程、重命名任务、删除历史记录和导出清洗结果。清洗后的数据可继续作为生成或评估的输入。"
    }

    property string viewMode: "history"
    property bool isCleaning: false
    property bool isCompleted: false
    property int currentCount: 0
    property int totalCount: 0
    property real progress: totalCount > 0 ? currentCount / totalCount : 0
    property double taskProgress: 0.0
    property string taskProgressMessage: ""
    property int currentTaskId: 0
    property int lastFailureTaskId: 0
    property string cleaningErrorMessage: ""

    property var selectedStrategies: []
    property var cleaningAlgorithms: []
    property var cleaningAlgorithmGroups: []

    property var sourceDatasets: []
    property var allSourceDatasets: []
    property string datasetTypeFilter: "raw"
    property var currentHistoryItem: null
    property string currentHistoryTitle: ""
    property int currentHistoryIndex: -1
    property var currentFileList: []
    property var detailAlgorithmIds: []
    property var detailAlgorithmItems: []
    property var detailParameters: ({})
    property bool hasDetailCustomParams: false

    property string previewKind: ""
    property string previewTitle: ""
    property string previewText: ""
    property string previewSource: ""
    property bool imageLoadError: false

    property int pendingPreviewId: -1
    property int pendingEditIndex: -1
    property int pendingDeleteIndex: -1
    property int selectedExportCount: 0

    function updateExportCount() {
        var count = 0
        for (var i = 0; i < cleaningHistoryModel.count; i++) {
            if (cleaningHistoryModel.get(i).isSelected) count++
        }
        root.selectedExportCount = count
    }

    function modalityFromLabel(label) {
        if (label === "图像") return "image"
        if (label === "文本") return "text"
        if (label === "音频") return "audio"
        if (label === "表格") return "tabular"
        if (label === "视频") return "video"
        if (label === "多模态") return "multimodal"
        return label || ""
    }

    function modalityTitle(modality) {
        if (modality === "image") return "图像清洗算法"
        if (modality === "text") return "文本清洗算法"
        if (modality === "audio") return "音频清洗算法"
        if (modality === "tabular") return "表格清洗算法"
        if (modality === "video") return "视频清洗算法"
        if (modality === "multimodal") return "通用清洗算法"
        return "其他清洗算法"
    }

    function stageLabel(stage) {
        if (stage === "raw") return "原始"
        if (stage === "cleaned") return "清洗"
        if (stage === "generated") return "生成"
        return stage || "原始"
    }

    function stageColor(stage) {
        if (stage === "raw") return "#4DD0E1"
        if (stage === "cleaned") return "#34D399"
        if (stage === "generated") return "#F59E0B"
        return root.textMuted
    }

    function applyDatasetFilter() {
        var filtered = []
        for (var i = 0; i < root.allSourceDatasets.length; i++) {
            var ds = root.allSourceDatasets[i]
            if (root.datasetTypeFilter === "all" || ds.stage === root.datasetTypeFilter) {
                filtered.push(ds)
            }
        }
        if (filtered.length === 0) filtered.push({ id: 0, name: "无可用数据集", modality: "", stage: root.datasetTypeFilter })
        root.sourceDatasets = filtered
    }

    function currentSourceDataset() {
        if (sourceDataCombo.currentIndex < 0 || sourceDataCombo.currentIndex >= root.sourceDatasets.length)
            return null
        return root.sourceDatasets[sourceDataCombo.currentIndex]
    }

    function loadCleaningAlgorithms() {
        var source = root.currentSourceDataset()
        var modality = source ? (source.modality || "") : ""
        var algorithms = backendService.getCleaningStrategies(modality) || []
        root.cleaningAlgorithms = algorithms
        root.paramsDataMap = root.buildParamsDataMap(algorithms)
        root.cleaningAlgorithmGroups = root.groupCleaningAlgorithms(algorithms)
        root.selectedStrategies = root.selectedStrategies.filter(function(id) {
            return root.algorithmById(id) !== null
        })
    }

    function buildParamsDataMap(algorithms) {
        var map = {}
        for (var i = 0; i < algorithms.length; i++) {
            var algorithm = algorithms[i]
            var params = []
            var rawParams = algorithm.parameters || []
            for (var p = 0; p < rawParams.length; p++) {
                var param = rawParams[p]
                params.push({
                    n: param.name || "",
                    label: param.label || param.name || "",
                    v: param.default_value !== undefined && param.default_value !== null ? String(param.default_value) : "",
                    type: param.type || "string"
                })
            }
            map[String(algorithm.id)] = params
        }
        return map
    }

    function groupCleaningAlgorithms(algorithms) {
        var order = ["multimodal", "image", "text", "audio", "tabular", "video", "other"]
        var grouped = {}
        for (var i = 0; i < algorithms.length; i++) {
            var algorithm = algorithms[i]
            var modality = algorithm.modality || "other"
            if (!grouped[modality]) grouped[modality] = []
            grouped[modality].push(algorithm)
        }
        var result = []
        for (var j = 0; j < order.length; j++) {
            var key = order[j]
            if (grouped[key] && grouped[key].length > 0)
                result.push({ t: root.modalityTitle(key), m: grouped[key] })
        }
        return result
    }

    function algorithmById(algorithmId) {
        var id = Number(algorithmId)
        for (var i = 0; i < root.cleaningAlgorithms.length; i++) {
            if (Number(root.cleaningAlgorithms[i].id) === id) return root.cleaningAlgorithms[i]
        }
        return null
    }

    function algorithmName(algorithmId) {
        var algorithm = root.algorithmById(algorithmId)
        return algorithm ? algorithm.name : "未知算法"
    }

    function algorithmIdByName(name) {
        for (var i = 0; i < root.cleaningAlgorithms.length; i++) {
            var algorithm = root.cleaningAlgorithms[i]
            if (algorithm.name === name || algorithm.key === name) return Number(algorithm.id)
        }
        return 0
    }

    function selectedCleaningParameters() {
        var result = { algorithm_ids: root.selectedStrategies.slice() }
        for (var i = 0; i < root.selectedStrategies.length; i++) {
            var id = String(root.selectedStrategies[i])
            var params = root.paramsDataMap[id] || []
            for (var p = 0; p < params.length; p++) {
                result[params[p].n] = params[p].v
            }
        }
        return result
    }

    property var paramsDataMap: ({})
    property var algorithmNameMap: ({})

    function algorithmNames(ids) {
        if (!ids || ids.length === 0) return ""
        var names = []
        for (var i = 0; i < ids.length; i++) {
            var name = root.algorithmNameMap[String(ids[i])] || ("算法#" + ids[i])
            names.push(name)
        }
        return names.join(", ")
    }

    function formatParameters(ids, paramsJson) {
        var parts = []
        parts.push("算法: " + root.algorithmNames(ids))
        if (paramsJson) {
            var keys = Object.keys(paramsJson)
            for (var i = 0; i < keys.length; i++) {
                var k = keys[i]
                if (k === "algorithm_ids") continue
                parts.push(k + "=" + paramsJson[k])
            }
        }
        return parts.join(" | ")
    }

    function cleaningTaskTitle(task, sourceName) {
        if (task && task.title && String(task.title).trim() !== "") return task.title
        var datasetName = sourceName || ("鏁版嵁闆?" + (task.source_dataset_id || ""))
        var taskId = task.id || task.taskId || ""
        return "娓呮礂浠诲姟_" + datasetName + "_#" + taskId
    }

    function showCleaningFailure(message) {
        root.isCleaning = false
        root.isCompleted = false
        root.taskProgressMessage = ""
        root.cleaningErrorMessage = message && message !== "" ? message : "清洗任务执行失败，请检查算法配置或源数据集。"
        cleaningFailurePopup.open()
    }

    function parseAlgorithmIds(value) {
        if (Array.isArray(value)) {
            return value.map(function(item) { return Number(item) }).filter(function(item) { return item > 0 })
        }
        return String(value || "").split(",").map(function(item) {
            return Number(String(item).trim())
        }).filter(function(item) {
            return item > 0
        })
    }

    function parseJsonObject(value) {
        if (!value) return {}
        if (typeof value === "object") return value
        try {
            return JSON.parse(String(value))
        } catch (e) {
            return {}
        }
    }

    function normalizeAlgorithmIds(task) {
        var parameters = task.parameters || task.parameters_json || {}
        var payload = task.payload || task.payload_json || {}
        var ids = parameters.algorithm_ids || payload.algorithm_ids || []
        if ((!ids || ids.length === 0) && task.algorithm_id) ids = [task.algorithm_id]
        return root.parseAlgorithmIds(ids)
    }

    function detailParameterItems(params) {
        var result = []
        if (!params) return result
        var keys = Object.keys(params)
        for (var i = 0; i < keys.length; i++) {
            var key = keys[i]
            if (key === "algorithm_ids") continue
            result.push({ k: key, v: params[key] })
        }
        return result
    }

    function localFileUrl(path) {
        var clean = String(path || "").replace(/\\/g, "/")
        if (clean.indexOf("file://") === 0) return clean
        return "file:///" + clean
    }

    function decisionKey(actionName) {
        var value = String(actionName || "").toLowerCase()
        if (value.indexOf("删除") !== -1 || value.indexOf("剔除") !== -1 || value.indexOf("delete") !== -1 || value.indexOf("drop") !== -1)
            return "delete"
        if (value.indexOf("修复") !== -1 || value.indexOf("校正") !== -1 || value.indexOf("repair") !== -1 || value.indexOf("fix") !== -1)
            return "repair"
        if (value.indexOf("保留") !== -1 || value.indexOf("keep") !== -1)
            return "keep"
        if (value.indexOf("复核") !== -1 || value.indexOf("审核") !== -1 || value.indexOf("review") !== -1)
            return "review"
        return "other"
    }

    function decisionAccentColor(actionName) {
        var key = root.decisionKey(actionName)
        if (key === "delete") return "#F87171"
        if (key === "repair") return "#F59E0B"
        if (key === "keep") return "#34D399"
        if (key === "review") return "#60A5FA"
        return root.primaryColor
    }

    function decisionBackgroundColor(actionName) {
        var key = root.decisionKey(actionName)
        if (key === "delete") return "#4C1D1D"
        if (key === "repair") return "#4A2E12"
        if (key === "keep") return "#123B2A"
        if (key === "review") return "#17365F"
        return root.tableHoverBg
    }

    function computeHasDetailParams(obj) {
        if (!obj) return false
        var keys = Object.keys(obj)
        for (var i = 0; i < keys.length; i++) {
            if (keys[i] !== "algorithm_ids") return true
        }
        return false
    }

    ListModel { id: cleaningHistoryModel }
    ListModel { id: previewModel }

    // ================= 后端信号处理 =================
    Connections {
        target: backendService

        function onDatasetsUpdated(data) {
            var rawList = []
            if (data && data.items) rawList = data.items
            else if (Array.isArray(data)) rawList = data

            var sources = []
            for (var i = 0; i < rawList.length; i++) {
                var item = rawList[i]
                var n = item.name || ""
                var idx = n.indexOf("|Status:")
                var s = idx !== -1 ? n.substring(idx + 8) : (item.status || "")
                if (s !== "清洗文件" && s !== "扩增文件" && s !== "扩展文件") {
                    sources.push({
                        id: item.id || 0,
                        name: (item.name || "未命名").split("|Status:")[0],
                        modality: item.modality || root.modalityFromLabel(item.type || ""),
                        stage: item.stage || "raw"
                    })
                }
            }
            if (sources.length === 0) sources.push({ id: 0, name: "无可用源数据集 (请先导入)", modality: "", stage: "raw" })
            root.allSourceDatasets = sources
            root.applyDatasetFilter()
            root.loadCleaningAlgorithms()
        }

        function onCleaningStatusUpdated(message, success) {
            root.showToast(success ? "✅ " + message : "⚠️ " + message)
            if (success) {
                root.isCleaning = false
                root.isCompleted = true
                if (root.currentTaskId > 0) {
                    backendService.getCleaningSuggestions(root.currentTaskId, "", 1, 200)
                }
            } else {
                root.showCleaningFailure(message)
            }
        }

        function onCleaningTasksUpdated(data) {
            var items = []
            if (data && data.items) items = data.items
            cleaningHistoryModel.clear()
            for (var i = 0; i < items.length; i++) {
                var task = items[i]
                var sourceName = task.source_dataset_name || ("数据集#" + (task.source_dataset_id || ""))
                var targetName = task.target_dataset_name || ""
                var paramsObj = task.parameters || task.parameters_json || {}
                var payloadObj = task.payload || task.payload_json || {}
                var algorithmIds = root.normalizeAlgorithmIds(task)
                var algoDesc = root.formatParameters(algorithmIds, paramsObj)
                cleaningHistoryModel.append({
                    isSelected: false,
                    taskId: task.id || 0,
                    projectName: root.cleaningTaskTitle(task, sourceName),
                    sourceDataset: sourceName,
                    cleanedDataset: targetName,
                    algos: algoDesc,
                    algorithmIds: algorithmIds,
                    algorithmIdsText: algorithmIds.join(","),
                    parameters: paramsObj,
                    parametersJsonText: JSON.stringify(paramsObj),
                    payload: payloadObj,
                    path: task.output_dir || "",
                    time: task.created_at || "",
                    status: task.status || "",
                    progress: task.progress || 0,
                    progressMessage: task.progress_message || "",
                    errorMessage: task.error_message || ""
                })
                if (root.isCleaning && root.currentTaskId > 0 && task.id === root.currentTaskId) {
                    root.taskProgress = (task.progress || 0) / 100.0
                    root.taskProgressMessage = task.progress_message || ""
                    if (task.status === "failed" && root.lastFailureTaskId !== task.id) {
                        root.lastFailureTaskId = task.id
                        root.showCleaningFailure(task.error_message || task.progress_message || "清洗任务执行失败")
                    }
                }
            }
        }

        function onAlgorithmsUpdated(algorithms) {
            if (!algorithms || !algorithms.length) return
            var map = {}
            var old = root.algorithmNameMap
            if (old) {
                var oldKeys = Object.keys(old)
                for (var j = 0; j < oldKeys.length; j++) {
                    map[oldKeys[j]] = old[oldKeys[j]]
                }
            }
            for (var i = 0; i < algorithms.length; i++) {
                var algo = algorithms[i]
                map[String(algo.id)] = algo.name || algo.key || ""
            }
            root.algorithmNameMap = map
        }

        function onCleaningSuggestionsUpdated(data) {
            previewModel.clear()
            var monitorItems = data.monitor_items || []
            for (var i = 0; i < monitorItems.length; i++) {
                var item = monitorItems[i]
                previewModel.append({
                    sampleId: item.sample_id || 0,
                    sourceName: item.sample_name || "",
                    actionName: item.operation_label || item.suggested_action || "",
                    samplePath: item.sample_path || "",
                    issueType: item.issue_type || "",
                    confidence: item.confidence || 0,
                    status: item.status || ""
                })
            }
            if (monitorItems.length === 0) {
                previewModel.append({
                    sampleId: 0,
                    sourceName: "清洗任务已完成",
                    actionName: "未发现需处理的清洗建议",
                    samplePath: "",
                    issueType: "",
                    confidence: 0,
                    status: ""
                })
            }
        }

        function onSamplePreviewUpdated(data) {
            var payload = data && data.data ? data.data : data
            if (!payload || !payload.sample_id) return
            if (root.pendingPreviewId !== payload.sample_id) return
            root.pendingPreviewId = -1
            root.previewKind = payload.preview_kind || "file"
            root.previewText = payload.text_content || payload.error || ""
            root.previewTitle = payload.name || payload.relative_path || "样本预览"
            root.previewSource = payload.file_path ? root.localFileUrl(payload.file_path) : ""
            root.imageLoadError = false
            if (root.previewKind === "audio" && root.previewSource !== "") {
                previewPlayer.source = root.previewSource
            }
            samplePreviewPopup.open()
        }
    }

    // ================= 样本预览弹窗 =================
    Popup {
        id: samplePreviewPopup
        width: Math.max(400, Math.min(root.width * 0.9, 760))
        height: Math.max(300, Math.min(root.height * 0.9, 560))
        x: Math.round((root.width - width) / 2)
        y: Math.round((root.height - height) / 2)
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onClosed: previewPlayer.stop()

        background: Rectangle {
            color: root.panelBg
            border.color: root.borderColor
            border.width: 1
            radius: 8
            clip: true
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 18
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                Text {
                    text: root.previewTitle
                    color: root.textColor
                    font.pixelSize: 16
                    font.bold: true
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }

                Button {
                    text: "关闭"
                    Layout.preferredWidth: 72
                    Layout.preferredHeight: 30
                    background: Rectangle { color: parent.hovered ? root.tableHoverBg : "transparent"; radius: 4; border.color: root.borderColor }
                    contentItem: Text { text: parent.text; color: root.textColor; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: samplePreviewPopup.close()
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: root.bgDark
                border.color: root.borderColor
                radius: 6
                clip: true

                Image {
                    id: previewImage
                    anchors.fill: parent
                    anchors.margins: 12
                    visible: root.previewKind === "image" && root.previewSource !== "" && previewImage.status !== Image.Error
                    source: root.previewKind === "image" ? root.previewSource : ""
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                    onStatusChanged: {
                        if (previewImage.status === Image.Error) {
                            root.imageLoadError = true
                        }
                    }
                }

                ScrollView {
                    anchors.fill: parent
                    anchors.margins: 12
                    visible: root.previewKind === "text"

                    TextArea {
                        text: root.previewText
                        readOnly: true
                        wrapMode: TextEdit.Wrap
                        color: root.textColor
                        selectByMouse: true
                        background: Rectangle { color: "transparent" }
                    }
                }

                ColumnLayout {
                    anchors.centerIn: parent
                    width: Math.min(parent.width - 60, 520)
                    spacing: 14
                    visible: root.previewKind === "audio"

                    Text {
                        text: root.previewTitle
                        color: root.textColor
                        font.pixelSize: 15
                        font.bold: true
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignHCenter
                        elide: Text.ElideRight
                    }

                    Text {
                        text: root.previewSource !== "" ? root.previewSource : "无音频路径"
                        color: root.textMuted
                        font.pixelSize: 12
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignHCenter
                        elide: Text.ElideMiddle
                    }

                    RowLayout {
                        Layout.alignment: Qt.AlignHCenter
                        spacing: 10

                        Button {
                            text: previewPlayer.playbackState === MediaPlayer.PlayingState ? "暂停" : "播放"
                            Layout.preferredWidth: 90
                            Layout.preferredHeight: 34
                            background: Rectangle { color: parent.hovered ? "#0288D1" : "#039BE5"; radius: 4 }
                            contentItem: Text { text: parent.text; color: "black"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                            onClicked: {
                                if (previewPlayer.playbackState === MediaPlayer.PlayingState) previewPlayer.pause()
                                else previewPlayer.play()
                            }
                        }

                        Button {
                            text: "停止"
                            Layout.preferredWidth: 70
                            Layout.preferredHeight: 34
                            background: Rectangle { color: parent.hovered ? root.tableHoverBg : "transparent"; border.color: root.borderColor; border.width: 1; radius: 4 }
                            contentItem: Text { text: parent.text; color: root.textColor; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                            onClicked: previewPlayer.stop()
                        }
                    }
                }

                ColumnLayout {
                    anchors.centerIn: parent
                    width: Math.min(parent.width - 60, 520)
                    spacing: 14
                    visible: (root.previewKind !== "image" && root.previewKind !== "text" && root.previewKind !== "audio") || (root.previewKind === "image" && root.imageLoadError)

                    Rectangle {
                        width: 72; height: 72; radius: 12
                        color: root.tableHoverBg
                        Layout.alignment: Qt.AlignHCenter
                        Text {
                            text: root.previewKind === "image" && root.imageLoadError ? "🖼" : (root.previewKind === "file" ? "📄" : "📎")
                            font.pixelSize: 32
                            anchors.centerIn: parent
                        }
                    }

                    Text {
                        text: root.previewTitle
                        color: root.textColor
                        font.pixelSize: 15
                        font.bold: true
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignHCenter
                        elide: Text.ElideRight
                    }

                    Text {
                        text: root.previewSource !== "" ? root.previewSource : "文件路径不可用"
                        color: root.textMuted
                        font.pixelSize: 12
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignHCenter
                        elide: Text.ElideMiddle
                    }

                    Text {
                        visible: root.previewKind === "image" && root.imageLoadError
                        text: "图片文件加载失败，文件可能不存在或格式不受支持"
                        color: root.dangerColor
                        font.pixelSize: 12
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                    }

                    Text {
                        visible: root.previewText !== "" && !(root.previewKind === "image" && root.imageLoadError)
                        text: root.previewText
                        color: root.textMuted
                        font.pixelSize: 12
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }
    }

    MediaPlayer {
        id: previewPlayer
        autoPlay: false
        audioOutput: previewAudio
    }

    AudioOutput {
        id: previewAudio
    }

    // ================= 任务进度轮询 =================
    Timer {
        id: progressPollTimer
        interval: 1000
        repeat: true
        running: root.isCleaning && root.currentTaskId > 0
        onTriggered: {
            backendService.getCleaningTasks(0, "")
        }
    }

    Component.onCompleted: {
        backendService.getDatasets(1, 100, "")
        backendService.getAlgorithms("cleaning", "")
        backendService.getCleaningTasks(0, "")
    }

    function getCurrentTime() {
        var date = new Date()
        var y = date.getFullYear()
        var m = (date.getMonth() + 1).toString().padStart(2, '0')
        var d = date.getDate().toString().padStart(2, '0')
        var h = date.getHours().toString().padStart(2, '0')
        var min = date.getMinutes().toString().padStart(2, '0')
        return y + "-" + m + "-" + d + " " + h + ":" + min
    }

    // ================= Toast =================
    property string toastMessage: "✅ 任务执行成功"
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
        progressPollTimer.stop()
        previewPlayer.stop()
    }

    function showToast(msg) {
        root.toastMessage = msg
        toastMsg.open()
        toastAnim.restart()
        toastCloseTimer.restart()
    }

    // ================= 清洗失败弹窗 =================
    Popup {
        id: cleaningFailurePopup
        width: 460
        height: 240
        modal: true
        focus: true
        x: Math.round((root.width - width) / 2)
        y: Math.round((root.height - height) / 2)
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { color: root.panelBg; radius: 8; border.color: root.dangerColor; border.width: 1 }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 20
            spacing: 14

            Text { text: "清洗任务失败"; color: root.dangerColor; font.pixelSize: 18; font.bold: true }
            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: root.borderColor }
            Text {
                text: root.cleaningErrorMessage
                color: root.textColor
                font.pixelSize: 13
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
                Layout.fillHeight: true
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                Button {
                    id: cleaningFailureOkButton
                    text: "知道了"
                    Layout.preferredWidth: 96
                    Layout.preferredHeight: 34
                    background: Rectangle { color: cleaningFailureOkButton.hovered ? "#BE123C" : root.dangerColor; radius: 4 }
                    contentItem: Text { text: cleaningFailureOkButton.text; color: "black"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; font.bold: true }
                    onClicked: cleaningFailurePopup.close()
                }
            }
        }
    }

    // ================= 保存清洗结果弹窗 =================
    Popup {
        id: savePopup
        width: 460
        height: 300
        modal: true
        focus: true
        x: Math.round((root.width - width) / 2)
        y: Math.round((root.height - height) / 2)
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { color: root.panelBg; radius: 8; border.color: root.borderColor; border.width: 1 }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 20
            spacing: 15
            Text { text: "💾 确认保存清洗结果"; color: root.textColor; font.pixelSize: 16; font.bold: true }
            Rectangle { Layout.fillWidth: true; height: 1; color: root.borderColor }

            ColumnLayout {
                spacing: 5
                Layout.fillWidth: true
                Text { text: "清洗数据集名称:"; color: root.textMuted; font.pixelSize: 12 }
                Rectangle {
                    Layout.fillWidth: true; height: 36; color: root.bgDark; radius: 4; border.color: root.borderColor; border.width: 1
                    TextInput {
                        id: saveDatasetNameInput
                        color: root.textColor; font.pixelSize: 13
                        anchors.fill: parent; leftPadding: 10; verticalAlignment: TextInput.AlignVCenter; selectByMouse: true
                    }
                }
            }

            Text {
                text: "保存路径由系统自动管理 (data/datasets/...)"
                color: root.textMuted; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.WordWrap
            }

            Item { Layout.fillHeight: true }

            RowLayout {
                Layout.fillWidth: true
                spacing: 15
                Item { Layout.fillWidth: true }
                Button {
                    text: "取消"
                    Layout.preferredWidth: 80; Layout.preferredHeight: 34
                    background: Rectangle { color: "transparent"; border.color: root.borderColor; border.width: 1; radius: 4 }
                    contentItem: Text { text: parent.text; color: root.textMuted; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: savePopup.close()
                }
                Button {
                    text: "确认保存"
                    Layout.preferredWidth: 100; Layout.preferredHeight: 34
                    background: Rectangle { color: root.primaryColor; radius: 4 }
                    contentItem: Text { text: parent.text; color: "black"; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: {
                        if (root.currentTaskId > 0) {
                            var result = backendService.storeCleaningTaskResult(root.currentTaskId, saveDatasetNameInput.text)
                            if (result && result.status === "success") {
                                root.showToast("✅ 清洗结果已保存: " + saveDatasetNameInput.text)
                                backendService.getCleaningTasks(0, "")
                                backendService.getDatasets(1, 100, "")
                            } else {
                                root.showToast("⚠️ " + ((result && result.message) ? result.message : "保存失败"))
                            }
                        } else {
                            root.showToast("⚠️ 没有可保存的清洗任务")
                        }
                        savePopup.close()
                        newCleaningTaskPopup.close()
                        previewModel.clear()
                        root.currentCount = 0
                        root.isCompleted = false
                        root.currentTaskId = 0
                    }
                }
            }
        }
    }

    // ================= 修改工程名弹窗 =================
    Popup {
        id: editProjectPopup
        width: 360
        height: 180
        modal: true
        focus: true
        x: Math.round((root.width - width) / 2)
        y: Math.round((root.height - height) / 2)
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { color: root.panelBg; radius: 8; border.color: root.borderColor; border.width: 1 }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 20
            spacing: 15
            Text { text: "✏️ 修改工程名称"; color: root.textColor; font.pixelSize: 16; font.bold: true }
            Rectangle {
                Layout.fillWidth: true; height: 36; color: root.bgDark; radius: 4; border.color: root.borderColor; border.width: 1
                TextInput {
                    id: editProjectNameInput
                    color: root.primaryColor; font.pixelSize: 13; font.bold: true
                    anchors.fill: parent; leftPadding: 10; verticalAlignment: TextInput.AlignVCenter; selectByMouse: true
                }
            }
            Item { Layout.fillHeight: true }
            RowLayout {
                Layout.fillWidth: true
                spacing: 15
                Item { Layout.fillWidth: true }
                Button {
                    text: "取消"
                    Layout.preferredWidth: 80; Layout.preferredHeight: 32
                    background: Rectangle { color: "transparent"; border.color: root.borderColor; border.width: 1; radius: 4 }
                    contentItem: Text { text: parent.text; color: root.textMuted; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: editProjectPopup.close()
                }
                Button {
                    text: "保存"
                    Layout.preferredWidth: 80; Layout.preferredHeight: 32
                    background: Rectangle { color: root.primaryColor; radius: 4 }
                    contentItem: Text { text: parent.text; color: "black"; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: {
                        if (root.pendingEditIndex !== -1 && editProjectNameInput.text.trim() !== "") {
                            cleaningHistoryModel.setProperty(root.pendingEditIndex, "projectName", editProjectNameInput.text)
                            root.showToast("✅ 工程名称已更新")
                        }
                        editProjectPopup.close()
                    }
                }
            }
        }
    }

    // ================= 删除确认弹窗 =================
    Popup {
        id: deleteConfirmPopup
        width: 320
        height: 190
        modal: true
        focus: true
        x: Math.round((root.width - width) / 2)
        y: Math.round((root.height - height) / 2)
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { color: root.panelBg; radius: 8; border.color: root.dangerColor; border.width: 1 }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 20
            spacing: 15
            RowLayout {
                spacing: 10
                Text { text: "⚠️"; font.pixelSize: 20 }
                Text { text: "确认删除此清洗记录吗？"; color: root.textColor; font.pixelSize: 15; font.bold: true }
            }
            Text { text: "删除后将无法恢复，相关文件依然保留在磁盘中。"; color: root.textMuted; font.pixelSize: 12; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            Item { Layout.fillHeight: true }
            RowLayout {
                Layout.fillWidth: true
                spacing: 15
                Item { Layout.fillWidth: true }
                Button {
                    text: "取消"
                    Layout.preferredWidth: 80; Layout.preferredHeight: 30
                    background: Rectangle { color: "transparent"; border.color: root.borderColor; border.width: 1; radius: 4 }
                    contentItem: Text { text: parent.text; color: root.textMuted; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: deleteConfirmPopup.close()
                }
                Button {
                    text: "确认删除"
                    Layout.preferredWidth: 80; Layout.preferredHeight: 30
                    background: Rectangle { color: root.dangerColor; radius: 4 }
                    contentItem: Text { text: parent.text; color: "black"; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: {
                        if (root.pendingDeleteIndex !== -1) {
                            var item = cleaningHistoryModel.get(root.pendingDeleteIndex)
                            if (item && item.taskId > 0) {
                                var result = backendService.deleteTask(item.taskId)
                                if (result && result.status === "success") {
                                    cleaningHistoryModel.remove(root.pendingDeleteIndex)
                                    root.updateExportCount()
                                    root.showToast("记录已删除")
                                } else {
                                    root.showToast("删除失败: " + ((result && result.message) ? result.message : "未知错误"))
                                }
                            } else {
                                cleaningHistoryModel.remove(root.pendingDeleteIndex)
                                root.updateExportCount()
                                root.showToast("记录已删除")
                            }
                        }
                        deleteConfirmPopup.close()
                    }
                }
            }
        }
    }

    // ================= 导出弹窗 =================
    FolderDialog {
        id: exportFolderDialog
        title: "选择导出合并的目标文件夹"
        onAccepted: {
            var path = selectedFolder.toString()
            exportPathInput.text = decodeURIComponent(path.replace(/^(file:\/{2,3})/, ""))
        }
    }

    Popup {
        id: exportPopup
        width: 450
        height: 250
        modal: true
        focus: true
        x: Math.round((root.width - width) / 2)
        y: Math.round((root.height - height) / 2)
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { color: root.panelBg; radius: 8; border.color: root.borderColor; border.width: 1 }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 20
            spacing: 15
            Text { text: "📥 导出合并选中的数据集"; color: root.textColor; font.pixelSize: 16; font.bold: true }
            Rectangle { Layout.fillWidth: true; height: 1; color: root.borderColor }
            Text {
                text: "已选中 " + root.selectedExportCount + " 个清洗数据集。"
                color: root.textMuted; font.pixelSize: 13; wrapMode: Text.WordWrap; Layout.fillWidth: true
            }
            ColumnLayout {
                spacing: 5
                Layout.fillWidth: true
                Text { text: "目标导出路径:"; color: root.textMuted; font.pixelSize: 12 }
                RowLayout {
                    Layout.fillWidth: true; spacing: 10
                    Rectangle {
                        Layout.fillWidth: true; height: 36; color: root.bgDark; radius: 4; border.color: root.borderColor; border.width: 1
                        TextInput {
                            id: exportPathInput
                            text: "/data/export/merged_clean_data/"
                            color: root.textColor; font.pixelSize: 13; anchors.fill: parent; leftPadding: 10; verticalAlignment: TextInput.AlignVCenter
                        }
                    }
                    Button {
                        text: "浏览"; Layout.preferredHeight: 36
                        background: Rectangle { color: root.tableHoverBg; radius: 4; border.color: root.borderColor; border.width: 1 }
                        contentItem: Text { text: parent.text; color: root.textColor; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                        onClicked: exportFolderDialog.open()
                    }
                }
            }
            Item { Layout.fillHeight: true }
            RowLayout {
                Layout.fillWidth: true; spacing: 15
                Item { Layout.fillWidth: true }
                Button {
                    text: "取消"; Layout.preferredWidth: 80; Layout.preferredHeight: 34
                    background: Rectangle { color: "transparent"; border.color: root.borderColor; border.width: 1; radius: 4 }
                    contentItem: Text { text: parent.text; color: root.textMuted; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: exportPopup.close()
                }
                Button {
                    text: "开始打包导出"; Layout.preferredWidth: 120; Layout.preferredHeight: 34
                    background: Rectangle { color: root.primaryColor; radius: 4 }
                    contentItem: Text { text: parent.text; color: "black"; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: {
                        exportPopup.close()
                        for (var i = 0; i < cleaningHistoryModel.count; i++) {
                            cleaningHistoryModel.setProperty(i, "isSelected", false)
                        }
                        root.updateExportCount()
                        root.showToast("🚀 选中的数据集已开始合并打包导出")
                    }
                }
            }
        }
    }

    // ================= 新建清洗任务弹窗 =================
    Popup {
        id: newCleaningTaskPopup
        width: Math.max(600, Math.min(1250, root.width * 0.95))
        height: Math.max(500, Math.min(850, root.height * 0.95))
        modal: true
        focus: true
        x: Math.round((root.width - width) / 2)
        y: Math.round((root.height - height) / 2)
        closePolicy: root.isCleaning ? Popup.NoAutoClose : (Popup.CloseOnEscape | Popup.CloseOnPressOutside)
        background: Rectangle { color: root.bgDark; radius: 8; border.color: root.borderColor; border.width: 1 }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 20
            spacing: 15

            RowLayout {
                Layout.fillWidth: true
                Text { text: "⚙️ 新建多策略数据清洗任务"; color: root.textColor; font.pixelSize: 18; font.bold: true }
                Item { Layout.fillWidth: true }
                Rectangle {
                    width: 30; height: 30; color: "transparent"; radius: 4
                    Text { text: "✕"; color: root.textMuted; font.pixelSize: 18; anchors.centerIn: parent }
                    MouseArea {
                        anchors.fill: parent; cursorShape: Qt.PointingHandCursor; hoverEnabled: true
                        onEntered: parent.color = root.dangerColor
                        onExited: parent.color = "transparent"
                        onClicked: {
                            if (root.isCleaning) {
                                root.showToast("⚠️ 请先停止正在进行的清洗任务")
                            } else {
                                newCleaningTaskPopup.close()
                            }
                        }
                    }
                }
            }

            Rectangle { Layout.fillWidth: true; height: 1; color: root.borderColor }

            // 顶部控制面板
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 90
                color: root.panelBg
                radius: 8
                border.color: root.borderColor
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 15
                    spacing: 12
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 20
                        RowLayout {
                            spacing: 8
                            Text { text: "📁 目标源数据:"; color: root.textMuted; font.pixelSize: 13 }
                            RowLayout {
                                spacing: 4
                                Repeater {
                                    model: [
                                        { stage: "raw", label: "原始" },
                                        { stage: "cleaned", label: "清洗" },
                                        { stage: "generated", label: "生成" },
                                        { stage: "all", label: "全部" }
                                    ]
                                    delegate: Rectangle {
                                        height: 26; width: labelText.contentWidth + 16; radius: 13
                                        color: root.datasetTypeFilter === modelData.stage ? root.stageColor(modelData.stage) : root.bgDark
                                        border.color: root.datasetTypeFilter === modelData.stage ? root.stageColor(modelData.stage) : root.borderColor
                                        border.width: 1
                                        Text {
                                            id: labelText
                                            text: modelData.label; color: root.datasetTypeFilter === modelData.stage ? "#0D1117" : root.stageColor(modelData.stage)
                                            font.pixelSize: 11; font.bold: root.datasetTypeFilter === modelData.stage
                                            anchors.centerIn: parent
                                        }
                                        MouseArea {
                                            anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                            onClicked: {
                                                root.datasetTypeFilter = modelData.stage
                                                root.applyDatasetFilter()
                                                sourceDataCombo.currentIndex = 0
                                                root.selectedStrategies = []
                                                root.loadCleaningAlgorithms()
                                            }
                                        }
                                    }
                                }
                            }
                            StableComboBox {
                                id: sourceDataCombo
                                model: root.sourceDatasets
                                textRole: "name"
                                Layout.preferredWidth: 200
                                Layout.preferredHeight: 32
                                background: Rectangle { color: root.bgDark; border.color: root.borderColor; radius: 4 }
                                contentItem: RowLayout {
                                    spacing: 6
                                    Rectangle {
                                        width: 8; height: 8; radius: 4
                                        color: {
                                            var ds = root.sourceDatasets[sourceDataCombo.currentIndex]
                                            return ds ? root.stageColor(ds.stage || "raw") : root.textMuted
                                        }
                                    }
                                    Text {
                                        text: sourceDataCombo.currentText
                                        color: root.textColor
                                        verticalAlignment: Text.AlignVCenter
                                        elide: Text.ElideRight
                                        Layout.fillWidth: true
                                    }
                                }
                                onCurrentIndexChanged: {
                                    root.selectedStrategies = []
                                    root.loadCleaningAlgorithms()
                                }
                            }
                        }

                        Item { Layout.fillWidth: true }

                        Rectangle {
                            width: 150; height: 36; radius: 4
                            color: root.selectedStrategies.length === 0 ? Theme.border : (root.isCleaning ? Theme.muted : root.primaryColor)
                            opacity: root.selectedStrategies.length === 0 ? 0.5 : 1.0
                            Text { text: root.isCleaning ? "⏹ 停止清洗" : "▶ 开始清洗任务"; color: "#FFFFFF"; font.bold: true; font.pixelSize: 13; anchors.centerIn: parent }
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: root.selectedStrategies.length === 0 ? Qt.ArrowCursor : Qt.PointingHandCursor
                                onClicked: {
                                    if (root.selectedStrategies.length === 0) return
                                    if (!root.isCleaning) {
                                        var source = root.currentSourceDataset()
                                        if (!source || !source.id) {
                                            root.showToast("⚠️ 请先选择可用源数据集")
                                            return
                                        }
                                        var taskResult = backendService.createCleaningTask(source.id, root.selectedStrategies.slice(), root.selectedCleaningParameters())
                                        if (!taskResult || taskResult.status !== "success") {
                                            root.showToast("⚠️ " + (taskResult && taskResult.message ? taskResult.message : "清洗任务创建失败"))
                                            return
                                        }
                                        root.currentTaskId = taskResult.id || 0
                                        root.lastFailureTaskId = 0
                                        root.currentCount = 0
                                        root.taskProgress = 0.0
                                        root.taskProgressMessage = ""
                                        root.isCompleted = false
                                        previewModel.clear()
                                        root.showToast("✅ 清洗任务已启动 (" + root.currentTaskId + ")")
                                    } else {
                                        backendService.stopEnhancementTask(root.currentTaskId)
                                        root.showToast("⏹ 已请求停止任务")
                                    }
                                    root.isCleaning = !root.isCleaning
                                }
                            }
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        RowLayout {
                            Layout.fillWidth: true
                            Text {
                                text: root.isCleaning ? "清洗引擎运行中" : (root.isCompleted ? "✅ 数据清洗已完成" : "请在下方勾选所需清洗策略并启动")
                                color: root.isCompleted ? root.successColor : root.primaryColor
                                font.pixelSize: 12; font.bold: true
                            }
                            Item { Layout.fillWidth: true }
                            Text {
                                text: root.isCleaning ? Math.floor(root.taskProgress * 100) + "%" : (root.currentCount + " / " + root.totalCount + " (" + Math.floor(root.progress * 100) + "%)")
                                color: root.textMuted; font.pixelSize: 12; font.bold: true
                            }
                        }
                        Rectangle {
                            Layout.fillWidth: true; height: 4; color: root.bgDark; radius: 2
                            Rectangle {
                                width: parent.width * (root.isCleaning ? root.taskProgress : root.progress); height: parent.height
                                color: root.isCompleted ? root.successColor : root.primaryColor
                                radius: 2
                                Behavior on width { NumberAnimation { duration: 100 } }
                            }
                        }
                        Text {
                            visible: root.isCleaning && root.taskProgressMessage !== ""
                            text: root.taskProgressMessage
                            color: root.textMuted; font.pixelSize: 11
                            Layout.fillWidth: true; elide: Text.ElideRight
                        }
                    }
                }
            }

            // 三栏布局
            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 15

                // 左栏：算法选择
                Rectangle {
                    Layout.preferredWidth: 260
                    Layout.fillHeight: true
                    color: root.panelBg
                    radius: 8
                    border.color: root.borderColor
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 15
                        spacing: 15
                        Text { text: "📂 清洗算法选择 (可多选)"; color: root.textColor; font.bold: true; font.pixelSize: 15 }
                        ScrollView {
                            Layout.fillWidth: true; Layout.fillHeight: true; clip: true; contentWidth: availableWidth
                            Column {
                                width: parent.width; spacing: 5
                                Repeater {
                                    model: root.cleaningAlgorithmGroups
                                    delegate: Column {
                                        width: parent.width; spacing: 2
                                        property bool isExpanded: true
                                        Rectangle {
                                            width: parent.width; height: 38; radius: 4; color: isExpanded ? Theme.hover : "transparent"
                                            Text { text: (isExpanded ? "▼ " : "▶ ") + modelData.t; color: root.textColor; font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter; anchors.left: parent.left; anchors.leftMargin: 12 }
                                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: isExpanded = !isExpanded }
                                        }
                                        Column {
                                            visible: isExpanded; width: parent.width; spacing: 2
                                            Repeater {
                                                model: modelData.m
                                                delegate: Rectangle {
                                                    property int algorithmId: Number(modelData.id)
                                                    width: parent.width; height: 34; radius: 4
                                                    color: root.selectedStrategies.indexOf(algorithmId) !== -1 ? root.tableHoverBg : "transparent"
                                                    RowLayout {
                                                        anchors.fill: parent; anchors.leftMargin: 25; spacing: 10
                                                        Rectangle {
                                                            width: 14; height: 14; radius: 2
                                                            border.color: root.selectedStrategies.indexOf(algorithmId) !== -1 ? root.primaryColor : root.textMuted
                                                            color: root.selectedStrategies.indexOf(algorithmId) !== -1 ? root.primaryColor : "transparent"
                                                            Text { text: "✓"; font.pixelSize: 10; color: "white"; anchors.centerIn: parent; visible: root.selectedStrategies.indexOf(algorithmId) !== -1 }
                                                        }
                                                        Text { text: modelData.name || modelData.key || "未命名算法"; color: root.selectedStrategies.indexOf(algorithmId) !== -1 ? root.textColor : root.textMuted; font.pixelSize: 12; Layout.fillWidth: true; elide: Text.ElideRight }
                                                    }
                                                    MouseArea {
                                                        anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                                        onClicked: {
                                                            var arr = root.selectedStrategies.slice()
                                                            var idx = arr.indexOf(algorithmId)
                                                            if (idx !== -1) arr.splice(idx, 1)
                                                            else arr.push(algorithmId)
                                                            root.selectedStrategies = arr
                                                            root.isCompleted = false
                                                            previewModel.clear()
                                                            root.currentCount = 0
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                                Text {
                                    visible: root.cleaningAlgorithmGroups.length === 0
                                    text: "当前源数据集没有可用清洗算法\n请先在算法与参数配置中启用或注册清洗算法"
                                    color: root.textMuted; font.pixelSize: 12; wrapMode: Text.WordWrap
                                    width: parent.width; horizontalAlignment: Text.AlignHCenter
                                }
                            }
                        }
                    }
                }

                // 中栏：参数配置
                Rectangle {
                    Layout.preferredWidth: 260
                    Layout.fillHeight: true
                    color: root.panelBg
                    radius: 8
                    border.color: root.borderColor
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 15
                        spacing: 15
                        Text { text: "⚙️ 综合参数配置"; color: root.textColor; font.bold: true; font.pixelSize: 14; Layout.fillWidth: true }
                        Text { visible: root.selectedStrategies.length === 0; text: "👈 请在左侧勾选清洗算法\n可以同时选择多个"; color: root.textMuted; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; Layout.alignment: Qt.AlignCenter; Layout.fillHeight: true }
                        ScrollView {
                            Layout.fillWidth: true; Layout.fillHeight: true; clip: true; contentWidth: availableWidth; visible: root.selectedStrategies.length > 0
                            Column {
                                width: parent.width; spacing: 20
                                Repeater {
                                    model: root.selectedStrategies
                                    delegate: Column {
                                        id: selectedAlgorithmDelegate
                                        property int selectedAlgorithmId: Number(modelData)
                                        width: parent.width; spacing: 10
                                        Text { text: "🔹 " + root.algorithmName(selectedAlgorithmId); color: root.primaryColor; font.bold: true; font.pixelSize: 13 }
                                        Column {
                                            width: parent.width; spacing: 10
                                            Repeater {
                                                model: root.paramsDataMap[String(selectedAlgorithmId)] || []
                                                delegate: Column {
                                                    width: parent.width; spacing: 6
                                                    Text { text: modelData.label || modelData.n; color: root.textMuted; font.pixelSize: 12 }
                                                    Rectangle {
                                                        width: parent.width; height: 36; color: root.bgDark; radius: 4; border.color: root.borderColor; border.width: 1
                                                        TextInput {
                                                            text: modelData.v
                                                            color: root.textColor; font.pixelSize: 13; anchors.fill: parent; leftPadding: 10; verticalAlignment: TextInput.AlignVCenter
                                                            onTextChanged: {
                                                                var paramList = root.paramsDataMap[String(selectedAlgorithmDelegate.selectedAlgorithmId)]
                                                                for (var i = 0; i < paramList.length; i++) {
                                                                    if (paramList[i].n === modelData.n) {
                                                                        paramList[i].v = text
                                                                        break
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                        Rectangle { width: parent.width; height: 1; color: root.borderColor; visible: index !== root.selectedStrategies.length - 1 }
                                    }
                                }
                            }
                        }
                    }
                }

                // 右栏：实时监控流
                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    color: root.panelBg
                    radius: 8
                    border.color: root.borderColor
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 20; spacing: 15
                        Text { text: "👁 清洗实时监控流"; color: root.textColor; font.bold: true; font.pixelSize: 16 }
                        Rectangle {
                            Layout.fillWidth: true; Layout.fillHeight: true; color: root.bgDark; radius: 6; border.color: root.borderColor; border.width: 1; clip: true
                            ColumnLayout {
                                anchors.centerIn: parent; spacing: 10; visible: previewModel.count === 0 && !root.isCleaning
                                Text { text: root.isCompleted ? "LOADING_RESULTS" : "AWAITING_TASK"; color: root.textMuted; font.pixelSize: 14; font.family: "Courier"; font.bold: true; Layout.alignment: Qt.AlignHCenter }
                            }
                            ListView {
                                id: taskMonitorList
                                anchors.fill: parent; anchors.margins: 10; spacing: 8; model: previewModel; clip: true
                                delegate: Rectangle {
                                    width: taskMonitorList.width; height: 50; radius: 4
                                    color: monitorMa.containsMouse ? root.tableHoverBg : "transparent"
                                    border.color: monitorMa.containsMouse ? root.primaryColor : "transparent"
                                    border.width: 1
                                    MouseArea {
                                        id: monitorMa
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            if (sampleId > 0) {
                                                root.pendingPreviewId = sampleId
                                                backendService.getSamplePreview(sampleId)
                                            }
                                        }
                                    }
                                    RowLayout {
                                        anchors.fill: parent; anchors.margins: 10; spacing: 15
                                        RowLayout {
                                            Layout.fillWidth: true; spacing: 8
                                            Text { text: "📄"; font.pixelSize: 16 }
                                            ColumnLayout {
                                                spacing: 2
                                                Text { text: "样本"; color: root.textMuted; font.pixelSize: 10 }
                                                Text { text: sourceName; color: root.textColor; font.pixelSize: 12; font.family: "Courier"; elide: Text.ElideRight }
                                            }
                                        }
                                        Text { text: "➡"; color: root.primaryColor; font.pixelSize: 16 }
                                        RowLayout {
                                            Layout.fillWidth: true; spacing: 8
                                            Text { text: "🛠"; font.pixelSize: 16 }
                                            ColumnLayout {
                                                spacing: 2
                                                Text { text: "清洗决策"; color: root.primaryColor; font.pixelSize: 10; font.bold: true }
                                                Text { text: actionName; color: root.textColor; font.pixelSize: 12; font.family: "Courier"; elide: Text.ElideRight }
                                            }
                                        }
                                    }
                                }
                            }
                            Rectangle {
                                width: parent.width; height: 2; color: root.primaryColor; opacity: 0.8; visible: root.isCleaning
                                SequentialAnimation on y {
                                    running: root.isCleaning
                                    loops: Animation.Infinite
                                    NumberAnimation { from: 0; to: parent.height; duration: 1500 }
                                    NumberAnimation { from: parent.height; to: 0; duration: 0 }
                                }
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 46
                            Layout.maximumHeight: 46
                            spacing: 15
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                radius: 6
                                color: root.isCompleted ? root.primaryColor : root.bgDark
                                border.color: root.isCompleted ? "transparent" : root.borderColor
                                border.width: 1
                                opacity: root.isCompleted ? 1.0 : 0.4
                                RowLayout {
                                    anchors.centerIn: parent; spacing: 10
                                    Text { text: "💾"; color: root.isCompleted ? "white" : root.textMuted; font.pixelSize: 16 }
                                    Text { text: "完成清洗并生成记录"; color: root.isCompleted ? "white" : root.textMuted; font.bold: true; font.pixelSize: 14 }
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: root.isCompleted ? Qt.PointingHandCursor : Qt.ForbiddenCursor
                                    enabled: root.isCompleted
                                    onClicked: {
                                        saveDatasetNameInput.text = sourceDataCombo.currentText + "_清洗版"
                                        savePopup.open()
                                    }
                                }
                            }

                            Rectangle {
                                Layout.preferredWidth: 150
                                Layout.fillHeight: true
                                radius: 6
                                color: root.isCompleted ? Qt.rgba(245, 63, 63, 0.1) : root.bgDark
                                border.color: root.isCompleted ? root.dangerColor : root.borderColor
                                border.width: 1
                                opacity: root.isCompleted ? 1.0 : 0.4
                                RowLayout {
                                    anchors.centerIn: parent; spacing: 8
                                    Text { text: "✗"; color: root.isCompleted ? root.dangerColor : root.textMuted; font.bold: true; font.pixelSize: 14 }
                                    Text { text: "放弃清洗"; color: root.isCompleted ? root.dangerColor : root.textMuted; font.bold: true; font.pixelSize: 14 }
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: root.isCompleted ? Qt.PointingHandCursor : Qt.ForbiddenCursor
                                    enabled: root.isCompleted
                                    onClicked: {
                                        previewModel.clear()
                                        root.currentCount = 0
                                        root.isCompleted = false
                                        root.currentTaskId = 0
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // ================= 视图A：清洗历史列表 =================
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 15
        visible: root.viewMode === "history"

        RowLayout {
            Layout.fillWidth: true
            spacing: 15
            Label { text: "数据清洗流转历史"; font.pixelSize: 18; font.bold: true; color: root.textColor }
            Button {
                text: "修改任务名称"
                font.bold: true; font.pixelSize: 14
                Layout.preferredHeight: 30
                background: Rectangle { color: "transparent"; border.color: root.primaryColor; border.width: 1; radius: 4 }
                contentItem: Text { text: parent.text; color: root.primaryColor; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                onClicked: {
                    if (!root.currentHistoryItem || root.currentHistoryItem.taskId <= 0) {
                        root.showToast("❌ 没有可修改的任务")
                        return
                    }
                    renameTaskNameInput.text = root.currentHistoryTitle || root.currentHistoryItem.projectName || ""
                    renameTaskPopup.open()
                }
            }

            Item { Layout.fillWidth: true }
            Button {
                text: root.selectedExportCount > 0 ? "📥 导出选中项 (" + root.selectedExportCount + ")" : "📥 导出选中项"
                font.bold: true; font.pixelSize: 14
                enabled: root.selectedExportCount > 0
                background: Rectangle {
                    color: root.selectedExportCount > 0 ? root.successColor : root.bgDark
                    border.color: root.selectedExportCount > 0 ? "transparent" : root.borderColor
                    border.width: 1; radius: 4
                }
                contentItem: Text { text: parent.text; color: root.selectedExportCount > 0 ? "white" : root.textMuted; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                onClicked: exportPopup.open()
            }

            Button {
                text: "+ 新建清洗任务"
                font.bold: true; font.pixelSize: 14
                background: Rectangle { color: parent.pressed ? "#0277BD" : parent.hovered ? "#0288D1" : "#039BE5"; radius: 4 }
                contentItem: Text { text: parent.text; color: "black"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                onClicked: {
                    root.selectedStrategies = []
                    previewModel.clear()
                    root.currentCount = 0
                    root.isCompleted = false
                    root.currentTaskId = 0
                    backendService.getDatasets(1, 100, "")
                    newCleaningTaskPopup.open()
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: "transparent"
            clip: true

            ListView {
                id: historyListView
                anchors.fill: parent
                clip: true
                spacing: 12
                model: cleaningHistoryModel

                delegate: Rectangle {
                    id: cardItem
                    width: historyListView.width
                    height: 165
                    radius: 8
                    color: Theme.panel
                    border.color: model.isSelected ? root.primaryColor : (cardMa.containsMouse ? Theme.primary : root.borderColor)
                    border.width: 1

                    MouseArea {
                        id: cardMa
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: {
                            model.isSelected = !model.isSelected
                            root.updateExportCount()
                        }
                    }

                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 15
                        spacing: 20

                        Rectangle {
                            width: 22; height: 22; radius: 4
                            color: model.isSelected ? root.primaryColor : root.bgDark
                            border.color: model.isSelected ? root.primaryColor : root.textMuted
                            Text { text: "✓"; color: "white"; font.pixelSize: 14; font.bold: true; anchors.centerIn: parent; visible: model.isSelected }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 6

                            RowLayout {
                                Layout.fillWidth: true; spacing: 8
                                Label {
                                    text: "🚀 " + (model.projectName || "清洗任务#" + (model.taskId || "?"))
                                    color: root.primaryColor; font.pixelSize: 16; font.bold: true; elide: Text.ElideRight
                                    Layout.maximumWidth: 350
                                }
                                Item { Layout.fillWidth: true }
                                Label { text: "🕒 " + (model.time || ""); color: root.textMuted; font.pixelSize: 12 }
                            }

                            RowLayout {
                                Layout.fillWidth: true; spacing: 10
                                Label { text: "源数据集: "; color: root.textMuted; font.pixelSize: 13 }
                                Label { text: model.sourceDataset || "-"; color: root.textColor; font.pixelSize: 13; Layout.maximumWidth: 200; elide: Text.ElideRight }
                                Rectangle { width: 1; height: 12; color: root.borderColor }
                                Label { text: "状态: "; color: root.textMuted; font.pixelSize: 13 }
                                Label {
                                    text: {
                                        var s = model.status || ""
                                        if (s === "completed") return "✅ 已完成"
                                        if (s === "running") return "⏳ 运行中 (" + (model.progress || 0) + "%)"
                                        if (s === "failed") return "❌ 失败"
                                        if (s === "pending") return "📋 等待中"
                                        if (s === "cancelled") return "⏹ 已取消"
                                        return s
                                    }
                                    color: model.status === "completed" ? root.successColor : (model.status === "failed" ? root.dangerColor : root.textColor)
                                    font.pixelSize: 13
                                }
                            }

                            Rectangle {
                                id: runningHistoryProgress
                                Layout.fillWidth: true
                                Layout.preferredHeight: 6
                                visible: model.status === "running"
                                color: root.bgDark
                                radius: 3
                                Rectangle {
                                    height: parent.height
                                    width: parent.width * Math.max(0, Math.min(1, (model.progress || 0) / 100.0))
                                    color: root.primaryColor
                                    radius: 3
                                    Behavior on width { NumberAnimation { duration: 120 } }
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                Label { text: "使用算法: "; color: root.textMuted; font.pixelSize: 13 }
                                Label { text: model.algos || "未知"; color: root.textColor; font.pixelSize: 13; Layout.fillWidth: true; elide: Text.ElideRight; font.bold: true }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                Label { text: "清洗数据集: "; color: root.textMuted; font.pixelSize: 13 }
                                Label { text: model.cleanedDataset || "(清洗完成后保存)"; color: root.textColor; font.pixelSize: 13; Layout.maximumWidth: 200; elide: Text.ElideRight }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                Label { text: "存储路径: " + (model.path || "(系统自动管理)"); color: root.textMuted; font.pixelSize: 12; font.family: "Courier"; elide: Text.ElideRight; Layout.fillWidth: true }
                            }
                        }

                        ColumnLayout {
                            Layout.alignment: Qt.AlignVCenter | Qt.AlignRight
                            spacing: 10

                            Button {
                                text: "查看详情"
                                Layout.preferredWidth: 90; Layout.preferredHeight: 30
                                background: Rectangle { color: parent.hovered ? Theme.hover : Theme.control; radius: 4; border.color: Theme.border }
                                contentItem: Text { text: parent.text; color: "#D1D5DB"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                onClicked: {
                                    var detailIds = root.parseAlgorithmIds(model.algorithmIdsText || model.algorithmIds || "")
                                    var detailParams = root.parseJsonObject(model.parametersJsonText || model.parameters || {})
                                    root.currentHistoryItem = {
                                        taskId: model.taskId || 0,
                                        title: model.projectName,
                                        projectName: model.projectName,
                                        sourceDataset: model.sourceDataset,
                                        cleanedDataset: model.cleanedDataset,
                                        algos: model.algos,
                                        algorithmIds: detailIds,
                                        parameters: detailParams,
                                        time: model.time
                                    }
                                    root.currentHistoryTitle = model.projectName || ""
                                    root.currentHistoryIndex = index
                                    root.detailAlgorithmIds = detailIds
                                    var algoItems = []
                                    for (var ai = 0; ai < root.detailAlgorithmIds.length; ai++) {
                                        var aid = root.detailAlgorithmIds[ai]
                                        algoItems.push({
                                            aid: aid,
                                            aname: root.algorithmNameMap[String(aid)] || ("算法#" + aid)
                                        })
                                    }
                                    root.detailAlgorithmItems = algoItems
                                    root.detailParameters = detailParams
                                    root.hasDetailCustomParams = root.computeHasDetailParams(root.detailParameters)
                                    if (model.taskId && model.taskId > 0) {
                                        backendService.getCleaningSuggestions(model.taskId, "", 1, 200)
                                    }
                                    root.viewMode = "fileDetail"
                                }
                            }

                            Button {
                                text: "删除"
                                Layout.preferredWidth: 90; Layout.preferredHeight: 30
                                background: Rectangle { color: parent.hovered ? "#BE123C" : "transparent"; border.color: root.dangerColor; border.width: 1; radius: 4 }
                                contentItem: Text { text: parent.text; color: parent.hovered ? "white" : root.dangerColor; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                onClicked: {
                                    root.pendingDeleteIndex = index
                                    deleteConfirmPopup.open()
                                }
                            }
                        }
                    }
                }

                Text {
                    anchors.centerIn: parent
                    text: "暂无清洗历史记录"
                    color: Theme.muted
                    font.pixelSize: 16
                    visible: cleaningHistoryModel.count === 0
                }
            }
        }
    }

    // ================= 视图B：任务详情 (复用清洗任务界面布局) =================
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 15
        visible: root.viewMode === "fileDetail"

        RowLayout {
            Layout.fillWidth: true
            spacing: 15

            Button {
                text: "⬅ 返回历史"
                font.bold: true; font.pixelSize: 14
                background: Rectangle { color: "transparent"; border.color: Theme.border; border.width: 1; radius: 4 }
                contentItem: Text { text: parent.text; color: "#4DD0E1"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                onClicked: {
                    root.viewMode = "history"
                    backendService.getCleaningTasks(0, "")
                }
            }

            Label {
                text: root.currentHistoryItem ? "📂 " + (root.currentHistoryItem.projectName || ("#" + root.currentHistoryItem.taskId)) : ""
                font.pixelSize: 16; font.bold: true; color: root.primaryColor
            }

            Item { Layout.fillWidth: true }

            Label {
                text: "共 " + previewModel.count + " 条清洗记录"
                color: Theme.muted; font.pixelSize: 13
            }

            Button {
                text: "▶ 刷新数据"
                font.bold: true; font.pixelSize: 14
                background: Rectangle { color: root.primaryColor; radius: 4 }
                contentItem: Text { text: parent.text; color: "black"; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                onClicked: {
                    if (root.currentHistoryItem && root.currentHistoryItem.taskId > 0) {
                        backendService.getCleaningSuggestions(root.currentHistoryItem.taskId, "", 1, 200)
                    }
                }
            }
        }

        // 详情布局：左侧为历史任务使用的清洗算法，右侧为样本图片和清洗决策。
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 15

            // 左栏：已使用的算法
            Rectangle {
                Layout.preferredWidth: 260
                Layout.fillHeight: true
                color: root.panelBg
                radius: 8
                border.color: root.borderColor
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 15
                    spacing: 12
                    Text { text: "📂 已使用算法"; color: root.textColor; font.bold: true; font.pixelSize: 15 }
                    Text {
                        visible: root.detailAlgorithmItems.length === 0
                        text: "未记录算法信息"
                        color: root.textMuted; font.pixelSize: 12
                    }
                    ScrollView {
                        id: algoScrollView
                        Layout.fillWidth: true; Layout.preferredHeight: 180; clip: true
                        visible: root.detailAlgorithmItems.length > 0
                        Column {
                            id: algoColumn
                            width: parent.width; spacing: 6
                            Repeater {
                                model: root.detailAlgorithmItems
                                delegate: Rectangle {
                                    width: algoColumn.width; height: 42; radius: 4; color: root.tableHoverBg
                                    Text {
                                        text: "🔹 " + (modelData.aname || ("算法#" + modelData.aid))
                                        color: root.primaryColor; font.bold: true; font.pixelSize: 13
                                        anchors.verticalCenter: parent.verticalCenter; anchors.left: parent.left; anchors.leftMargin: 12
                                    }
                                }
                            }
                        }
                    }

                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: root.borderColor }
                    Text { text: "配置参数"; color: root.textColor; font.bold: true; font.pixelSize: 14 }
                    Text {
                        visible: !root.hasDetailCustomParams
                        text: "无额外配置参数"
                        color: root.textMuted; font.pixelSize: 12
                    }
                    ScrollView {
                        Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                        visible: root.hasDetailCustomParams
                        Column {
                            id: detailParamColumn
                            width: parent.width; spacing: 8
                            Repeater {
                                model: root.detailParameterItems(root.detailParameters)
                                delegate: Column {
                                    width: detailParamColumn.width; spacing: 4
                                    Text { text: modelData.k; color: root.textMuted; font.pixelSize: 11; elide: Text.ElideRight; width: parent.width }
                                    Rectangle {
                                        width: parent.width; height: 28; color: root.bgDark; radius: 4; border.color: root.borderColor; border.width: 1
                                        Text {
                                            text: String(modelData.v)
                                            color: root.textColor; font.pixelSize: 12
                                            anchors.verticalCenter: parent.verticalCenter; anchors.left: parent.left; anchors.right: parent.right
                                            anchors.leftMargin: 8; anchors.rightMargin: 8
                                            elide: Text.ElideRight
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // 右栏：图片与清洗决策
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: root.panelBg
                radius: 8
                border.color: root.borderColor
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 20
                    spacing: 15
                    Text { text: "清洗结果详情"; color: root.textColor; font.bold: true; font.pixelSize: 16 }
                    Rectangle {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        color: root.bgDark; radius: 6; border.color: root.borderColor; border.width: 1; clip: true
                        ColumnLayout {
                            anchors.centerIn: parent; spacing: 10
                            visible: previewModel.count === 0
                            Text { text: "LOADING_RESULTS"; color: root.textMuted; font.pixelSize: 14; font.family: "Courier"; font.bold: true; Layout.alignment: Qt.AlignHCenter }
                        }
                        ListView {
                            id: detailFileListView
                            anchors.fill: parent; anchors.margins: 10; spacing: 8; model: previewModel; clip: true
                            delegate: Rectangle {
                                width: detailFileListView.width; height: 64; radius: 4
                                color: ma.containsMouse ? root.tableHoverBg : "transparent"
                                border.color: ma.containsMouse ? root.primaryColor : "transparent"
                                border.width: 1
                                MouseArea {
                                    id: ma
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        if (sampleId > 0) {
                                            root.pendingPreviewId = sampleId
                                            backendService.getSamplePreview(sampleId)
                                        }
                                    }
                                }
                                RowLayout {
                                    anchors.fill: parent; anchors.margins: 10; spacing: 16

                                    Rectangle {
                                        Layout.preferredWidth: 58
                                        Layout.preferredHeight: 44
                                        Layout.alignment: Qt.AlignVCenter
                                        radius: 4
                                        color: root.panelBg
                                        border.color: root.borderColor
                                        clip: true
                                        Image {
                                            id: sampleThumb
                                            anchors.fill: parent
                                            anchors.margins: 2
                                            source: {
                                                var ext = String(samplePath).toLowerCase().split('.').pop()
                                                var isImg = ["jpg","jpeg","png","bmp","gif","webp","tif","tiff"].indexOf(ext) >= 0
                                                return isImg ? root.localFileUrl(samplePath) : ""
                                            }
                                            fillMode: Image.PreserveAspectCrop
                                            asynchronous: true
                                            visible: {
                                                var ext = String(samplePath).toLowerCase().split('.').pop()
                                                return ["jpg","jpeg","png","bmp","gif","webp","tif","tiff"].indexOf(ext) >= 0 && samplePath !== ""
                                            }
                                        }
                                        Text {
                                            anchors.centerIn: parent
                                            text: {
                                                var ext = String(samplePath).toLowerCase().split('.').pop()
                                                if (ext === "csv") return "📊"
                                                if (ext === "txt" || ext === "log") return "📄"
                                                if (["wav","mp3","aac","flac"].indexOf(ext) >= 0) return "🎵"
                                                return "📁"
                                            }
                                            color: root.textColor
                                            font.pixelSize: 22
                                            visible: {
                                                var ext = String(samplePath).toLowerCase().split('.').pop()
                                                var isImg = ["jpg","jpeg","png","bmp","gif","webp","tif","tiff"].indexOf(ext) >= 0
                                                return !isImg && samplePath !== ""
                                            }
                                        }
                                        Text {
                                            anchors.centerIn: parent
                                            text: "图片"
                                            color: root.textMuted
                                            font.pixelSize: 12
                                            visible: samplePath === ""
                                        }
                                    }

                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        Layout.alignment: Qt.AlignVCenter
                                        spacing: 2
                                        Text { text: sourceName || "未知样本"; color: root.textColor; font.pixelSize: 12; font.family: "Courier"; elide: Text.ElideRight; Layout.fillWidth: true }
                                        Text { text: (issueType || "-") + " · " + (confidence ? (confidence * 100).toFixed(0) + "%" : "-"); color: root.textMuted; font.pixelSize: 10; elide: Text.ElideRight; Layout.fillWidth: true }
                                    }

                                    ColumnLayout {
                                        Layout.preferredWidth: 130
                                        Layout.alignment: Qt.AlignVCenter
                                        spacing: 4
                                        Text { text: "清洗决策"; color: root.textMuted; font.pixelSize: 10 }
                                        Rectangle {
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 28
                                            radius: 4
                                            color: root.decisionBackgroundColor(actionName)
                                            border.color: root.decisionAccentColor(actionName)
                                            border.width: 1
                                            Text {
                                                anchors.centerIn: parent
                                                text: actionName || "-"
                                                color: root.decisionAccentColor(actionName)
                                                font.pixelSize: 13
                                                font.bold: true
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    Popup {
        id: renameTaskPopup
        width: 360
        height: 180
        modal: true
        focus: true
        x: Math.round((root.width - width) / 2)
        y: Math.round((root.height - height) / 2)
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { color: root.panelBg; radius: 8; border.color: root.borderColor; border.width: 1 }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 20
            spacing: 15
            Text { text: "修改任务名称"; color: root.textColor; font.pixelSize: 16; font.bold: true }
            Rectangle {
                Layout.fillWidth: true; height: 36; color: root.bgDark; radius: 4; border.color: root.borderColor; border.width: 1
                TextInput {
                    id: renameTaskNameInput
                    color: root.primaryColor; font.pixelSize: 13; font.bold: true
                    anchors.fill: parent; leftPadding: 10; verticalAlignment: TextInput.AlignVCenter; selectByMouse: true
                }
            }
            Item { Layout.fillHeight: true }
            RowLayout {
                Layout.fillWidth: true
                spacing: 15
                Item { Layout.fillWidth: true }
                Button {
                    text: "取消"
                    Layout.preferredWidth: 80; Layout.preferredHeight: 32
                    background: Rectangle { color: "transparent"; border.color: root.borderColor; border.width: 1; radius: 4 }
                    contentItem: Text { text: parent.text; color: root.textMuted; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: renameTaskPopup.close()
                }
                Button {
                    text: "保存"
                    Layout.preferredWidth: 80; Layout.preferredHeight: 32
                    background: Rectangle { color: root.primaryColor; radius: 4 }
                    contentItem: Text { text: parent.text; color: "black"; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: {
                        var newTitle = renameTaskNameInput.text.trim()
                        if (!root.currentHistoryItem || root.currentHistoryItem.taskId <= 0) {
                            root.showToast("❌ 没有可修改的任务")
                        } else if (newTitle === "") {
                            root.showToast("❌ 任务名称不能为空")
                        } else {
                            var result = backendService.updateTaskTitle(root.currentHistoryItem.taskId, newTitle)
                            if (result && result.status === "success") {
                                var updated = result.data || {}
                                var finalTitle = updated.title || newTitle
                                var index = root.currentHistoryIndex
                                if (index >= 0) {
                                    cleaningHistoryModel.setProperty(index, "projectName", finalTitle)
                                }
                                root.currentHistoryTitle = finalTitle
                                if (root.currentHistoryItem) {
                                    root.currentHistoryItem.projectName = finalTitle
                                    root.currentHistoryItem.title = finalTitle
                                }
                                root.showToast("✅ 任务名称已更新为 " + finalTitle)
                                backendService.getCleaningTasks(0, "")
                            } else {
                                root.showToast("❌ " + ((result && result.message) ? result.message : "修改失败"))
                            }
                        }
                        renameTaskPopup.close()
                    }
                }
            }
        }
    }
}
