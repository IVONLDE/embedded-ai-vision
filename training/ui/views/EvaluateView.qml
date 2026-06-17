import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
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
    readonly property color warningColor: Theme.warning
    readonly property color dangerColor: Theme.danger
    readonly property color tableHoverBg: Theme.hover

    HelpIcon {
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.topMargin: -16
        anchors.rightMargin: -16
        title: "仿真评估帮助"
        body: "本页用于创建训练任务、执行仿真评估，并查看训练/评估历史。\n\n1. 左侧历史区分为训练任务和评估任务，可查看任务状态、场景、数据集、算法、进度和结果摘要。\n2. 点击“新建任务”后，先选择应用场景。场景会过滤可用算法，例如舰船目标识别、开放集识别、故障诊断或多模态融合等。\n3. 选择数据集后，再选择训练算法或骨干网络。不同算法会显示对应动态参数，可在“参数配置”弹窗中调整训练轮数、批大小、学习率、模型路径等。\n4. 点击开始训练后，系统会创建训练任务并在后台运行。训练完成后会保存 checkpoint、日志和训练结果，供后续评估使用。\n5. 评估阶段会根据场景和算法绑定关系加载对应评估插件，读取训练产物或数据集，计算场景指标、分类指标、开放集指标或融合评估指标。\n6. 任务详情区可查看训练状态、评估结果、指标表格和输出信息。可对历史任务重命名、删除，也可保存项目记录。\n7. 如果任务失败，请优先检查数据集是否包含有效样本、算法是否启用、参数范围是否合理、模型权重或标签文件路径是否存在。\n8. 建议先完成训练，再运行评估；同一场景下保持数据集、训练算法和评估算法匹配，结果才具备可比性。"
    }

    property string viewMode: "history"
    property bool isTraining: false
    property bool isEvaluating: false
    property bool isAllSelected: false
    property int taskCounter: 1
    property int currentTrainingTaskId: 0
    property int currentEvalTaskId: 0
    property var pendingEvalTaskIds: []
    property var currentHistoryItem: null
    property int pendingDeleteIndex: -1
    property int pendingEditIndex: -1
    property bool trainingHistoryExpanded: true
    property bool evaluationHistoryExpanded: true
    property string workMode: "train"  // "train" / "eval"
    property bool trainingWorkbenchExpanded: true
    property bool evaluationWorkbenchExpanded: false
    property real evalTableContentX: 0

    property var algorithmNameMap: ({})
    property var evalAlgorithmMap: ({})
    property var algoParamsMap: ({})
    property string pendingAlgoKey: ""
    property var evalMetricHeaders: []
    // 访问主窗口的全局状态管理器 (跨页面切换保持数据)
    property var appState: typeof window !== "undefined" && window ? window.appState : null

    // 训练算法 -> 评估算法 绑定表 (key -> key)
    property var trainingToEvalKey: ({
        "training.image.sonar_oltr_classifier": "evaluation.multimodal.sonar_oltr_plud",
        "training.image.yolov5_detector": "evaluation.image.yolov5_evaluator",
        "training.timeseries.ship_predictor": "evaluation.timeseries.ship_evaluator",
        "training.timeseries.hyfd_fault_diagnosis": "evaluation.timeseries.hyfd_fault_evaluator",
        "training.multimodal.fusion_detector": "evaluation.multimodal.fusion_evaluator",
        "training.multimodal.seg": "evaluation.multimodal.seg_evaluator"
    })

    // 场景 → 算法 绑定表 (按场景key过滤算法key)
    property var scenarioAlgoMap: ({})
    // 所有训练算法的完整列表 (用于场景过滤)
    property var allTrainingAlgos: []

    ListModel { id: scenarioModel }
    ListModel { id: datasetModel }
    ListModel { id: algoModel }
    ListModel { id: taskQueueModel }
    ListModel { id: evalResultModel }
    ListModel { id: evalHistoryModel }
    ListModel { id: currentDetailModel }
    ListModel { id: weightOptionModel }
    ListModel { id: activeEvalSourceModel }

    function checkStates() {
        var _allSel = taskQueueModel.count > 0
        for (var i = 0; i < taskQueueModel.count; i++) {
            if (!taskQueueModel.get(i).isSelected) _allSel = false
        }
        root.isAllSelected = _allSel
    }

    function workbenchContentHeight() {
        var total = 0
        total += 46
        if (root.trainingWorkbenchExpanded) total += 80
        total += root.workbenchMainHeight()
        total += (!root.trainingWorkbenchExpanded && !root.evaluationWorkbenchExpanded) ? 80 : 60
        return total
    }

    function workbenchMainHeight() {
        var total = 0
        if (root.trainingWorkbenchExpanded) total += 309
        total += (root.workMode === "eval" && root.evaluationWorkbenchExpanded) ? 640 : 0
        if (root.trainingWorkbenchExpanded) total += 15
        return total
    }

    function filterAlgorithmsByScenario() {
        algoModel.clear()
        var scIdx = scenarioCombo.currentIndex
        var scKey = scIdx >= 0 ? (scenarioModel.get(scIdx).key || "") : ""
        var allowedKeys = root.scenarioAlgoMap[scKey] || []
        for (var i = 0; i < root.allTrainingAlgos.length; i++) {
            var algo = root.allTrainingAlgos[i]
            // 无场景映射时显示所有算法，有映射则只显示匹配的
            if (allowedKeys.length === 0 || allowedKeys.indexOf(algo.key) >= 0) {
                algoModel.append(algo)
            }
        }
        if (algoModel.count > 0) algoCombo.currentIndex = 0
    }

    function getCurrentTime() {
        var d = new Date()
        return d.getFullYear() + "-" + String(d.getMonth()+1).padStart(2,'0') + "-" + String(d.getDate()).padStart(2,'0')
               + " " + String(d.getHours()).padStart(2,'0') + ":" + String(d.getMinutes()).padStart(2,'0')
    }

    function algorithmName(algoId) {
        var id = Number(algoId)
        for (var i = 0; i < algoModel.count; i++) {
            var a = algoModel.get(i)
            if (Number(a.id) === id) return a.name
        }
        return root.algorithmNameMap[String(algoId)] || ("算法#" + algoId)
    }

    function algorithmKeyById(algoId) {
        var id = Number(algoId)
        for (var i = 0; i < root.allTrainingAlgos.length; i++) {
            var algo = root.allTrainingAlgos[i]
            if ((algo.id || 0) === id) return algo.key || ""
        }
        return ""
    }

    function normalizeParamToken(value) {
        return String(value || "").toLowerCase().replace(/[\s_\-]/g, "")
    }

    function resolveTrainingParamValue(params, algoId, aliases, labelKeywords) {
        var source = params || {}
        var defs = root.algoParamsMap[String(algoId)] || []
        var aliasTokens = []
        var labelTokens = []
        var directKeys = Object.keys(source)

        for (var ai = 0; ai < aliases.length; ai++) aliasTokens.push(root.normalizeParamToken(aliases[ai]))
        for (var li = 0; li < labelKeywords.length; li++) labelTokens.push(String(labelKeywords[li] || "").toLowerCase())

        for (var di = 0; di < defs.length; di++) {
            var def = defs[di]
            var keyName = String(def.name || "")
            var keyToken = root.normalizeParamToken(keyName)
            var labelText = String(def.label || keyName || "").toLowerCase()
            var matched = aliasTokens.indexOf(keyToken) !== -1
            if (!matched) {
                for (var lk = 0; lk < labelTokens.length; lk++) {
                    if (labelText.indexOf(labelTokens[lk]) !== -1) {
                        matched = true
                        break
                    }
                }
            }
            if (matched && source[keyName] !== undefined && source[keyName] !== null && source[keyName] !== "") {
                return source[keyName]
            }
        }

        for (var ki = 0; ki < directKeys.length; ki++) {
            var rawKey = directKeys[ki]
            var rawToken = root.normalizeParamToken(rawKey)
            var rawLower = String(rawKey || "").toLowerCase()
            if (aliasTokens.indexOf(rawToken) !== -1) return source[rawKey]
            for (var lj = 0; lj < labelTokens.length; lj++) {
                if (rawLower.indexOf(labelTokens[lj]) !== -1) return source[rawKey]
            }
        }
        return ""
    }

    function displayTrainingParamValue(value) {
        if (value === undefined || value === null || value === "") return "未设置"
        if (typeof value === "object") return JSON.stringify(value)
        return String(value)
    }

    function buildTrainingParamSummary(params, algoId) {
        return [
            "骨干网络: " + root.displayTrainingParamValue(root.resolveTrainingParamValue(params, algoId, ["backbone", "backbone_network", "network", "arch", "model", "model_name"], ["骨干", "网络"])),
            "训练轮次: " + root.displayTrainingParamValue(root.resolveTrainingParamValue(params, algoId, ["epochs", "epoch", "num_epochs"], ["训练轮次", "轮次", "epoch"])),
            "批大小: " + root.displayTrainingParamValue(root.resolveTrainingParamValue(params, algoId, ["batch_size", "batchsize", "batch"], ["批大小", "batch"])),
            "学习率: " + root.displayTrainingParamValue(root.resolveTrainingParamValue(params, algoId, ["learning_rate", "lr"], ["学习率", "lr"]))
        ].join(" | ")
    }

    function findWeightOptionByTaskId(taskId) {
        var id = Number(taskId || 0)
        for (var i = 0; i < weightOptionModel.count; i++) {
            var item = weightOptionModel.get(i)
            if (Number(item.taskId || 0) === id) return item
        }
        return null
    }

    function buildTrainingDetailFromTask(taskId, fallbackItem) {
        var item = root.findWeightOptionByTaskId(taskId)
        var datasetName = ""
        var algoName = ""
        var algoId = 0
        var params = {}

        if (item) {
            datasetName = item.dataset || ""
            algoName = item.algo || ""
            algoId = item.algoId || 0
            params = item.params || {}
        } else if (fallbackItem) {
            datasetName = fallbackItem.datasets || ""
            algoName = fallbackItem.algos || ""
        }

        var detail = {
            dataset: datasetName,
            algo: algoName,
            "骨干网络": root.displayTrainingParamValue(root.resolveTrainingParamValue(params, algoId, ["backbone", "backbone_network", "network", "arch", "model", "model_name"], ["骨干", "网络"])),
            "训练轮次": root.displayTrainingParamValue(root.resolveTrainingParamValue(params, algoId, ["epochs", "epoch", "num_epochs"], ["训练轮次", "轮次", "epoch"])),
            "批大小": root.displayTrainingParamValue(root.resolveTrainingParamValue(params, algoId, ["batch_size", "batchsize", "batch"], ["批大小", "batch"])),
            "学习率": root.displayTrainingParamValue(root.resolveTrainingParamValue(params, algoId, ["learning_rate", "lr"], ["学习率", "lr"]))
        }
        return detail
    }

    function scenarioNameById(scenarioId) {
        var id = Number(scenarioId)
        for (var i = 0; i < scenarioModel.count; i++) {
            var scenario = scenarioModel.get(i)
            if ((scenario.id || 0) === id) return scenario.name || ""
        }
        return ""
    }

    function trainingStatusCode(status) {
        if (status === "completed") return 2
        if (status === "running") return 1
        if (status === "failed") return 3
        if (status === "interrupted" || status === "cancelled") return 4
        return 0
    }

    function trainingStatusLabel(status) {
        if (status === "completed") return "已完成"
        if (status === "failed") return "失败"
        if (status === "interrupted" || status === "cancelled") return "中断"
        if (status === "running") return "训练中"
        return "待训练"
    }

    function historyHasTask(taskId) {
        var id = Number(taskId || 0)
        if (id <= 0) return false
        for (var i = 0; i < evalHistoryModel.count; i++) {
            var item = evalHistoryModel.get(i)
            var ids = []
            try {
                ids = JSON.parse(item.taskIdsJson || "[]")
            } catch(e) {
                ids = []
            }
            for (var j = 0; j < ids.length; j++) {
                if (Number(ids[j]) === id) return true
            }
        }
        return false
    }

    function buildAutoHistoryEntry(task) {
        var payload = task.payload || {}
        var taskId = task.id || 0
        var status = task.status || ""
        var resultJson = task.result || {}
        var artifactCount = resultJson.artifacts ? resultJson.artifacts.length : 0
        var algoId = task.algorithm_id || 0
        var taskParams = task.parameters || {}
        var details = {
            dataset: task.source_dataset_name || ("数据集#" + (task.source_dataset_id || 0)),
            algo: algorithmName(algoId),
            "骨干网络": root.displayTrainingParamValue(root.resolveTrainingParamValue(taskParams, algoId, ["backbone", "backbone_network", "network", "arch", "model", "model_name"], ["骨干", "网络"])),
            "训练轮次": root.displayTrainingParamValue(root.resolveTrainingParamValue(taskParams, algoId, ["epochs", "epoch", "num_epochs"], ["训练轮次", "轮次", "epoch"])),
            "批大小": root.displayTrainingParamValue(root.resolveTrainingParamValue(taskParams, algoId, ["batch_size", "batchsize", "batch"], ["批大小", "batch"])),
            "学习率": root.displayTrainingParamValue(root.resolveTrainingParamValue(taskParams, algoId, ["learning_rate", "lr"], ["学习率", "lr"]))
        }
        if (resultJson.summary) details["训练摘要"] = resultJson.summary
        return {
            historyType: "training",
            projectName: "训练任务 #" + taskId,
            scenario: scenarioNameById(payload.scenario_id || 0),
            datasets: details.dataset,
            algos: details.algo,
            trainStatus: trainingStatusLabel(status),
            evalReport: status === "completed" ? ("训练完成，模型产物 " + artifactCount + " 个") : ("训练" + trainingStatusLabel(status)),
            time: root.getCurrentTime(),
            detailsJson: JSON.stringify([details]),
            taskIdsJson: JSON.stringify([taskId])
        }
    }

    function historyEntryType(item) {
        if (!item) return "evaluation"
        if (item.historyType === "training" || item.historyType === "evaluation") return item.historyType
        var projectName = item.projectName || ""
        if (projectName.indexOf("训练任务 #") === 0) return "training"
        var taskIds = []
        try {
            taskIds = JSON.parse(item.taskIdsJson || "[]")
        } catch(e) {
            taskIds = []
        }
        return taskIds.length > 0 ? "training" : "evaluation"
    }

    function historyIndexesByType(type) {
        var indexes = []
        for (var i = 0; i < evalHistoryModel.count; i++) {
            if (historyEntryType(evalHistoryModel.get(i)) === type) indexes.push(i)
        }
        return indexes
    }

    function historyTaskIds(item) {
        if (!item) return []
        try {
            var ids = JSON.parse(item.taskIdsJson || "[]")
            return Array.isArray(ids) ? ids : []
        } catch(e) {
            return []
        }
    }

    function deleteHistoryEntry(index) {
        if (index < 0 || index >= evalHistoryModel.count) return false
        var item = evalHistoryModel.get(index)
        var taskIds = historyTaskIds(item)
        var deleteIds = []

        for (var qi = taskQueueModel.count - 1; qi >= 0; qi--) {
            var q = taskQueueModel.get(qi)
            var matched = taskIds.indexOf(q.taskId || 0) !== -1 || taskIds.indexOf(q.evalTaskId || 0) !== -1
            if (!matched) continue
            if ((q.evalTaskId || 0) > 0 && deleteIds.indexOf(q.evalTaskId) === -1) deleteIds.push(q.evalTaskId)
            if ((q.taskId || 0) > 0 && deleteIds.indexOf(q.taskId) === -1) deleteIds.push(q.taskId)
            taskQueueModel.remove(qi)
        }

        for (var ti = 0; ti < taskIds.length; ti++) {
            var taskId = taskIds[ti] || 0
            if (taskId > 0 && deleteIds.indexOf(taskId) === -1) deleteIds.push(taskId)
        }

        for (var ri = evalResultModel.count - 1; ri >= 0; ri--) {
            var resultTaskId = evalResultModel.get(ri).taskId || 0
            if (deleteIds.indexOf(resultTaskId) !== -1) evalResultModel.remove(ri)
        }

        for (var di = 0; di < deleteIds.length; di++) {
            backendService.deleteTask(deleteIds[di])
        }

        evalHistoryModel.remove(index)
        root.checkStates()
        root.saveToAppState()
        return true
    }

    function syncHistoryFromTrainingTask(task) {
        if (!task) return
        var status = task.status || ""
        if (status !== "completed" && status !== "failed" && status !== "interrupted" && status !== "cancelled") return
        if (historyHasTask(task.id || 0)) return
        evalHistoryModel.insert(0, buildAutoHistoryEntry(task))
    }

    function upsertTrainingTask(task) {
        if (!task) return
        var taskId = task.id || 0
        var payload = task.payload || {}
        var matchedIndex = -1
        for (var i = 0; i < taskQueueModel.count; i++) {
            if ((taskQueueModel.get(i).taskId || 0) === taskId) {
                matchedIndex = i
                break
            }
        }

        var scenarioName = scenarioNameById(payload.scenario_id || 0)
        var datasetName = task.source_dataset_name || ("数据集#" + (task.source_dataset_id || 0))
        var algoId = task.algorithm_id || 0
        var algoName = algorithmName(algoId)
        var algoKey = algorithmKeyById(algoId)
        var trainStatus = trainingStatusCode(task.status || "")
        var trainProgress = (task.progress || 0) / 100.0
        var progressMessage = task.progress_message || ""
        var taskParams = task.parameters || {}
        var resultJson = task.result || {}
        var outputDir = task.output_dir || ""

        if (matchedIndex >= 0) {
            taskQueueModel.setProperty(matchedIndex, "scenario", scenarioName || taskQueueModel.get(matchedIndex).scenario || "")
            taskQueueModel.setProperty(matchedIndex, "dataset", datasetName)
            taskQueueModel.setProperty(matchedIndex, "datasetId", task.source_dataset_id || 0)
            taskQueueModel.setProperty(matchedIndex, "algo", algoName)
            taskQueueModel.setProperty(matchedIndex, "algoId", algoId)
            taskQueueModel.setProperty(matchedIndex, "algoKey", algoKey || taskQueueModel.get(matchedIndex).algoKey || "")
            taskQueueModel.setProperty(matchedIndex, "trainStatus", trainStatus)
            taskQueueModel.setProperty(matchedIndex, "dbStatus", task.status || "")
            taskQueueModel.setProperty(matchedIndex, "trainProgress", trainProgress)
            taskQueueModel.setProperty(matchedIndex, "progressMessage", progressMessage)
            taskQueueModel.setProperty(matchedIndex, "params", taskParams)
            taskQueueModel.setProperty(matchedIndex, "resultJson", resultJson)
            taskQueueModel.setProperty(matchedIndex, "outputDir", outputDir)
            return
        }
    }

    function weightOptionIndex(taskId) {
        var id = Number(taskId || 0)
        for (var i = 0; i < weightOptionModel.count; i++) {
            if (Number(weightOptionModel.get(i).taskId || 0) === id) return i
        }
        return -1
    }

    function trainingTaskIdForEvalTask(evalTaskId) {
        var id = Number(evalTaskId || 0)
        if (id <= 0) return 0
        for (var i = 0; i < activeEvalSourceModel.count; i++) {
            var item = activeEvalSourceModel.get(i)
            if (Number(item.evalTaskId || 0) === id) return Number(item.trainingTaskId || 0)
        }
        return 0
    }

    function upsertWeightOption(task) {
        if (!task) return
        var taskId = Number(task.id || 0)
        if (taskId <= 0) return

        var status = task.status || ""
        var resultJson = task.result || {}
        var artifacts = resultJson.artifacts || []
        var checkpointPath = artifacts.length > 0 ? (artifacts[0] || "") : ""
        var existingIndex = root.weightOptionIndex(taskId)

        if (status !== "completed" || !checkpointPath) {
            if (existingIndex >= 0) weightOptionModel.remove(existingIndex)
            return
        }

        var payload = task.payload || {}
        var scenarioName = scenarioNameById(payload.scenario_id || 0)
        var datasetName = task.source_dataset_name || ("数据集#" + (task.source_dataset_id || 0))
        var algoId = task.algorithm_id || 0
        var algoName = algorithmName(algoId)
        var algoKey = algorithmKeyById(algoId)
        var taskParams = task.parameters || {}
        var selected = existingIndex >= 0 ? !!weightOptionModel.get(existingIndex).isSelected : false
        var item = {
            taskId: taskId,
            scenarioId: payload.scenario_id || 0,
            scenario: scenarioName,
            datasetId: task.source_dataset_id || 0,
            dataset: datasetName,
            algoId: algoId,
            algo: algoName,
            algoKey: algoKey,
            params: taskParams,
            checkpointPath: checkpointPath,
            checkpointName: checkpointPath.split(/[\\/]/).pop(),
            paramSummary: root.buildTrainingParamSummary(taskParams, algoId),
            summary: resultJson.summary || "",
            outputDir: task.output_dir || "",
            createdAt: task.created_at || "",
            isSelected: selected
        }

        if (existingIndex >= 0) {
            weightOptionModel.set(existingIndex, item)
        } else {
            // 按 taskId 降序插入，保持最新在前
            var ins = 0
            for (var wi = 0; wi < weightOptionModel.count; wi++) {
                if (Number(weightOptionModel.get(wi).taskId || 0) < taskId) break
                ins = wi + 1
            }
            weightOptionModel.insert(ins, item)
        }
    }

    // ================= 后端信号 =================
    Connections {
        target: backendService

        function onSettingValueLoaded(key, value) {
            if (key !== "eval_state" || !value) return
            try {
                var state = JSON.parse(value)
                root.isTraining = state.isTraining || false
                root.taskCounter = state.taskCounter || 1
                root.evalMetricHeaders = state.metricHeaders || []

                var h = state.evalHistory || []
                for (var hi = 0; hi < h.length; hi++) evalHistoryModel.append(h[hi])

                // 恢复任务队列：关闭时运行中的任务不保存，重开后都是已完成/待处理
                var q = state.taskQueue || []
                for (var qi = 0; qi < q.length; qi++) {
                    if (q[qi].trainStatus === 1) q[qi].trainStatus = 4  // 标记为中断
                    taskQueueModel.append(q[qi])
                    root.checkStates()
                }

                var r = state.evalResults || []
                for (var ri = 0; ri < r.length; ri++) evalResultModel.append(r[ri])
                var activeSources = state.activeEvalSources || []
                for (var ai = 0; ai < activeSources.length; ai++) activeEvalSourceModel.append(activeSources[ai])
                backendService.getTrainingTasks(0, "")
            } catch(e) {}
        }

        function onEvaluationScenariosUpdated(scenarios) {
            scenarioModel.clear()
            for (var i = 0; i < scenarios.length; i++) {
                scenarioModel.append({id: scenarios[i].id || 0, name: scenarios[i].name || scenarios[i].key || "", key: scenarios[i].key || ""})
            }
            if (scenarioModel.count > 0) scenarioCombo.currentIndex = 0
            // 场景加载完后检查是否有待恢复的训练任务
            root.restoreTrainingTasksFromBackend()
        }

        function onDatasetsUpdated(data) {
            var items = []
            if (data && data.items) items = data.items
            datasetModel.clear()
            for (var j = 0; j < items.length; j++) {
                var item = items[j]
                var n = item.name || ""
                var idx = n.indexOf("|Status:")
                var s = idx !== -1 ? n.substring(idx + 8) : (item.status || "")
                if (s !== "扩展文件") {
                    datasetModel.append({
                        id: item.id || 0,
                        name: (item.name || "未命名").split("|Status:")[0],
                        modality: item.modality || "",
                        parentId: item.parent_dataset_id || 0,
                        status: item.status || ""
                    })
                }
            }
            if (datasetModel.count === 0) datasetModel.append({id: 0, name: "无可用数据集 (请先导入)", modality: "", parentId: 0, status: ""})
        }

        function onAlgorithmsUpdated(algorithms) {
            if (!algorithms || !algorithms.length) return
            var map = {}
            var old = root.algorithmNameMap
            if (old) { var oks = Object.keys(old); for (var kk = 0; kk < oks.length; kk++) map[oks[kk]] = old[oks[kk]] }
            var oldEvalMap = root.evalAlgorithmMap || {}
            var evalMap = {}
            for (var ek in oldEvalMap) { if (oldEvalMap.hasOwnProperty(ek)) evalMap[ek] = oldEvalMap[ek] }
            var paramsMap = {}
            var trainingList = []
            var newScenarioAlgoMap = {}
            for (var i = 0; i < algorithms.length; i++) {
                var a = algorithms[i]
                map[String(a.id)] = a.name || a.key || ""
                if (a.parameters && a.parameters.length > 0) {
                    paramsMap[a.key || ""] = a.parameters
                    paramsMap[String(a.id)] = a.parameters
                }
                if (a.category === "evaluation") {
                    evalMap[a.key || a.name] = {id: a.id || 0, name: a.name || a.key || ""}
                } else if (a.category === "training") {
                    trainingList.push({id: a.id || 0, name: a.name || a.key || "", modality: a.modality || "", key: a.key || ""})
                    var vr = a.validation_rules || {}
                    var scKey = vr["scenario_key"] || ""
                    if (scKey) {
                        if (!newScenarioAlgoMap[scKey]) newScenarioAlgoMap[scKey] = []
                        newScenarioAlgoMap[scKey].push(a.key)
                    }
                    var boundKey = a.bound_evaluation_key || ""
                    if (boundKey && !root.trainingToEvalKey[a.key]) {
                        root.trainingToEvalKey[a.key] = boundKey
                    }
                }
            }
            root.algorithmNameMap = map
            root.evalAlgorithmMap = evalMap
            root.algoParamsMap = paramsMap
            root.allTrainingAlgos = trainingList
            root.scenarioAlgoMap = newScenarioAlgoMap
            root.filterAlgorithmsByScenario()
        }

        function onTrainingTasksUpdated(data) {
            var items = []
            if (data && data.items) items = data.items
            for (var i = 0; i < items.length; i++) {
                var task = items[i]
                root.upsertTrainingTask(task)
                root.upsertWeightOption(task)
                root.syncHistoryFromTrainingTask(task)
                if (task.status === "running") root.isTraining = true
            }
            if (root.isTraining) {
                var allDone = true
                for (var k = 0; k < taskQueueModel.count; k++) {
                    if (taskQueueModel.get(k).isSelected && taskQueueModel.get(k).trainStatus === 1) allDone = false
                }
                if (allDone) root.isTraining = false
            }
            // 同步到全局状态
            root.saveToAppState()
        }

        function onTrainingStatusUpdated(message, success, progressVal) {
            root.showToast(success ? "✅ " + message : "⚠️ " + message)
            if (!success) root.isTraining = false
            if (success) backendService.getTrainingTasks(0, "")  // 训练完成立即刷新状态
        }

        function onEvaluationStatusUpdated(message, success) {
            root.showToast(success ? "✅ " + message : "⚠️ " + message)
            if (!success) {
                root.pendingEvalTaskIds = []
                root.isEvaluating = false
            }
            // success时由 evalPollTimer 轮询拉取结果
        }

        function onEvaluationTasksUpdated(data) {
            if (root.isEvaluating && root.pendingEvalTaskIds.length > 0) {
                var items = data.items || []
                for (var ti = 0; ti < items.length; ti++) {
                    var it = items[ti]
                    var taskId = it.id || 0
                    var idx = root.pendingEvalTaskIds.indexOf(taskId)
                    if (idx >= 0) {
                        if (it.status === "completed") {
                            backendService.getEvaluationResults(taskId)
                            var newIds = root.pendingEvalTaskIds.slice()
                            newIds.splice(idx, 1)
                            root.pendingEvalTaskIds = newIds
                        } else if (it.status === "failed") {
                            root.isEvaluating = false
                            root.pendingEvalTaskIds = []
                            root.showToast("⚠️ 评估失败: " + (it.error_message || it.progress_message || "未知错误"))
                        }
                    }
                }
                if (root.pendingEvalTaskIds.length === 0) root.isEvaluating = false
            }
        }

        function onEvaluationResultsUpdated(data) {
            if (!evalMetricHeaders || evalMetricHeaders.length === 0) {
                evalMetricHeaders = []
            }
            var items = data && data.data ? data.data.items || [] : (data && data.items ? data.items : [])
            if (items.length === 0) return

            // 合并新旧指标键
            var existingKeys = evalMetricHeaders.length > 0 ? evalMetricHeaders.slice() : []
            var newKeys = []
            for (var i = 0; i < items.length; i++) {
                var mk = Object.keys(items[i].metrics || {})
                for (var k = 0; k < mk.length; k++) {
                    if (newKeys.indexOf(mk[k]) < 0 && existingKeys.indexOf(mk[k]) < 0) {
                        newKeys.push(mk[k])
                    }
                }
            }
            var skipKeys = ["num_classes", "class_names", "per_class_ap", "model_type", "num_test_sequences",
                           "label_distribution", "train_count", "val_count", "test_count", "feature_cols"]
            function filterKeys(keys) {
                var out = []
                for (var fi = 0; fi < keys.length; fi++) {
                    if (skipKeys.indexOf(keys[fi]) < 0) out.push(keys[fi])
                }
                return out
            }
            var allKeys = filterKeys(existingKeys.concat(newKeys))
            if (allKeys.length === 0) allKeys = ["accuracy", "macro_f1"]
            evalMetricHeaders = allKeys

            // 追加新结果行，同时记录已完成的任务ID
            var completedTaskIds = []
            for (var i = 0; i < items.length; i++) {
                var r = items[i]
                var m = r.metrics || {}
                var evalTaskId = r.task_id || 0
                var trainingTaskId = root.trainingTaskIdForEvalTask(evalTaskId)
                var vals = []
                for (var k = 0; k < allKeys.length; k++) {
                    var v = m[allKeys[k]]
                    if (v !== undefined && v !== null) {
                        if (typeof v === "number") vals.push(v < 10 ? Number(v).toFixed(4) : Number(v).toFixed(2))
                        else vals.push(String(v))
                    } else {
                        vals.push("-")
                    }
                }
                evalResultModel.append({
                    taskId: evalTaskId,
                    trainingTaskId: trainingTaskId,
                    modelName: r.model_name || "",
                    displayName: (trainingTaskId > 0 ? ("#" + trainingTaskId + " ") : "") + (r.model_name || r.method || "评估算法"),
                    evalMethod: r.model_name || r.method || "评估算法",
                    metricValues: vals,
                    metricValuesJson: JSON.stringify(vals),
                    summary: r.summary || ""
                })
                if (evalTaskId > 0 && completedTaskIds.indexOf(evalTaskId) < 0) {
                    completedTaskIds.push(evalTaskId)
                }
            }
            // 从pending列表中移除已完成的评估任务
            var remainingIds = root.pendingEvalTaskIds.slice()
            for (var ci = 0; ci < completedTaskIds.length; ci++) {
                var idx = remainingIds.indexOf(completedTaskIds[ci])
                if (idx >= 0) remainingIds.splice(idx, 1)
            }
            root.pendingEvalTaskIds = remainingIds
            root.saveToAppState()
            if (root.pendingEvalTaskIds.length === 0) {
                root.isEvaluating = false
                root.showToast("✅ 评估比对完成，共 " + evalResultModel.count + " 条结果")
            }
        }
    }

    Component.onCompleted: {
        backendService.getSetting("eval_state")
        backendService.getScenarios()
        backendService.getDatasets(1, 100, "")
        backendService.getAlgorithms("", "")
        root.restoreTrainingTasksFromBackend()
    }
    Component.onDestruction: {
        root.saveToAppState()
        toastCloseTimer.stop()
        evalPollTimer.stop()
    }

    // ================= 全局状态保存/恢复 =================
    function saveToAppState() {
        // 把 ListModel 序列化为 JSON 持久化到后端数据库
        var histArr = []
        for (var hi = 0; hi < evalHistoryModel.count; hi++) {
            var h = evalHistoryModel.get(hi)
            histArr.push({historyType: h.historyType || historyEntryType(h), projectName: h.projectName, scenario: h.scenario, datasets: h.datasets,
                          algos: h.algos, trainStatus: h.trainStatus, evalReport: h.evalReport,
                          time: h.time, detailsJson: h.detailsJson, taskIdsJson: h.taskIdsJson || "[]"})
        }

        var queueArr = []
        for (var qi = 0; qi < taskQueueModel.count; qi++) {
            var q = taskQueueModel.get(qi)
            // 不保存正在运行的任务（trainStatus===1），关闭后这些任务会被中断
            if (q.trainStatus === 1) continue
            queueArr.push({taskId: q.taskId, evalTaskId: q.evalTaskId, scenario: q.scenario,
                           dataset: q.dataset, datasetId: q.datasetId, algo: q.algo,
                           algoId: q.algoId, algoKey: q.algoKey, params: q.params,
                           isSelected: q.isSelected, trainStatus: q.trainStatus,
                           trainProgress: q.trainProgress, progressMessage: q.progressMessage,
                           dbStatus: q.dbStatus, resultJson: q.resultJson, outputDir: q.outputDir,
                           saved: q.saved || false})
        }

        var resArr = []
        for (var ri = 0; ri < evalResultModel.count; ri++) {
            var r = evalResultModel.get(ri)
            resArr.push({taskId: r.taskId, trainingTaskId: r.trainingTaskId, modelName: r.modelName, displayName: r.displayName, evalMethod: r.evalMethod,
                         metricValues: r.metricValues, metricValuesJson: r.metricValuesJson, summary: r.summary})
        }

        var activeEvalSources = []
        for (var ai = 0; ai < activeEvalSourceModel.count; ai++) {
            activeEvalSources.push(activeEvalSourceModel.get(ai))
        }

        var state = {
            evalHistory: histArr,
            taskQueue: queueArr,
            evalResults: resArr,
            activeEvalSources: activeEvalSources,
            metricHeaders: root.evalMetricHeaders,
            isTraining: root.isTraining,
            taskCounter: root.taskCounter
        }
        backendService.updateSetting("eval_state", JSON.stringify(state))
    }

    function restoreFromAppState() {
        // 从后端数据库加载持久化状态
        backendService.getSetting("eval_state")
    }

    function restoreTrainingTasksFromBackend() {
        // 场景加载完成后，以数据库状态同步训练队列
        if (scenarioModel.count === 0) return
        backendService.getTrainingTasks(0, "")
    }

    // ================= Toast =================
    property string toastMessage: ""
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

    function showToast(msg) {
        root.toastMessage = msg
        toastMsg.open()
        toastAnim.restart()
        toastCloseTimer.restart()
    }

    // ================= 保存评估工程弹窗 =================
    Popup {
        id: saveProjectPopup
        width: 460; height: 300
        modal: true; focus: true
        x: Math.round((root.width - width) / 2)
        y: Math.round((root.height - height) / 2)
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { color: root.panelBg; radius: 8; border.color: root.borderColor; border.width: 1 }

        ColumnLayout {
            anchors.fill: parent; anchors.margins: 20; spacing: 15
            Text { text: "💾 确认保存评估结果"; color: root.textColor; font.pixelSize: 16; font.bold: true }
            Rectangle { Layout.fillWidth: true; height: 1; color: root.borderColor }
            ColumnLayout { spacing: 5; Layout.fillWidth: true
                Text { text: "评估工程名称:"; color: root.textMuted; font.pixelSize: 12 }
                Rectangle {
                    Layout.fillWidth: true; height: 36; color: root.bgDark; radius: 4; border.color: root.borderColor; border.width: 1
                    TextInput {
                        id: saveProjectInput
                        text: "评估任务_" + root.getCurrentTime().replace(/[- :]/g, "")
                        color: root.primaryColor; font.pixelSize: 13; font.bold: true
                        anchors.fill: parent; leftPadding: 10; verticalAlignment: TextInput.AlignVCenter; selectByMouse: true
                    }
                }
            }
            Text {
                text: "保存路径由系统自动管理 (data/datasets/...)"
                color: root.textMuted; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.WordWrap
            }

            Item { Layout.fillHeight: true }
            RowLayout { Layout.fillWidth: true; spacing: 15
                Item { Layout.fillWidth: true }
                Button {
                    text: "取消"; Layout.preferredWidth: 80; Layout.preferredHeight: 34
                    background: Rectangle { color: "transparent"; border.color: root.borderColor; border.width: 1; radius: 4 }
                    contentItem: Text { text: parent.text; color: root.textMuted; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: saveProjectPopup.close()
                }
                Button {
                    text: "确认保存"; Layout.preferredWidth: 100; Layout.preferredHeight: 34
                    background: Rectangle { color: root.primaryColor; radius: 4 }
                    contentItem: Text { text: parent.text; color: "black"; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: {
                        var dsSet = {}; var algoSet = {}; var detailsArr = []; var scenarioName = ""
                        var headers = root.evalMetricHeaders || []
                        var sourceModel = activeEvalSourceModel.count > 0 ? activeEvalSourceModel : taskQueueModel
                        for (var i = 0; i < sourceModel.count; i++) {
                            var t = sourceModel.get(i)
                            if (!t.dataset && !t.algo) continue
                            dsSet[t.dataset] = true; algoSet[t.algo] = true
                            if (!scenarioName) scenarioName = t.scenario || ""
                            var detail = {dataset: t.dataset, algo: t.algo}
                            if (t.checkpointName) detail.checkpoint = t.checkpointName
                            var evalTaskId = t.evalTaskId || 0
                            for (var hj = 0; hj < evalResultModel.count; hj++) {
                                var r = evalResultModel.get(hj)
                                if (r.taskId === evalTaskId) {
                                    try {
                                        var vals = JSON.parse(r.metricValuesJson || "[]")
                                        for (var vi = 0; vi < headers.length && vi < vals.length; vi++) {
                                            detail[headers[vi]] = vals[vi]
                                        }
                                    } catch(e) {}
                                    break
                                }
                            }
                            detailsArr.push(detail)
                        }
                        var allDone = evalResultModel.count > 0
                        evalHistoryModel.insert(0, {
                            historyType: "evaluation",
                            projectName: saveProjectInput.text,
                            scenario: scenarioName,
                            datasets: Object.keys(dsSet).join(", ") || "无",
                            algos: Object.keys(algoSet).join(", ") || "无",
                            trainStatus: allDone ? "已完成" : "包含未完成",
                            evalReport: allDone ? ("共 " + evalResultModel.count + " 条评估结果") : "暂无报告",
                            time: root.getCurrentTime(),
                            detailsJson: JSON.stringify(detailsArr),
                            taskIdsJson: JSON.stringify([])
                        })
                        root.saveToAppState()
                        saveProjectPopup.close()
                        root.showToast("✅ 评估工程已归档")
                        taskQueueModel.clear(); evalResultModel.clear(); activeEvalSourceModel.clear()
                        root.taskCounter = 1; root.viewMode = "history"
                        root.saveToAppState()
                    }
                }
            }
        }
    }

    // ================= 修改/删除弹窗 =================
    Popup {
        id: editProjectPopup
        width: 360; height: 180; modal: true; focus: true
        x: Math.round((root.width - width) / 2); y: Math.round((root.height - height) / 2)
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { color: root.panelBg; radius: 8; border.color: root.borderColor; border.width: 1 }
        ColumnLayout { anchors.fill: parent; anchors.margins: 20; spacing: 15
            Text { text: "✏️ 修改工程名称"; color: root.textColor; font.pixelSize: 16; font.bold: true }
            Rectangle { Layout.fillWidth: true; height: 36; color: root.bgDark; radius: 4; border.color: root.borderColor; border.width: 1
                TextInput { id: editProjectNameInput; color: root.primaryColor; font.pixelSize: 13; font.bold: true
                    anchors.fill: parent; leftPadding: 10; verticalAlignment: TextInput.AlignVCenter; selectByMouse: true }
            }
            Item { Layout.fillHeight: true }
            RowLayout { Layout.fillWidth: true; spacing: 15; Item { Layout.fillWidth: true }
                Button { text: "取消"; Layout.preferredWidth: 80; Layout.preferredHeight: 32
                    background: Rectangle { color: "transparent"; border.color: root.borderColor; border.width: 1; radius: 4 }
                    contentItem: Text { text: parent.text; color: root.textMuted; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: editProjectPopup.close() }
                Button { text: "保存"; Layout.preferredWidth: 80; Layout.preferredHeight: 32
                    background: Rectangle { color: root.primaryColor; radius: 4 }
                    contentItem: Text { text: parent.text; color: "black"; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: {
                        if (root.pendingEditIndex !== -1 && editProjectNameInput.text.trim() !== "") {
                            evalHistoryModel.setProperty(root.pendingEditIndex, "projectName", editProjectNameInput.text)
                            root.showToast("✅ 工程名称已更新")
                        }
                        editProjectPopup.close()
                    }
                }
            }
        }
    }

    Popup {
        id: deleteConfirmPopup
        width: 320; height: 190; modal: true; focus: true
        x: Math.round((root.width - width) / 2); y: Math.round((root.height - height) / 2)
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { color: root.panelBg; radius: 8; border.color: root.dangerColor; border.width: 1 }
        ColumnLayout { anchors.fill: parent; anchors.margins: 20; spacing: 15
            RowLayout { spacing: 10
                Text { text: "⚠️"; font.pixelSize: 20 }
                Text { text: "确认删除此评估工程吗？"; color: root.textColor; font.pixelSize: 15; font.bold: true }
            }
            Text { text: "删除后历史记录将无法恢复。"; color: root.textMuted; font.pixelSize: 12; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            Item { Layout.fillHeight: true }
            RowLayout { Layout.fillWidth: true; spacing: 15; Item { Layout.fillWidth: true }
                Button { text: "取消"; Layout.preferredWidth: 80; Layout.preferredHeight: 30
                    background: Rectangle { color: "transparent"; border.color: root.borderColor; border.width: 1; radius: 4 }
                    contentItem: Text { text: parent.text; color: root.textMuted; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: deleteConfirmPopup.close() }
                Button { text: "确认删除"; Layout.preferredWidth: 80; Layout.preferredHeight: 30
                    background: Rectangle { color: root.dangerColor; radius: 4 }
                    contentItem: Text { text: parent.text; color: "black"; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: {
                        if (root.pendingDeleteIndex !== -1 && root.deleteHistoryEntry(root.pendingDeleteIndex)) {
                            root.showToast("🗑️ 记录已删除")
                        }
                        root.pendingDeleteIndex = -1
                        deleteConfirmPopup.close()
                    }
                }
            }
        }
    }

    // ========================================================================
    // 视图 A: 评估历史列表
    // ========================================================================
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 20; spacing: 15
        visible: root.viewMode === "history"

        RowLayout { Layout.fillWidth: true; spacing: 15
            Label { text: "模型训练与评估历史"; font.pixelSize: 18; font.bold: true; color: root.textColor }
            Item { Layout.fillWidth: true }
            Button {
                text: "+ 添加训练或评估任务"; font.bold: true; font.pixelSize: 14
                background: Rectangle { color: parent.pressed ? "#0277BD" : parent.hovered ? "#0288D1" : "#039BE5"; radius: 4 }
                contentItem: Text { text: parent.text; color: "black"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                onClicked: {
                    // Preserve running tasks when re-entering the evaluate view
                    var hasRunning = false
                    for (var i = 0; i < taskQueueModel.count; i++) {
                        if (taskQueueModel.get(i).trainStatus === 1) hasRunning = true
                    }
                    if (!hasRunning) {
                        taskQueueModel.clear()
                        evalResultModel.clear()
                        root.taskCounter = 1
                    }
                    backendService.getScenarios(); backendService.getDatasets(1, 100, ""); backendService.getAlgorithms("", "")
                    root.viewMode = "evaluating"
                }
            }
        }

        Rectangle { Layout.fillWidth: true; Layout.fillHeight: true; color: "transparent"; clip: true
            ScrollView {
                id: historyScroll
                anchors.fill: parent
                clip: true
                ScrollBar.vertical.policy: ScrollBar.AlwaysOn

                Column {
                    id: historySections
                    width: historyScroll.availableWidth
                    spacing: 12

                    Rectangle {
                        width: parent.width
                        height: 44
                        radius: 8
                        color: Qt.rgba(3/255, 155/255, 229/255, 0.08)
                        border.color: root.borderColor
                        border.width: 1

                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 10

                            Label { text: root.trainingHistoryExpanded ? "▼" : "▶"; color: root.primaryColor; font.pixelSize: 14; font.bold: true }
                            Label { text: "训练任务"; color: root.textColor; font.pixelSize: 15; font.bold: true }
                            Rectangle { width: 24; height: 20; radius: 10; color: Qt.rgba(3/255, 155/255, 229/255, 0.18)
                                Text { anchors.centerIn: parent; text: root.historyIndexesByType("training").length; color: root.primaryColor; font.pixelSize: 11; font.bold: true }
                            }
                            Item { Layout.fillWidth: true }
                        }

                        MouseArea {
                            anchors.fill: parent
                            onClicked: root.trainingHistoryExpanded = !root.trainingHistoryExpanded
                        }
                    }

                    Column {
                        width: parent.width
                        spacing: 12
                        visible: root.trainingHistoryExpanded

                        Repeater {
                            model: root.historyIndexesByType("training")

                            delegate: Rectangle {
                                required property int modelData
                                property int historyIndex: modelData
                                property var historyItem: evalHistoryModel.get(historyIndex)
                                width: historySections.width
                                height: 130
                                radius: 8
                                color: Theme.panel
                                border.color: rowMa.containsMouse ? Theme.primary : root.borderColor
                                border.width: 1

                                MouseArea { id: rowMa; anchors.fill: parent; hoverEnabled: true }

                                RowLayout { anchors.fill: parent; anchors.margins: 15; spacing: 20
                                    ColumnLayout { Layout.fillWidth: true; spacing: 6
                                        RowLayout { Layout.fillWidth: true; spacing: 8
                                            Label { text: "🚀 " + (historyItem.projectName || ""); color: root.primaryColor; font.pixelSize: 16; font.bold: true; elide: Text.ElideRight; Layout.maximumWidth: 400 }
                                            Item { Layout.fillWidth: true }
                                            Label { text: "🕒 " + (historyItem.time || ""); color: root.textMuted; font.pixelSize: 12 }
                                        }
                                        RowLayout { Layout.fillWidth: true; spacing: 10
                                            Label { text: "应用场景: "; color: root.textMuted; font.pixelSize: 13 }
                                            Label { text: historyItem.scenario || ""; color: root.textColor; font.pixelSize: 13; Layout.maximumWidth: 200; elide: Text.ElideRight }
                                            Rectangle { width: 1; height: 12; color: root.borderColor }
                                            Label { text: "挂载数据: "; color: root.textMuted; font.pixelSize: 13 }
                                            Label { text: historyItem.datasets || ""; color: root.textColor; font.pixelSize: 13; Layout.fillWidth: true; elide: Text.ElideRight }
                                        }
                                        RowLayout { Layout.fillWidth: true
                                            Label { text: "算法模型: "; color: root.textMuted; font.pixelSize: 13 }
                                            Label { text: historyItem.algos || ""; color: "#4DD0E1"; font.pixelSize: 13; Layout.fillWidth: true; elide: Text.ElideRight }
                                        }
                                        RowLayout { Layout.fillWidth: true; spacing: 10
                                            Label { text: "训练状态: "; color: root.textMuted; font.pixelSize: 12 }
                                            Label { text: historyItem.trainStatus || ""; color: historyItem.trainStatus === "已完成" ? root.successColor : root.warningColor; font.pixelSize: 12; font.bold: true }
                                            Rectangle { width: 1; height: 12; color: root.borderColor }
                                            Label { text: "评估报告: "; color: root.textMuted; font.pixelSize: 12 }
                                            Label { text: historyItem.evalReport || ""; color: root.primaryColor; font.pixelSize: 12; font.family: "Courier"; font.bold: true; Layout.fillWidth: true }
                                        }
                                    }
                                    ColumnLayout { Layout.alignment: Qt.AlignVCenter | Qt.AlignRight; spacing: 10
                                        Button {
                                            text: "查看"; Layout.preferredWidth: 90; Layout.preferredHeight: 30
                                            background: Rectangle { color: parent.hovered ? Theme.hover : Theme.control; radius: 4; border.color: Theme.border }
                                            contentItem: Text { text: parent.text; color: "#D1D5DB"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                            onClicked: {
                                                root.currentHistoryItem = { historyType: historyItem.historyType || "training", projectName: historyItem.projectName, scenario: historyItem.scenario, datasets: historyItem.datasets, algos: historyItem.algos, trainStatus: historyItem.trainStatus, evalReport: historyItem.evalReport }
                                                currentDetailModel.clear()
                                                var taskIds = []
                                                try { taskIds = JSON.parse(historyItem.taskIdsJson || "[]") } catch(e) { taskIds = [] }
                                                if (taskIds.length > 0) {
                                                    var rebuilt = root.buildTrainingDetailFromTask(taskIds[0], historyItem)
                                                    rebuilt.detailsJson = JSON.stringify(rebuilt)
                                                    currentDetailModel.append(rebuilt)
                                                } else if (historyItem.detailsJson && historyItem.detailsJson !== "") {
                                                    var arr = JSON.parse(historyItem.detailsJson)
                                                    for (var i = 0; i < arr.length; i++) {
                                                        var item = arr[i]
                                                        item.detailsJson = JSON.stringify(item)
                                                        currentDetailModel.append(item)
                                                    }
                                                }
                                                root.viewMode = "detail"
                                            }
                                        }
                                        Button {
                                            text: "修改"; Layout.preferredWidth: 90; Layout.preferredHeight: 30
                                            background: Rectangle { color: parent.hovered ? Theme.hover : Theme.control; radius: 4; border.color: Theme.border }
                                            contentItem: Text { text: parent.text; color: "#D1D5DB"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                            onClicked: { root.pendingEditIndex = historyIndex; editProjectNameInput.text = historyItem.projectName || ""; editProjectPopup.open() }
                                        }
                                        Button {
                                            text: "删除"; Layout.preferredWidth: 90; Layout.preferredHeight: 30
                                            background: Rectangle { color: parent.hovered ? "#BE123C" : "transparent"; border.color: root.dangerColor; border.width: 1; radius: 4 }
                                            contentItem: Text { text: parent.text; color: parent.hovered ? "white" : root.dangerColor; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                            onClicked: { root.pendingDeleteIndex = historyIndex; deleteConfirmPopup.open() }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    Rectangle {
                        width: parent.width
                        height: 44
                        radius: 8
                        color: Qt.rgba(77/255, 208/255, 225/255, 0.08)
                        border.color: root.borderColor
                        border.width: 1

                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 10

                            Label { text: root.evaluationHistoryExpanded ? "▼" : "▶"; color: "#4DD0E1"; font.pixelSize: 14; font.bold: true }
                            Label { text: "评估任务"; color: root.textColor; font.pixelSize: 15; font.bold: true }
                            Rectangle { width: 24; height: 20; radius: 10; color: Qt.rgba(77/255, 208/255, 225/255, 0.18)
                                Text { anchors.centerIn: parent; text: root.historyIndexesByType("evaluation").length; color: "#4DD0E1"; font.pixelSize: 11; font.bold: true }
                            }
                            Item { Layout.fillWidth: true }
                        }

                        MouseArea {
                            anchors.fill: parent
                            onClicked: root.evaluationHistoryExpanded = !root.evaluationHistoryExpanded
                        }
                    }

                    Column {
                        width: parent.width
                        spacing: 12
                        visible: root.evaluationHistoryExpanded

                        Repeater {
                            model: root.historyIndexesByType("evaluation")

                            delegate: Rectangle {
                                required property int modelData
                                property int historyIndex: modelData
                                property var historyItem: evalHistoryModel.get(historyIndex)
                                width: historySections.width
                                height: 130
                                radius: 8
                                color: Theme.panel
                                border.color: rowMaEval.containsMouse ? Theme.primary : root.borderColor
                                border.width: 1

                                MouseArea { id: rowMaEval; anchors.fill: parent; hoverEnabled: true }

                                RowLayout { anchors.fill: parent; anchors.margins: 15; spacing: 20
                                    ColumnLayout { Layout.fillWidth: true; spacing: 6
                                        RowLayout { Layout.fillWidth: true; spacing: 8
                                            Label { text: "📊 " + (historyItem.projectName || ""); color: "#4DD0E1"; font.pixelSize: 16; font.bold: true; elide: Text.ElideRight; Layout.maximumWidth: 400 }
                                            Item { Layout.fillWidth: true }
                                            Label { text: "🕒 " + (historyItem.time || ""); color: root.textMuted; font.pixelSize: 12 }
                                        }
                                        RowLayout { Layout.fillWidth: true; spacing: 10
                                            Label { text: "应用场景: "; color: root.textMuted; font.pixelSize: 13 }
                                            Label { text: historyItem.scenario || ""; color: root.textColor; font.pixelSize: 13; Layout.maximumWidth: 200; elide: Text.ElideRight }
                                            Rectangle { width: 1; height: 12; color: root.borderColor }
                                            Label { text: "挂载数据: "; color: root.textMuted; font.pixelSize: 13 }
                                            Label { text: historyItem.datasets || ""; color: root.textColor; font.pixelSize: 13; Layout.fillWidth: true; elide: Text.ElideRight }
                                        }
                                        RowLayout { Layout.fillWidth: true
                                            Label { text: "算法模型: "; color: root.textMuted; font.pixelSize: 13 }
                                            Label { text: historyItem.algos || ""; color: "#4DD0E1"; font.pixelSize: 13; Layout.fillWidth: true; elide: Text.ElideRight }
                                        }
                                        RowLayout { Layout.fillWidth: true; spacing: 10
                                            Label { text: "训练状态: "; color: root.textMuted; font.pixelSize: 12 }
                                            Label { text: historyItem.trainStatus || ""; color: historyItem.trainStatus === "已完成" ? root.successColor : root.warningColor; font.pixelSize: 12; font.bold: true }
                                            Rectangle { width: 1; height: 12; color: root.borderColor }
                                            Label { text: "评估报告: "; color: root.textMuted; font.pixelSize: 12 }
                                            Label { text: historyItem.evalReport || ""; color: root.primaryColor; font.pixelSize: 12; font.family: "Courier"; font.bold: true; Layout.fillWidth: true }
                                        }
                                    }
                                    ColumnLayout { Layout.alignment: Qt.AlignVCenter | Qt.AlignRight; spacing: 10
                                        Button {
                                            text: "查看"; Layout.preferredWidth: 90; Layout.preferredHeight: 30
                                            background: Rectangle { color: parent.hovered ? Theme.hover : Theme.control; radius: 4; border.color: Theme.border }
                                            contentItem: Text { text: parent.text; color: "#D1D5DB"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                            onClicked: {
                                                root.currentHistoryItem = { historyType: historyItem.historyType || "evaluation", projectName: historyItem.projectName, scenario: historyItem.scenario, datasets: historyItem.datasets, algos: historyItem.algos, trainStatus: historyItem.trainStatus, evalReport: historyItem.evalReport }
                                                currentDetailModel.clear()
                                                if (historyItem.detailsJson && historyItem.detailsJson !== "") {
                                                    var arr = JSON.parse(historyItem.detailsJson)
                                                    for (var i = 0; i < arr.length; i++) {
                                                        var item = arr[i]
                                                        item.detailsJson = JSON.stringify(item)
                                                        currentDetailModel.append(item)
                                                    }
                                                }
                                                root.viewMode = "detail"
                                            }
                                        }
                                        Button {
                                            text: "修改"; Layout.preferredWidth: 90; Layout.preferredHeight: 30
                                            background: Rectangle { color: parent.hovered ? Theme.hover : Theme.control; radius: 4; border.color: Theme.border }
                                            contentItem: Text { text: parent.text; color: "#D1D5DB"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                            onClicked: { root.pendingEditIndex = historyIndex; editProjectNameInput.text = historyItem.projectName || ""; editProjectPopup.open() }
                                        }
                                        Button {
                                            text: "删除"; Layout.preferredWidth: 90; Layout.preferredHeight: 30
                                            background: Rectangle { color: parent.hovered ? "#BE123C" : "transparent"; border.color: root.dangerColor; border.width: 1; radius: 4 }
                                            contentItem: Text { text: parent.text; color: parent.hovered ? "white" : root.dangerColor; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                            onClicked: { root.pendingDeleteIndex = historyIndex; deleteConfirmPopup.open() }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    Text {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        text: "暂无历史记录"
                        color: Theme.muted
                        font.pixelSize: 16
                        visible: evalHistoryModel.count === 0
                    }
                }
            }
        }
    }

    // ========================================================================
    // 视图 B: 评估工程详情
    // ========================================================================
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 20; spacing: 15
        visible: root.viewMode === "detail"

        RowLayout { Layout.fillWidth: true; spacing: 15
            Button {
                text: "⬅ 返回历史"; font.bold: true; font.pixelSize: 14
                background: Rectangle { color: "transparent"; border.color: Theme.border; border.width: 1; radius: 4 }
                contentItem: Text { text: parent.text; color: "#4DD0E1"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                onClicked: root.viewMode = "history"
            }
            Label { text: root.currentHistoryItem ? "📂 工程详情: " + root.currentHistoryItem.projectName : ""; font.pixelSize: 16; font.bold: true; color: root.primaryColor; Layout.leftMargin: 10 }
            Item { Layout.fillWidth: true }
        }

        Rectangle { Layout.fillWidth: true; Layout.fillHeight: true; color: Theme.row; border.color: Theme.border; border.width: 1; radius: 8; clip: true
            ColumnLayout { anchors.fill: parent; spacing: 0
                Rectangle { Layout.fillWidth: true; height: 45; color: Theme.rowAlt
                    RowLayout { anchors.fill: parent; anchors.leftMargin: 20; anchors.rightMargin: 20; spacing: 10
                        Label { text: "使用数据集"; font.bold: true; color: "#A0AEC0"; Layout.preferredWidth: 160 }
                        Label { text: "匹配算法模型"; font.bold: true; color: "#A0AEC0"; Layout.preferredWidth: 140 }
                        Label { text: root.currentHistoryItem && root.currentHistoryItem.historyType === "training" ? "训练配置" : "评估指标"; font.bold: true; color: "#A0AEC0"; Layout.fillWidth: true }
                    }
                }
                ListView { id: detailListView; Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 1; model: currentDetailModel
                    delegate: Rectangle { width: detailListView.width; height: 45; color: index % 2 === 0 ? Theme.panel : "transparent"
                        MouseArea { anchors.fill: parent; hoverEnabled: true; onEntered: parent.color = Theme.hover; onExited: parent.color = index % 2 === 0 ? Theme.panel : "transparent" }
                        RowLayout { anchors.fill: parent; anchors.leftMargin: 20; anchors.rightMargin: 20; spacing: 10
                            Label { text: "📁 " + model.dataset; color: Theme.text; font.pixelSize: 13; Layout.preferredWidth: 160; elide: Text.ElideRight }
                            Label { text: model.algo; color: root.primaryColor; font.pixelSize: 13; font.bold: true; Layout.preferredWidth: 140; elide: Text.ElideRight }
                            Flickable {
                                id: metricFlick
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                clip: true
                                contentWidth: metricText.implicitWidth
                                contentHeight: height
                                flickableDirection: Flickable.HorizontalFlick
                                boundsBehavior: Flickable.StopAtBounds
                                interactive: contentWidth > width

                                ScrollBar.horizontal: ScrollBar {
                                    policy: metricFlick.contentWidth > metricFlick.width ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff
                                }

                                Text {
                                    id: metricText
                                    property var _detailObj: { try { return JSON.parse(model.detailsJson || "{}") } catch(e) { return {} } }
                                    property var _metricText: {
                                        var str = "";
                                        var keys = Object.keys(_detailObj);
                                        var hiddenTrainingKeys = ["taskId", "status", "outputDir", "artifactPath", "progressMessage", "summary", "checkpoint"]
                                        for (var mi = 0; mi < keys.length; mi++) {
                                            if (keys[mi] === "dataset" || keys[mi] === "algo") continue;
                                            if (root.currentHistoryItem && root.currentHistoryItem.historyType === "training" && hiddenTrainingKeys.indexOf(keys[mi]) !== -1) continue;
                                            if (str !== "") str += " | ";
                                            str += keys[mi] + ": " + _detailObj[keys[mi]];
                                        }
                                        return str || "暂无指标";
                                    }
                                    x: 0
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: _metricText
                                    color: root.textColor
                                    font.pixelSize: 12
                                    font.family: "Courier"
                                    font.bold: true
                                    wrapMode: Text.NoWrap
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // ========================================================================
    // 视图 C: 评估任务操作台
    // ========================================================================
    Button {
        text: "返回历史"
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.topMargin: 20
        anchors.rightMargin: 20
        width: 92
        height: 30
        visible: root.viewMode === "evaluating"
        background: Rectangle { color: "transparent"; border.color: Theme.border; border.width: 1; radius: 4 }
        contentItem: Text { text: parent.text; color: "#4DD0E1"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
        onClicked: root.viewMode = "history"
    }

    // 右下角浮动按钮 -- 训练模式
    RowLayout {
        id: floatingButtons
        anchors.bottom: parent.bottom; anchors.right: parent.right
        anchors.bottomMargin: 12; anchors.rightMargin: 20; spacing: 10
        visible: root.viewMode === "evaluating" && root.workMode === "train"
        z: 10
        property bool canSave: {
            for (var i = 0; i < taskQueueModel.count; i++) {
                var t = taskQueueModel.get(i)
                if (t.trainStatus === 2 && t.isSelected) return true
            }
            return false
        }
        Rectangle { height: 34; width: 110; radius: 6
            color: floatingButtons.canSave ? root.successColor : root.bgDark
            border.color: floatingButtons.canSave ? "transparent" : root.borderColor; border.width: floatingButtons.canSave ? 0 : 1
            Text { text: "💾 保存权重"; color: floatingButtons.canSave ? "white" : root.textMuted; font.pixelSize: 12; font.bold: true; anchors.centerIn: parent }
            MouseArea { anchors.fill: parent; cursorShape: floatingButtons.canSave ? Qt.PointingHandCursor : Qt.ForbiddenCursor; enabled: floatingButtons.canSave
                onClicked: {
                    var count = 0; var delCount = 0
                    for (var i = taskQueueModel.count - 1; i >= 0; i--) {
                        var t = taskQueueModel.get(i)
                        if (t.trainStatus === 2 && t.isSelected) { taskQueueModel.setProperty(i, "saved", true); count++ }
                        else if (t.trainStatus === 2) {
                            if (t.taskId > 0) { backendService.deleteTask(t.taskId); delCount++ }
                            taskQueueModel.remove(i)
                        }
                    }
                    root.checkStates(); root.saveToAppState()
                    backendService.getTrainingTasks(0, "")
                    root.viewMode = "history"
                    root.showToast(count > 0 ? "✅ 已保存 " + count + " 个，删除 " + delCount + " 个" : "⚠️ 未勾选已完成的任务")
                }
            }
        }
        Rectangle { id: clrBtn; height: 34; width: 90; radius: 6
            color: taskQueueModel.count > 0 ? (clrMa.containsMouse ? Qt.rgba(245,63,63,0.1) : "transparent") : root.bgDark
            border.color: taskQueueModel.count > 0 ? root.borderColor : root.textMuted; border.width: 1
            Text { text: "清空队列"; color: taskQueueModel.count > 0 ? root.textMuted : Qt.darker(root.textMuted, 2); font.pixelSize: 12; anchors.centerIn: parent }
            MouseArea { id: clrMa; anchors.fill: parent; cursorShape: taskQueueModel.count > 0 ? Qt.PointingHandCursor : Qt.ForbiddenCursor; enabled: taskQueueModel.count > 0; hoverEnabled: true
                onClicked: {
                    for (var i = taskQueueModel.count - 1; i >= 0; i--) {
                        var tid = taskQueueModel.get(i).taskId
                        if (tid > 0) backendService.deleteTask(tid)
                    }
                    taskQueueModel.clear(); root.checkStates(); root.saveToAppState()
                    backendService.getTrainingTasks(0, "")
                    root.showToast("🗑️ 队列及权重已清空")
                }
            }
        }
    }

    Flickable {
        id: evaluationWorkbenchFlickable
        anchors.fill: parent; anchors.margins: 20
        anchors.topMargin: 66
        visible: root.viewMode === "evaluating"
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        contentHeight: Math.max(root.workbenchContentHeight(), height + 1)

        ScrollBar.vertical: ScrollBar {
            policy: ScrollBar.AsNeeded
        }

        ColumnLayout {
        id: evaluationWorkbenchContent
        width: parent.width - 12
        spacing: (!root.trainingWorkbenchExpanded && !root.evaluationWorkbenchExpanded) ? 8 : 15

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 46
            radius: 8
            color: root.panelBg
            border.color: root.borderColor
            border.width: 1

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 16
                anchors.rightMargin: 16
                spacing: 10

                Text { text: "模型训练与评估"; color: root.textColor; font.pixelSize: 16; font.bold: true }
                Item { Layout.fillWidth: true }
                // 模式切换按钮
                Rectangle {
                    width: 64; height: 30; radius: 6
                    color: root.workMode === "train" ? root.primaryColor : "transparent"
                    border.color: root.workMode === "train" ? "transparent" : root.borderColor; border.width: 1
                    Text { text: "训练"; color: root.workMode === "train" ? "white" : root.textColor; font.pixelSize: 12; font.bold: root.workMode === "train"; anchors.centerIn: parent }
                    MouseArea {
                        anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                        onClicked: { root.workMode = "train"; root.trainingWorkbenchExpanded = true; root.evaluationWorkbenchExpanded = false }
                    }
                }
                Rectangle {
                    width: 64; height: 30; radius: 6
                    color: root.workMode === "eval" ? root.primaryColor : "transparent"
                    border.color: root.workMode === "eval" ? "transparent" : root.borderColor; border.width: 1
                    Text { text: "评估"; color: root.workMode === "eval" ? "white" : root.textColor; font.pixelSize: 12; font.bold: root.workMode === "eval"; anchors.centerIn: parent }
                    MouseArea {
                        anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                        onClicked: { root.workMode = "eval"; root.trainingWorkbenchExpanded = false; root.evaluationWorkbenchExpanded = true }
                    }
                }
            }
        }

        // 顶部控制栏
        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 80; color: root.panelBg; radius: 8; border.color: root.borderColor; border.width: 1
            visible: root.workMode === "train" && root.trainingWorkbenchExpanded
            RowLayout { anchors.fill: parent; anchors.margins: 15; spacing: 20
                ColumnLayout { spacing: 5
                    Text { text: "1. 任务场景"; color: root.textMuted; font.pixelSize: 12; font.bold: true }
                    StableComboBox { id: scenarioCombo; model: scenarioModel; textRole: "name"; Layout.preferredWidth: 160
                        background: Rectangle { color: root.bgDark; border.color: root.borderColor; radius: 4 }
                        contentItem: Text { text: parent.currentText; color: root.textColor; verticalAlignment: Text.AlignVCenter; padding: 10 }
                        onCurrentIndexChanged: root.filterAlgorithmsByScenario()
                    }
                }
                Text { text: "➡"; color: root.borderColor; font.pixelSize: 16 }
                ColumnLayout { spacing: 5
                    Text { text: "2. 挂载数据集"; color: root.textMuted; font.pixelSize: 12; font.bold: true }
                    StableComboBox { id: datasetCombo; model: datasetModel; textRole: "name"; Layout.preferredWidth: 160
                        background: Rectangle { color: root.bgDark; border.color: root.borderColor; radius: 4 }
                        contentItem: Text { text: parent.currentText; color: root.textColor; verticalAlignment: Text.AlignVCenter; padding: 10; elide: Text.ElideRight }
                    }
                }
                Text { text: "➡"; color: root.borderColor; font.pixelSize: 16 }
                ColumnLayout { spacing: 5
                    Text { text: "3. 骨干算法网络"; color: root.textMuted; font.pixelSize: 12; font.bold: true }
                    StableComboBox { id: algoCombo; model: algoModel; textRole: "name"; Layout.preferredWidth: 160
                        background: Rectangle { color: root.bgDark; border.color: root.borderColor; radius: 4 }
                        contentItem: Text { text: parent.currentText; color: root.textColor; verticalAlignment: Text.AlignVCenter; padding: 10; elide: Text.ElideRight }
                    }
                }
                Item { Layout.fillWidth: true }
                Rectangle { width: 140; height: 38; radius: 4
                    color: (scenarioCombo.currentText && datasetCombo.currentIndex >= 0 && datasetCombo.currentText !== "无可用数据集 (请先导入)" && algoCombo.currentText) ? root.primaryColor : root.bgDark
                    border.color: (scenarioCombo.currentText && datasetCombo.currentIndex >= 0 && datasetCombo.currentText !== "无可用数据集 (请先导入)" && algoCombo.currentText) ? "transparent" : root.borderColor
                    border.width: 1
                    Text { text: "+ 追加至队列"; color: (scenarioCombo.currentText && datasetCombo.currentIndex >= 0 && datasetCombo.currentText !== "无可用数据集 (请先导入)" && algoCombo.currentText) ? "white" : root.textMuted; font.bold: true; font.pixelSize: 13; anchors.centerIn: parent }
                    MouseArea { anchors.fill: parent
                        cursorShape: (scenarioCombo.currentText && datasetCombo.currentIndex >= 0 && datasetCombo.currentText !== "无可用数据集 (请先导入)" && algoCombo.currentText) ? Qt.PointingHandCursor : Qt.ForbiddenCursor
                        enabled: scenarioCombo.currentText && datasetCombo.currentIndex >= 0 && datasetCombo.currentText !== "无可用数据集 (请先导入)" && algoCombo.currentText
                        onClicked: {
                            var algoItem = algoModel.get(algoCombo.currentIndex)
                            root.pendingAlgoKey = algoItem ? (algoItem.key || "") : ""
                            algoParamsPopup.open()
                        }
                    }
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: root.trainingWorkbenchExpanded || root.evaluationWorkbenchExpanded
            Layout.minimumHeight: root.workbenchMainHeight()
            Layout.preferredHeight: root.workbenchMainHeight()
            spacing: 4
            clip: false

            // 中部：训练任务队列
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: false
                Layout.minimumHeight: root.trainingWorkbenchExpanded ? 309 : 0
                Layout.preferredHeight: root.trainingWorkbenchExpanded ? 309 : 0
                color: "transparent"; clip: true
                visible: root.workMode === "train" && root.trainingWorkbenchExpanded
                ColumnLayout { anchors.fill: parent; spacing: 12
                    // 队列头部操作栏
                    Rectangle { Layout.fillWidth: true; height: 45; color: root.panelBg; radius: 8; border.color: root.borderColor; border.width: 1
                        RowLayout { anchors.fill: parent; anchors.leftMargin: 15; anchors.rightMargin: 15; spacing: 15
                            Rectangle { width: 18; height: 18; radius: 4; color: root.isAllSelected ? root.primaryColor : root.bgDark; border.color: root.isAllSelected ? root.primaryColor : root.textMuted
                                Text { text: "✓"; color: "white"; font.pixelSize: 12; font.bold: true; anchors.centerIn: parent; visible: root.isAllSelected }
                                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        if (taskQueueModel.count === 0) return
                                        var ns = !root.isAllSelected
                                        for (var i = 0; i < taskQueueModel.count; i++) taskQueueModel.setProperty(i, "isSelected", ns)
                                        root.checkStates()
                                    }
                                }
                            }
                            Text { text: "全选"; color: root.textMuted; font.pixelSize: 13; font.bold: true }
                            Rectangle { width: 1; height: 16; color: root.borderColor }
                            Text { text: "训练任务队列"; color: root.textColor; font.pixelSize: 15; font.bold: true }
                            Item { Layout.fillWidth: true }
                            // canStartTraining / startSelectedTraining 定义在文件底部「状态判断函数」区域
                            Rectangle { width: 130; height: 32; radius: 4
                                visible: !root.isTraining
                                color: root.canStartTraining() ? root.primaryColor : root.bgDark
                                border.color: root.canStartTraining() ? "transparent" : root.borderColor
                                Text { text: "▶ 启动选中训练"; color: root.canStartTraining() ? "white" : root.textMuted; font.bold: true; font.pixelSize: 12; anchors.centerIn: parent }
                                MouseArea { anchors.fill: parent
                                    cursorShape: root.canStartTraining() ? Qt.PointingHandCursor : Qt.ForbiddenCursor
                                    enabled: root.canStartTraining()
                                    onClicked: root.startSelectedTraining()
                                }
                            }
                            Rectangle { width: 130; height: 32; radius: 4
                                visible: root.isTraining
                                color: "#E11D48"
                                border.color: "transparent"
                                Text { text: "⏹ 取消训练"; color: "black"; font.bold: true; font.pixelSize: 12; anchors.centerIn: parent }
                                MouseArea { anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        for (var ci = 0; ci < taskQueueModel.count; ci++) {
                                            var ct = taskQueueModel.get(ci)
                                            if (ct.trainStatus === 1 && ct.taskId > 0) {
                                                backendService.cancelTask(ct.taskId)
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    Rectangle { Layout.fillWidth: true; height: 40; color: root.bgDark
                        Rectangle { width: parent.width; height: 1; color: root.borderColor; anchors.bottom: parent.bottom }
                        Rectangle { width: parent.width; height: 1; color: root.borderColor; anchors.top: parent.top }
                        RowLayout { anchors.fill: parent; anchors.leftMargin: 15; anchors.rightMargin: 15; spacing: 10
                            Item { Layout.preferredWidth: 60 }
                            Label { text: "任务ID"; color: root.textMuted; font.pixelSize: 12; font.bold: true; Layout.preferredWidth: 60 }
                            Label { text: "应用场景"; color: root.textMuted; font.pixelSize: 12; font.bold: true; Layout.preferredWidth: 160 }
                            Label { text: "使用数据集"; color: root.textMuted; font.pixelSize: 12; font.bold: true; Layout.fillWidth: true }
                            Label { text: "算法模型"; color: root.textMuted; font.pixelSize: 12; font.bold: true; Layout.preferredWidth: 160 }
                            Label { text: "训练状态"; color: root.textMuted; font.pixelSize: 12; font.bold: true; Layout.preferredWidth: 220 }
                            Label { text: "操作"; color: root.textMuted; font.pixelSize: 12; font.bold: true; Layout.preferredWidth: 80; horizontalAlignment: Text.AlignRight }
                        }
                    }

                    ListView {
                        id: taskQueueListView
                        Layout.fillWidth: true; Layout.preferredHeight: 200; clip: true; model: taskQueueModel; spacing: 0
                        boundsBehavior: Flickable.StopAtBounds
                        Text { visible: taskQueueModel.count === 0; text: "暂无训练任务，请在上方配置并追加至队列"; color: root.textMuted; font.pixelSize: 14; anchors.centerIn: parent }

                        delegate: Rectangle {
                            width: taskQueueListView.width
                            height: 50
                            color: index % 2 === 0 ? Theme.panel : "transparent"
                            property bool rowHov: rowMa.containsMouse
                            Rectangle { anchors.fill: parent; color: isSelected ? root.tableHoverBg : (rowHov ? Theme.hover : "transparent") }
                            Rectangle { width: parent.width; height: 1; color: root.borderColor; anchors.bottom: parent.bottom }
                            MouseArea { id: rowMa; anchors.fill: parent; hoverEnabled: true
                                onClicked: { taskQueueModel.setProperty(index, "isSelected", !isSelected); root.checkStates() }
                            }
                            RowLayout { anchors.fill: parent; anchors.leftMargin: 15; anchors.rightMargin: 15; spacing: 10
                                Item { Layout.preferredWidth: 60
                                    Rectangle { width: 16; height: 16; radius: 2; anchors.centerIn: parent; color: isSelected ? root.primaryColor : root.bgDark; border.color: isSelected ? root.primaryColor : root.borderColor
                                        Text { text: "✓"; color: "white"; font.pixelSize: 12; anchors.centerIn: parent; visible: isSelected }
                                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; hoverEnabled: true
                                            onClicked: { taskQueueModel.setProperty(index, "isSelected", !isSelected); root.checkStates() }
                                        }
                                    }
                                }
                                Text {
                                    text: taskId > 0 ? ("#" + taskId) : ("T" + (index + 1))
                                    color: root.primaryColor
                                    font.pixelSize: 13
                                    font.bold: true
                                    font.family: "Courier"
                                    Layout.preferredWidth: 60
                                }
                                Text { text: scenario; color: root.textColor; font.pixelSize: 13; Layout.preferredWidth: 160; elide: Text.ElideRight }
                                Text { text: dataset; color: root.textColor; font.pixelSize: 13; Layout.fillWidth: true; elide: Text.ElideRight }
                                Text { text: algo; color: "#4DD0E1"; font.pixelSize: 13; font.bold: true; Layout.preferredWidth: 160; elide: Text.ElideRight }
                                Item { Layout.preferredWidth: 220; height: 30
                                    Text { text: "待训练"; color: root.textMuted; font.pixelSize: 12; font.bold: true; anchors.verticalCenter: parent.verticalCenter; visible: trainStatus === 0 }
                                    ColumnLayout { anchors.verticalCenter: parent.verticalCenter; visible: trainStatus === 1; anchors.left: parent.left; anchors.right: parent.right
                                        RowLayout { spacing: 6
                                            Rectangle { Layout.fillWidth: true; height: 6; radius: 3; color: root.bgDark
                                                Rectangle { width: parent.width * trainProgress; height: parent.height; radius: 3; color: root.primaryColor }
                                            }
                                            Text { text: Math.floor(trainProgress * 100) + "%"; color: root.primaryColor; font.pixelSize: 11; font.bold: true; font.family: "Courier" }
                                        }
                                    }
                                    Rectangle { anchors.verticalCenter: parent.verticalCenter; height: 22; width: 64; radius: 3; color: Qt.rgba(0,180,42,0.1); border.color: root.successColor; border.width: 1; visible: trainStatus === 2
                                        Text { text: "✓ 已完成"; color: root.successColor; font.pixelSize: 11; font.bold: true; anchors.centerIn: parent }
                                    }
                                    Rectangle { anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; height: 22; width: 56; radius: 3; color: Qt.rgba(245,63,63,0.1); border.color: root.dangerColor; border.width: 1; visible: trainStatus === 3
                                        Text { text: "✗ 失败"; color: root.dangerColor; font.pixelSize: 11; font.bold: true; anchors.centerIn: parent }
                                    }
                                    Rectangle { anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; height: 22; width: 56; radius: 3; color: Qt.rgba(245,158,11,0.1); border.color: root.warningColor; border.width: 1; visible: trainStatus === 4
                                        Text { text: "⏸ 中断"; color: root.warningColor; font.pixelSize: 11; font.bold: true; anchors.centerIn: parent }
                                    }
                                }
                                Item { Layout.preferredWidth: 80; height: 30
                                    Rectangle { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; height: 26; width: 60; radius: 4; color: btnHov ? Theme.hover : root.bgDark; border.color: root.borderColor; border.width: 1; visible: trainStatus === 0 || trainStatus === 3 || trainStatus === 4
                                        property bool btnHov: delBtnMa.containsMouse
                                        Text { text: "删除"; color: root.dangerColor; font.pixelSize: 11; anchors.centerIn: parent }
                                        MouseArea { id: delBtnMa; anchors.fill: parent; cursorShape: Qt.PointingHandCursor; hoverEnabled: true
                                            onClicked: { taskQueueModel.remove(index); root.checkStates(); root.saveToAppState() }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // 底部：评估比对
            Rectangle {
                Layout.fillWidth: true
                visible: root.workMode === "eval"
                Layout.fillHeight: root.evaluationWorkbenchExpanded
                Layout.minimumHeight: root.evaluationWorkbenchExpanded ? 640 : 46
                Layout.preferredHeight: root.evaluationWorkbenchExpanded ? 640 : 46
                color: root.panelBg; radius: 8; border.color: root.borderColor; border.width: 1
                ColumnLayout { anchors.fill: parent; anchors.margins: root.evaluationWorkbenchExpanded ? 15 : 0; spacing: 10
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: root.evaluationWorkbenchExpanded ? 40 : 46
                    color: "transparent"

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: root.evaluationWorkbenchExpanded ? 0 : 16
                        anchors.rightMargin: root.evaluationWorkbenchExpanded ? 0 : 16
                        spacing: 10
                        Text { text: root.evaluationWorkbenchExpanded ? "▼" : "▶"; color: root.primaryColor; font.pixelSize: 14; font.bold: true }
                        Text { text: "模型评估比对"; color: root.textColor; font.pixelSize: 16; font.bold: true }
                        Item { Layout.fillWidth: true }
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.evaluationWorkbenchExpanded = !root.evaluationWorkbenchExpanded
                    }
                }
                Rectangle { Layout.fillWidth: true; height: 1; color: root.borderColor; visible: root.workMode === "eval" && root.evaluationWorkbenchExpanded }

                // 启动评估
                RowLayout { Layout.fillWidth: true; visible: root.workMode === "eval" && root.evaluationWorkbenchExpanded
                    Text { text: "4. 评估比对:"; color: root.textMuted; font.pixelSize: 13; font.bold: true }
                    Text { text: "加载训练checkpoint进行开放集识别评估（MAV收集 → Weibull拟合 → OpenMax）"; color: root.textMuted; font.pixelSize: 11; Layout.fillWidth: true; elide: Text.ElideRight }
                    Rectangle { width: 160; height: 36; radius: 4
                        color: root.canRunEvaluation() && !root.isEvaluating ? root.primaryColor : root.bgDark
                        border.color: root.canRunEvaluation() && !root.isEvaluating ? "transparent" : root.borderColor
                        opacity: root.canRunEvaluation() && !root.isEvaluating ? 1.0 : 0.4
                        Text { text: root.isEvaluating ? "⏳ 评估中..." : "🚀 启动评估比对"; color: root.canRunEvaluation() && !root.isEvaluating ? "white" : root.textMuted; font.bold: true; font.pixelSize: 13; anchors.centerIn: parent }
                        MouseArea { anchors.fill: parent
                            cursorShape: root.canRunEvaluation() && !root.isEvaluating ? Qt.PointingHandCursor : Qt.ForbiddenCursor
                            enabled: root.canRunEvaluation() && !root.isEvaluating
                            onClicked: root.startEvaluation()
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 291
                    color: root.bgDark
                    radius: 6
                    border.color: root.borderColor
                    border.width: 1
                    visible: root.workMode === "eval" && root.evaluationWorkbenchExpanded

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 10

                        RowLayout {
                            Layout.fillWidth: true
                            Text { text: "选择训练权重"; color: root.textColor; font.pixelSize: 14; font.bold: true }
                            Text { text: "勾选历史训练完成后的 checkpoint，再点击右上角启动评估"; color: root.textMuted; font.pixelSize: 11; Layout.fillWidth: true; elide: Text.ElideRight }
                        }

                        Rectangle { Layout.fillWidth: true; height: 1; color: root.borderColor }

                        ListView {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 226
                            clip: true
                            model: weightOptionModel
                            spacing: 6

                            Text {
                                visible: weightOptionModel.count === 0
                                text: "暂无可用训练权重，请先完成训练任务"
                                color: root.textMuted
                                font.pixelSize: 13
                                anchors.centerIn: parent
                            }

                            delegate: Rectangle {
                                width: ListView.view ? ListView.view.width : 0
                                height: 52
                                radius: 4
                                color: model.isSelected ? root.tableHoverBg : "transparent"
                                border.color: model.isSelected ? root.primaryColor : root.borderColor
                                border.width: 1

                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: weightOptionModel.setProperty(index, "isSelected", !model.isSelected)
                                }

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 12
                                    anchors.rightMargin: 12
                                    spacing: 10

                                    Rectangle {
                                        width: 16
                                        height: 16
                                        radius: 2
                                        color: isSelected ? root.primaryColor : root.panelBg
                                        border.color: isSelected ? root.primaryColor : root.borderColor
                                        Text { text: "✓"; color: "white"; font.pixelSize: 12; anchors.centerIn: parent; visible: isSelected }
                                    }

                                    ColumnLayout {
                                        Layout.preferredWidth: 320
                                        spacing: 2
                                        Text { text: "#" + taskId + "  " + (algo || "训练模型"); color: root.primaryColor; font.pixelSize: 13; font.bold: true; elide: Text.ElideRight; Layout.fillWidth: true }
                                        Text { text: (scenario || "") + " | " + (dataset || ""); color: root.textColor; font.pixelSize: 12; elide: Text.ElideRight; Layout.fillWidth: true }
                                    }

                                    Text {
                                        text: paramSummary || ""
                                        color: "#4DD0E1"
                                        font.pixelSize: 12
                                        wrapMode: Text.NoWrap
                                        elide: Text.ElideRight
                                        Layout.fillWidth: true
                                    }
                                }
                            }
                        }
                    }
                }

                // 评估比对表格
                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    color: "transparent"
                    visible: root.workMode === "eval" && root.evaluationWorkbenchExpanded

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 10

                        RowLayout {
                            Layout.fillWidth: true
                            Text { text: "评估结果"; color: root.textColor; font.pixelSize: 14; font.bold: true }
                            Text { text: evalResultModel.count > 0 ? ("共 " + evalResultModel.count + " 条结果") : "执行评估后在这里查看指标结果"; color: root.textMuted; font.pixelSize: 11; Layout.fillWidth: true; elide: Text.ElideRight }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            color: root.bgDark
                            radius: 6
                            border.color: root.borderColor
                            border.width: 1

                            Text {
                                visible: evalResultModel.count === 0
                                text: root.isEvaluating ? "⏳ 正在执行评估比对..." : "请先在上方勾选训练权重，然后点击启动评估比对"
                                color: root.isEvaluating ? root.primaryColor : root.textMuted
                                font.pixelSize: 13
                                font.family: "Courier"
                                anchors.centerIn: parent
                            }

                            ColumnLayout { anchors.fill: parent; spacing: 0; visible: evalResultModel.count > 0
                                // 表头 - 动态列 (可横向滚动)
                                Rectangle { Layout.fillWidth: true; height: 40; color: Qt.rgba(255, 255, 255, 0.02)
                                    Flickable {
                                        id: evalHeaderFlick
                                        anchors.fill: parent
                                        contentWidth: headerRow.implicitWidth + 24
                                        contentX: root.evalTableContentX
                                        clip: true; boundsBehavior: Flickable.StopAtBounds
                                        interactive: true
                                        onContentXChanged: {
                                            if (dragging || flicking) root.evalTableContentX = contentX
                                        }
                                        Row {
                                            id: headerRow; anchors.leftMargin: 12; anchors.verticalCenter: parent.verticalCenter
                                            spacing: 8
                                            Label { text: "模型 / 权重"; color: root.textMuted; font.pixelSize: 12; font.bold: true; width: 180 }
                                            Repeater {
                                                model: evalMetricHeaders
                                                Label {
                                                    text: String(modelData).length > 10 ? String(modelData).substring(0, 10) + "…" : modelData
                                                    color: root.textMuted; font.pixelSize: 11; font.bold: true
                                                    width: Math.max(75, String(modelData).length * 10)
                                                    elide: Text.ElideRight; horizontalAlignment: Text.AlignRight
                                                }
                                            }
                                        }
                                    }
                                }
                                Rectangle { Layout.fillWidth: true; height: 1; color: root.borderColor }

                                // 数据行
                                ListView {
                                    Layout.fillWidth: true; Layout.fillHeight: true; clip: true; model: evalResultModel; spacing: 0
                                    delegate: Rectangle {
                                        width: ListView.view ? ListView.view.width : 0; height: 40
                                        color: index % 2 === 0 ? Theme.panel : "transparent"
                                        Rectangle { width: parent.width; height: 1; color: root.borderColor; anchors.bottom: parent.bottom }
                                        property var _vals: JSON.parse(metricValuesJson || "[]")

                                        Flickable {
                                            anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12
                                            contentWidth: dataRow.implicitWidth
                                            contentX: root.evalTableContentX
                                            clip: true; boundsBehavior: Flickable.StopAtBounds
                                            interactive: false
                                            Row {
                                                id: dataRow; spacing: 8; anchors.verticalCenter: parent.verticalCenter
                                                Label { text: displayName || modelName; color: root.primaryColor; font.pixelSize: 13; font.bold: true; width: 180; elide: Text.ElideRight }
                                                Repeater {
                                                    model: root.evalMetricHeaders.length
                                                    Label {
                                                        text: index < _vals.length ? _vals[index] : "-"
                                                        color: root.textColor; font.pixelSize: 13; font.family: "Courier"; font.bold: true
                                                        width: Math.max(75, String(root.evalMetricHeaders[index] || "").length * 10)
                                                        horizontalAlignment: Text.AlignRight
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

                // 底部保存/清空
                RowLayout { Layout.fillWidth: true; Layout.preferredHeight: 36; Layout.topMargin: 4; spacing: 15; visible: root.workMode === "eval" && root.evaluationWorkbenchExpanded
                    Item { Layout.fillWidth: true }
                    Rectangle { width: 150; height: 36; radius: 4; color: root.bgDark; border.color: root.borderColor; border.width: 1; opacity: evalResultModel.count > 0 ? 1.0 : 0.4
                        RowLayout { anchors.centerIn: parent; spacing: 5
                            Text { text: "✗"; color: root.dangerColor; font.pixelSize: 14; font.bold: true }
                            Text { text: "清空评估面板"; color: root.dangerColor; font.pixelSize: 12; font.bold: true }
                        }
                        MouseArea { anchors.fill: parent; cursorShape: evalResultModel.count > 0 ? Qt.PointingHandCursor : Qt.ForbiddenCursor; enabled: evalResultModel.count > 0
                            onClicked: { taskQueueModel.clear(); evalResultModel.clear(); activeEvalSourceModel.clear(); root.pendingEvalTaskIds = []; root.isEvaluating = false; root.saveToAppState() }
                        }
                    }
                    Rectangle { width: 160; height: 36; radius: 4
                        color: evalResultModel.count > 0 ? root.primaryColor : root.bgDark
                        border.color: evalResultModel.count > 0 ? "transparent" : root.borderColor
                        border.width: 1; opacity: evalResultModel.count > 0 ? 1.0 : 0.4
                        RowLayout { anchors.centerIn: parent; spacing: 5
                            Text { text: "💾"; color: "white"; font.pixelSize: 14 }
                            Text { text: "保存评估工程"; color: evalResultModel.count > 0 ? "white" : root.textMuted; font.pixelSize: 13; font.bold: true }
                        }
                        MouseArea { anchors.fill: parent; cursorShape: evalResultModel.count > 0 ? Qt.PointingHandCursor : Qt.ForbiddenCursor; enabled: evalResultModel.count > 0
                            onClicked: saveProjectPopup.open()
                        }
                    }
                }
            }
            }
        }

        Item {
            Layout.fillHeight: true
            visible: !root.trainingWorkbenchExpanded && !root.evaluationWorkbenchExpanded
        }
        }
    }


    // 评估结果轮询定时器 (后台任务完成后自动拉取结果)
    Timer {
        id: evalPollTimer
        interval: 1500; repeat: true
        running: root.pendingEvalTaskIds.length > 0
        onTriggered: {
            var ids = root.pendingEvalTaskIds.slice()
            for (var ei = 0; ei < ids.length; ei++) {
                backendService.getEvaluationResults(ids[ei])
            }
        }
    }

    // ================= 状态判断函数 =================
    function canStartTraining() {
        for (var i = 0; i < taskQueueModel.count; i++) {
            var t = taskQueueModel.get(i)
            if (t.isSelected && t.trainStatus === 0 && t.datasetId > 0 && t.algoId > 0) return true
        }
        return false
    }

    function startSelectedTraining() {
        for (var i = 0; i < taskQueueModel.count; i++) {
            var t = taskQueueModel.get(i)
            if (t.isSelected && t.trainStatus === 0 && t.datasetId > 0 && t.algoId > 0) {
                var scId = root.findScenarioId(t.scenario)
                var params = t.params || {}
                var result = backendService.createTrainingTask(scId, t.datasetId, t.algoId, params)
                if (!result || result.status !== "success") {
                    root.showToast("⚠️ " + (result && result.message ? result.message : "训练任务创建失败"))
                    return
                }
                taskQueueModel.setProperty(i, "taskId", result.id || 0)
                taskQueueModel.setProperty(i, "trainStatus", 1)
                taskQueueModel.setProperty(i, "trainProgress", 0.0)
                backendService.startTrainingTask(result.id)
            }
        }
        root.isTraining = true
        root.showToast("✅ 训练任务已启动")
    }

    function isWeightSaved(taskId) {
        for (var i = 0; i < taskQueueModel.count; i++) {
            if (Number(taskQueueModel.get(i).taskId || 0) === Number(taskId)) return taskQueueModel.get(i).saved === true
        }
        return true  // 不在队列中的历史权重默认允许评估
    }

    function findScenarioId(name) {
        for (var i = 0; i < scenarioModel.count; i++) {
            if (scenarioModel.get(i).name === name) return scenarioModel.get(i).id || 0
        }
        return 0
    }

    function collectEditedParams() {
        var result = {}
        for (var i = 0; i < paramEditModel.count; i++) {
            var item = paramEditModel.get(i)
            var val = item.value
            if (val === "true") { result[item.name] = true }
            else if (val === "false") { result[item.name] = false }
            else if (!isNaN(val) && val.trim() !== "") { result[item.name] = Number(val) }
            else { result[item.name] = val }
        }
        return result
    }

    function appendTaskToQueue() {
        var dsItem = datasetModel.get(datasetCombo.currentIndex)
        var algoItem = algoModel.get(algoCombo.currentIndex)
        var taskParams = root.collectEditedParams()

        taskQueueModel.append({
            taskId: 0,
            evalTaskId: 0,
            scenario: scenarioCombo.currentText,
            dataset: dsItem ? dsItem.name : "",
            datasetId: dsItem ? (dsItem.id || 0) : 0,
            algo: algoItem ? algoItem.name : "",
            algoId: algoItem ? (algoItem.id || 0) : 0,
            algoKey: algoItem ? (algoItem.key || "") : "",
            params: taskParams,
            isSelected: true,
            saved: false,
            trainStatus: 0,
            trainProgress: 0.0,
            progressMessage: "",
            dbStatus: "",
            resultJson: ({}),
            outputDir: ""
        })
        root.taskCounter++
        root.checkStates()
        root.pendingAlgoKey = ""
        algoParamsPopup.close()
        root.saveToAppState()
        root.showToast("✅ 已追加训练任务至队列")
    }

    function canRunEvaluation() {
        if (root.isTraining || root.isEvaluating) return false
        for (var i = 0; i < weightOptionModel.count; i++) {
            if (weightOptionModel.get(i).isSelected) return true
        }
        return false
    }

    function startEvaluation() {
        evalResultModel.clear()
        root.pendingEvalTaskIds = []
        activeEvalSourceModel.clear()

        var totalWeights = weightOptionModel.count
        var selectedWeights = 0
        var noEvalBind = 0
        var noCheckpoint = 0
        var startedCount = 0

        for (var i = 0; i < weightOptionModel.count; i++) {
            var t = weightOptionModel.get(i)
            if (!t.isSelected) continue
            if (!t.taskId || t.taskId <= 0) continue
            if (!root.isWeightSaved(t.taskId)) continue
            selectedWeights++

            var scId = Number(t.scenarioId || root.findScenarioId(t.scenario))
            var evalAlgoId = 0
            var trainingAlgoKey = t.algoKey || root.algorithmKeyById(t.algoId || 0)
            var evalKey = root.trainingToEvalKey[trainingAlgoKey || ""]
            if (evalKey && root.evalAlgorithmMap[evalKey]) {
                evalAlgoId = root.evalAlgorithmMap[evalKey].id
            }
            if (!evalAlgoId) {
                noEvalBind++
                continue
            }

            var checkpointPath = t.checkpointPath || ""
            if (!checkpointPath) {
                noCheckpoint++
                continue
            }

            var evalParams = {}
            evalParams.model_checkpoint_path = checkpointPath

            var evalResult = backendService.createEvaluationTask(scId, t.datasetId || 0, t.datasetId || 0, evalAlgoId, evalParams)
            if (evalResult && evalResult.status === "success") {
                backendService.startEvaluationTask(evalResult.id)
                root.pendingEvalTaskIds = root.pendingEvalTaskIds.concat([evalResult.id || 0])
                activeEvalSourceModel.append({
                    evalTaskId: evalResult.id || 0,
                    trainingTaskId: t.taskId || 0,
                    scenario: t.scenario || "",
                    dataset: t.dataset || "",
                    algo: t.algo || "",
                    checkpointName: t.checkpointName || "",
                    checkpointPath: checkpointPath
                })
                startedCount++
            } else {
                root.showToast("⚠️ 创建评估任务失败: " + (evalResult ? (evalResult.message || "未知") : "无响应"))
            }
        }

        if (startedCount > 0) {
            root.isEvaluating = true
            root.saveToAppState()
        } else {
            var reason = "可选权重:" + totalWeights + " 已选:" + selectedWeights
            if (selectedWeights === 0) reason += " (请先勾选左侧训练权重)"
            else if (noEvalBind > 0) reason += " 缺评估绑定:" + noEvalBind
            else if (noCheckpoint > 0) reason += " 缺模型文件:" + noCheckpoint
            root.showToast("⚠️ 无可评估任务 - " + reason)
        }
    }

    // ================= 弹窗：算法参数配置 (追加任务前) =================
    Popup {
        id: algoParamsPopup
        width: 500; height: 400
        modal: true; focus: true
        x: Math.round((root.width - width) / 2)
        y: Math.round((root.height - height) / 2)
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { color: root.panelBg; radius: 8; border.color: root.primaryColor; border.width: 1 }

        onOpened: {
            var key = root.pendingAlgoKey
            var rawParams = root.algoParamsMap[key] || []
            var editable = []
            for (var i = 0; i < rawParams.length; i++) {
                var rp = rawParams[i]
                var val = rp.default_value
                if (typeof val !== "string") val = JSON.stringify(val)
                var opts = rp.options || rp.options_json || []
                editable.push({name: rp.name, label: rp.label || rp.name, value: val, defaultValue: val, optionsJson: JSON.stringify(opts)})
            }
            paramEditModel.clear()
            for (var j = 0; j < editable.length; j++) {
                paramEditModel.append(editable[j])
            }
        }

        ColumnLayout {
            anchors.fill: parent; anchors.margins: 20; spacing: 15
            RowLayout {
                Layout.fillWidth: true
                Text { text: "算法参数配置"; color: root.primaryColor; font.pixelSize: 16; font.bold: true }
                Item { Layout.fillWidth: true }
                Rectangle {
                    width: 28; height: 28; radius: 4; color: "transparent"
                    Text { text: "x"; color: root.textMuted; font.pixelSize: 16; anchors.centerIn: parent }
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; hoverEnabled: true
                        onEntered: parent.color = root.tableHoverBg
                        onExited: parent.color = "transparent"
                        onClicked: algoParamsPopup.close()
                    }
                }
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: root.borderColor }

            Text { text: "以下参数将从算法默认值预填充，您可按需修改："; color: root.textMuted; font.pixelSize: 12 }

            ListModel { id: paramEditModel }
            Rectangle {
                Layout.fillWidth: true; Layout.fillHeight: true
                color: root.bgDark; border.color: root.borderColor; border.width: 1; radius: 6; clip: true

                Rectangle { width: parent.width; height: 32; color: Theme.rowAlt
                    RowLayout { anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12; spacing: 10
                        Text { text: "参数名"; color: root.textMuted; font.pixelSize: 12; font.bold: true; Layout.fillWidth: true }
                        Text { text: "值"; color: root.textMuted; font.pixelSize: 12; font.bold: true; Layout.preferredWidth: 200 }
                    }
                }

                ListView {
                    id: paramEditList
                    anchors.fill: parent; anchors.topMargin: 32; clip: true
                    model: paramEditModel
                    delegate: Rectangle {
                        width: paramEditList.width; height: 40
                        color: index % 2 === 0 ? "transparent" : root.tableHoverBg
                        property var _opts: { try { return JSON.parse(model.optionsJson || "[]") } catch(e) { return [] } }
                        RowLayout {
                            anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12; spacing: 10
                            Text {
                                text: model.label; color: root.textColor; font.pixelSize: 13
                                Layout.fillWidth: true; verticalAlignment: Text.AlignVCenter
                            }
                            // 有 options = 下拉框
                            StableComboBox {
                                visible: _opts.length > 0
                                Layout.preferredWidth: 200
                                model: _opts
                                currentIndex: {
                                    var cv = model.value !== undefined ? String(model.value) : ""
                                    for (var oi = 0; oi < _opts.length; oi++) { if (String(_opts[oi]) === cv) return oi }
                                    return 0
                                }
                                onCurrentIndexChanged: {
                                    if (currentIndex >= 0 && currentIndex < _opts.length)
                                        paramEditModel.setProperty(index, "value", _opts[currentIndex])
                                }
                                background: Rectangle { color: "transparent"; border.color: root.borderColor; border.width: 1; radius: 4 }
                                contentItem: Text { text: parent.currentText || ""; color: root.primaryColor; font.pixelSize: 13; verticalAlignment: Text.AlignVCenter; padding: 8 }
                            }
                            // 无 options = 文本输入
                            Rectangle {
                                visible: _opts.length === 0
                                Layout.preferredWidth: 200; height: 30
                                color: "transparent"; border.color: root.borderColor; border.width: 1; radius: 4
                                TextInput {
                                    text: model.value
                                    color: root.primaryColor; font.pixelSize: 13; font.family: "Courier"
                                    anchors.fill: parent; leftPadding: 8; verticalAlignment: TextInput.AlignVCenter
                                    onTextChanged: paramEditModel.setProperty(index, "value", text)
                                }
                            }
                        }
                    }
                }
            }

            RowLayout { Layout.fillWidth: true; spacing: 15
                Item { Layout.fillWidth: true }
                Button {
                    text: "恢复默认"; Layout.preferredWidth: 100; Layout.preferredHeight: 32
                    background: Rectangle { color: "transparent"; border.color: root.borderColor; border.width: 1; radius: 4 }
                    contentItem: Text { text: parent.text; color: root.textMuted; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: {
                        for (var ri = 0; ri < paramEditModel.count; ri++) {
                            var defVal = paramEditModel.get(ri).defaultValue
                            if (defVal !== undefined) paramEditModel.setProperty(ri, "value", defVal)
                        }
                    }
                }
                Button {
                    text: "确认追加"; Layout.preferredWidth: 100; Layout.preferredHeight: 32
                    background: Rectangle { color: root.primaryColor; radius: 4 }
                    contentItem: Text { text: parent.text; color: "black"; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: root.appendTaskToQueue()
                }
            }
        }

    }
}
