# -*- coding: utf-8 -*-
from pathlib import Path
import sys
import os
import threading

from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlContext
from PySide6.QtCore import QUrl, QObject, Signal, Slot, Property

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from backend import (
    BackendPaths,
    BackendServiceFacade,
    create_backend_engine,
    create_session_factory,
    initialize_backend_database,
)
from backend.database import Base
from backend.qt.bridge import BackendBridge


def _build_backend() -> BackendBridge:
    root = Path(__file__).resolve().parent
    paths = BackendPaths(root=root)
    engine = create_backend_engine(paths.database_path)
    initialize_backend_database(engine)
    session_factory = create_session_factory(engine)
    facade = BackendServiceFacade.build(paths=paths, session_factory=session_factory)
    return BackendBridge(facade=facade)


class BackendService(QObject):
    systemStatsUpdated = Signal(dict)
    recentActivitiesUpdated = Signal(list)
    datasetsUpdated = Signal(dict)
    datasetSamplesUpdated = Signal(dict)
    datasetDirectoryUpdated = Signal(dict)
    datasetDirectoryLoading = Signal(bool)
    datasetPreviewSamplesUpdated = Signal(dict)
    samplePreviewUpdated = Signal(dict)
    datasetStatsUpdated = Signal(dict)
    sampleGrowthDataUpdated = Signal(dict)
    dataTypeDistributionUpdated = Signal(dict)
    importStatusUpdated = Signal(str, bool)

    cleaningTasksUpdated = Signal(dict)
    cleaningSuggestionsUpdated = Signal(dict)
    cleaningStatusUpdated = Signal(str, bool)

    enhancementTasksUpdated = Signal(dict)
    algorithmsUpdated = Signal(list)
    generationStatusUpdated = Signal(str, bool, float)
    generationOutputsUpdated = Signal(dict)

    evaluationScenariosUpdated = Signal(list)
    evaluationTasksUpdated = Signal(dict)
    evaluationResultsUpdated = Signal(dict)
    evaluationStatusUpdated = Signal(str, bool)
    settingValueLoaded = Signal(str, "QVariant")

    trainingTasksUpdated = Signal(dict)
    trainingStatusUpdated = Signal(str, bool, float)
    testSetImported = Signal(dict)
    algorithmBindingsUpdated = Signal(dict)

    taskLogsUpdated = Signal(dict)
    systemStatusUpdated = Signal(dict)
    settingsUpdated = Signal(dict)
    operationLogsUpdated = Signal(dict)

    # ── 边缘设备管理 + OTA ──────────────────────────────
    edgeDevicesUpdated = Signal(list)
    edgeDeviceOperationCompleted = Signal(dict)
    modelVersionsUpdated = Signal(list)

    def __init__(self):
        super().__init__()
        self._bridge = _build_backend()
        self._bridge.ensure_default_settings()
        self._bridge.seed_default_algorithms()
        self._bridge.facade.task_manager.mark_interrupted_tasks()


    def _run_in_background(self, task_id: int, runner, status_signal, success_msg: str):
        def worker():
            try:
                result = runner(task_id)
                if result.get("ok"):
                    status_signal.emit(success_msg, True)
                else:
                    status_signal.emit(result.get("message", "Task failed"), False)
            except Exception as exc:
                status_signal.emit(str(exc), False)

        threading.Thread(target=worker, daemon=True).start()

    def _run_generation_in_background(self, task_id: int):
        def worker():
            try:
                result = self._bridge.run_generation_task(task_id)
                if result.get("ok"):
                    self.generationStatusUpdated.emit("Generation complete", True, 100.0)
                else:
                    self.generationStatusUpdated.emit(result.get("message", "Task failed"), False, 0.0)
            except Exception as exc:
                self.generationStatusUpdated.emit(str(exc), False, 0.0)

        threading.Thread(target=worker, daemon=True).start()


    @Slot()
    def getSystemStats(self):
        result = self._bridge.get_system_stats()
        if result.get("ok"):
            self.systemStatsUpdated.emit(result["data"])
        else:
            self.systemStatsUpdated.emit({})

    @Slot(int)
    def getRecentActivities(self, limit: int):
        activities = self._bridge.get_recent_activities(limit)
        self.recentActivitiesUpdated.emit(activities)


    @Slot(int, int, str)
    def getDatasets(self, page: int, pageSize: int, status: str):
        result = self._bridge.get_datasets(page, pageSize, status)
        self.datasetsUpdated.emit(result)

    @Slot(int, int, int, str)
    def getDatasetSamples(self, datasetId: int, page: int, pageSize: int, status: str):
        result = self._bridge.get_dataset_samples(datasetId, page, pageSize, status)
        self.datasetSamplesUpdated.emit(result)

    @Slot(int, str)
    def getDatasetDirectory(self, datasetId: int, path: str):
        """异步加载目录内容，避免大数据集阻塞 UI 线程"""
        self.datasetDirectoryLoading.emit(True)
        def worker():
            try:
                result = self._bridge.get_dataset_directory(datasetId, path)
                self.datasetDirectoryUpdated.emit(result)
            except Exception as exc:
                self.datasetDirectoryUpdated.emit({"ok": False, "message": str(exc)})
            finally:
                self.datasetDirectoryLoading.emit(False)
        threading.Thread(target=worker, daemon=True).start()

    @Slot(int, int, str)
    def getDatasetPreviewSamples(self, datasetId: int, limit: int, status: str):
        result = self._bridge.get_dataset_preview_samples(datasetId, limit, status)
        self.datasetPreviewSamplesUpdated.emit(result)

    @Slot(int)
    def getSamplePreview(self, sampleId: int):
        result = self._bridge.get_sample_preview(sampleId)
        self.samplePreviewUpdated.emit(result)

    @Slot(str)
    def previewFileByPath(self, filePath: str):
        result = self._bridge.preview_file_by_path(filePath)
        self.samplePreviewUpdated.emit(result)

    @Slot(int)
    def getDatasetStats(self, datasetId: int):
        result = self._bridge.get_dataset_stats(datasetId)
        self.datasetStatsUpdated.emit(result)

    @Slot(str)
    def getSampleGrowthTrend(self, period: str):
        self.sampleGrowthDataUpdated.emit({})

    @Slot()
    def getDataTypeDistribution(self):
        result = self._bridge.get_data_type_distribution()
        if result.get("ok"):
            self.dataTypeDistributionUpdated.emit(result["data"])
        else:
            self.dataTypeDistributionUpdated.emit({})

    @Slot(int, str, result=dict)
    def uploadFile(self, datasetId: int, filePath: str) -> dict:
        result = self._bridge.import_files(datasetId, [filePath])
        return self._handle_import_result(result)

    @Slot(int, str, bool, result=dict)
    def importFolder(self, datasetId: int, folderPath: str, includeSubfolders: bool) -> dict:
        result = self._bridge.import_folder(datasetId, folderPath, includeSubfolders)
        return self._handle_import_result(result)

    def _handle_import_result(self, result: dict) -> dict:
        if result.get("ok"):
            data = result.get("data", {})
            imported_count = int(data.get("imported_count") or 0)
            failed_count = int(data.get("failed_count") or 0)
            self.datasetsUpdated.emit(self._bridge.get_datasets(1, 100, ""))
            self.importStatusUpdated.emit(f"已导入 {imported_count} 个文件，失败 {failed_count} 个", True)
            return {"status": "success", "data": data}
        message = result.get("message", "Unknown error")
        self.importStatusUpdated.emit(message, False)
        return {"status": "error", "message": message}


    @Slot(dict, result=dict)
    def importDatasetBundle(self, payload: dict) -> dict:
        result = self._bridge.import_dataset_bundle(payload or {})
        if result.get("ok"):
            self.datasetsUpdated.emit(self._bridge.get_datasets(1, 100, ""))
            return {"status": "success", "data": result.get("data", {})}
        return {"status": "error", "message": result.get("message", "Unknown error")}

    @Slot(str, str, str, result=dict)
    def createDataset(self, name: str, type_: str, description: str) -> dict:
        result = self._bridge.create_dataset(name, type_, description)
        if result.get("ok"):
            return {"status": "success", "id": result["data"]["id"], "name": result["data"]["name"], "dataset_status": result["data"]["status"]}
        return {"status": "error", "message": result.get("message", "Unknown error")}

    @Slot(int, str, str, result=dict)
    def updateDataset(self, datasetId: int, name: str, typeName: str) -> dict:
        result = self._bridge.update_dataset(datasetId, name, typeName)
        return {"status": "success" if result.get("ok") else "error", "message": result.get("message", "")}

    @Slot(int, result=dict)
    def deleteDataset(self, datasetId: int) -> dict:
        result = self._bridge.delete_dataset(datasetId)
        return {"status": "success" if result.get("ok") else "error", "message": result.get("message", "")}


    @Slot(str, result=list)
    def getCleaningStrategies(self, modality: str) -> list:
        algorithms = self._bridge.get_algorithms("cleaning", modality)
        return algorithms

    @Slot(int, str, dict, result=dict)
    def createCleaningTask(self, datasetId: int, modality: str, parameters: dict) -> dict:
        algorithm_ids = parameters.pop("algorithm_ids", []) if parameters else []
        result = self._bridge.create_cleaning_task(datasetId, algorithm_ids, parameters or {})
        if not result.get("ok"):
            self.cleaningStatusUpdated.emit(result.get("message", "Error"), False)
            return {"status": "error", "message": result.get("message", "Unknown error")}

        task_id = result["data"]["task_id"]
        self._run_in_background(
            task_id,
            self._bridge.run_cleaning_task,
            self.cleaningStatusUpdated,
            "Cleaning complete",
        )
        return {"status": "success", "id": task_id, "task_status": result["data"]["status"]}

    @Slot(int, str)
    def getCleaningTasks(self, datasetId: int, status: str):
        result = self._bridge.get_cleaning_tasks(datasetId, status)
        self.cleaningTasksUpdated.emit(result)

    @Slot(int, str, int, int)
    def getCleaningSuggestions(self, taskId: int, status: str, page: int, pageSize: int):
        result = self._bridge.get_cleaning_suggestions(taskId, status, page, pageSize)
        self.cleaningSuggestionsUpdated.emit(result)

    @Slot(int, str, result=dict)
    def approveCleaningSuggestion(self, suggestionId: int, action: str) -> dict:
        return self._bridge.approve_cleaning_suggestion(suggestionId, action)

    @Slot(list, str, result=dict)
    def batchApproveCleaningSuggestions(self, suggestionIds: list, action: str) -> dict:
        return self._bridge.batch_approve_cleaning_suggestions(list(suggestionIds), action)

    @Slot(int, str, result=dict)
    def storeCleaningTaskResult(self, taskId: int, datasetName: str) -> dict:
        result = self._bridge.store_cleaning_task_result(taskId, datasetName)
        return {
            "status": "success" if result.get("ok") else "error",
            "data": result.get("data", {}),
            "message": result.get("message", ""),
        }


    @Slot(int, str, dict, int, result=dict)
    def createEnhancementTask(self, datasetId: int, algorithm: str, parameters: dict, targetCount: int) -> dict:
        algorithm_ids = [int(item.strip()) for item in str(algorithm or "").split(",") if item.strip()]
        result = self._bridge.create_generation_task(datasetId, 0, algorithm_ids, parameters or {}, targetCount)
        if not result.get("ok"):
            return {"status": "error", "message": result.get("message", "Unknown error")}
        return {"status": "success", "id": result["data"]["task_id"], "task_status": result["data"]["status"], "target_dataset_id": result["data"].get("target_dataset_id", 0), "target_dataset_name": result["data"].get("target_dataset_name", "")}

    @Slot(int, str)
    def getEnhancementTasks(self, datasetId: int, status: str):
        result = self._bridge.get_generation_tasks(datasetId, status)
        self.enhancementTasksUpdated.emit(result)

    @Slot(str, str)
    def getAlgorithms(self, category: str, modality: str):
        algorithms = self._bridge.get_algorithms(category, modality)
        self.algorithmsUpdated.emit(algorithms)

    @Slot(str, result=dict)
    def reflectParameters(self, filePath: str) -> dict:
        return self._bridge.reflect_parameters(filePath)

    @Slot(str, result=dict)
    def importPluginFile(self, filePath: str) -> dict:
        return self._bridge.import_plugin_file(filePath)

    @Slot(dict, result=dict)
    def createAlgorithm(self, payload: dict) -> dict:
        return self._bridge.create_algorithm(payload)

    @Slot(int, dict, result=dict)
    def updateAlgorithm(self, algorithmId: int, payload: dict) -> dict:
        return self._bridge.update_algorithm(algorithmId, payload)

    @Slot(int, result=dict)
    def deleteAlgorithm(self, algorithmId: int) -> dict:
        return self._bridge.delete_algorithm(algorithmId)

    @Slot(int, bool, result=dict)
    def setAlgorithmEnabled(self, algorithmId: int, enabled: bool) -> dict:
        return self._bridge.set_algorithm_enabled(algorithmId, enabled)

    @Slot(int, result=dict)
    def validateAlgorithm(self, algorithmId: int) -> dict:
        return self._bridge.validate_algorithm(algorithmId)

    @Slot(result=dict)
    def openAlgorithmPluginSpec(self) -> dict:
        spec_path = Path(__file__).resolve().parent / "docs" / "ISG 算法插件开发规范 v1.0.pdf"
        if not spec_path.exists():
            return {"status": "error", "message": f"未找到插件规范文档: {spec_path}"}
        if QDesktopServices.openUrl(QUrl.fromLocalFile(str(spec_path))):
            return {"status": "success"}
        return {"status": "error", "message": "无法打开插件规范文档"}

    @Slot(str, result=dict)
    def downloadAlgorithmPluginSpec(self, targetPath: str) -> dict:
        result = self._bridge.download_algorithm_plugin_spec(targetPath)
        if result.get("ok"):
            return {"status": "success", "path": result.get("path", "")}
        return {"status": "error", "message": result.get("message", "插件规范下载失败")}

    # ── 算法绑定 ──────────────────────────────────────────

    @Slot(result=dict)
    def getAlgorithmBindings(self) -> dict:
        bindings = self._bridge.get_algorithm_bindings()
        self.algorithmBindingsUpdated.emit(bindings)
        return bindings

    @Slot(str, str, result=dict)
    def saveAlgorithmBinding(self, trainingKey: str, evaluationKey: str) -> dict:
        return self._bridge.save_algorithm_binding(trainingKey, evaluationKey)

    @Slot(str, result=dict)
    def deleteAlgorithmBinding(self, trainingKey: str) -> dict:
        return self._bridge.delete_algorithm_binding(trainingKey)

    @Slot(int, result=dict)
    def startEnhancementTask(self, taskId: int) -> dict:
        self._run_generation_in_background(taskId)
        return {"status": "success"}

    @Slot(int, result=dict)
    def deleteTask(self, taskId: int) -> dict:
        result = self._bridge.delete_task(taskId)
        return {"status": "success" if result.get("ok") else "error", "message": result.get("message", "")}

    @Slot(int, str, result=dict)
    def updateTaskTitle(self, taskId: int, title: str) -> dict:
        result = self._bridge.update_task_title(taskId, title)
        if result.get("ok"):
            return {"status": "success", "data": result.get("data", {})}
        return {"status": "error", "message": result.get("message", "Unknown error")}

    @Slot(int, result=dict)
    def cancelTask(self, taskId: int) -> dict:
        return self._bridge.cancel_task(taskId)

    @Slot(int, result=dict)
    def stopEnhancementTask(self, taskId: int) -> dict:
        return self._bridge.cancel_task(taskId)

    @Slot(int, str, int, int)
    def getGenerationOutputs(self, taskId: int, status: str, page: int, pageSize: int):
        result = self._bridge.get_generation_outputs(taskId, status, page, pageSize)
        self.generationOutputsUpdated.emit(result)


    @Slot(str)
    def getEvaluationScenarios(self, modality: str):
        self.evaluationScenariosUpdated.emit(self._bridge.get_scenarios(modality))

    @Slot(int, int, int, int, dict, result=dict)
    def createEvaluationTask(self, scenarioId: int, baselineDatasetId: int, enhancedDatasetId: int, algorithmId: int, parameters: dict) -> dict:
        result = self._bridge.create_evaluation_task(scenarioId, baselineDatasetId, enhancedDatasetId, algorithmId, parameters or {})
        if not result.get("ok"):
            return {"status": "error", "message": result.get("message", "Unknown error")}
        return {"id": result["data"]["task_id"], "status": "success"}

    @Slot(str)
    def getEvaluationTasks(self, status: str):
        result = self._bridge.get_evaluation_tasks(status)
        self.evaluationTasksUpdated.emit(result)

    @Slot(int)
    def getEvaluationResults(self, taskId: int):
        result = self._bridge.get_evaluation_results(taskId)
        self.evaluationResultsUpdated.emit(result)

    @Slot(int, result=dict)
    def startEvaluationTask(self, taskId: int) -> dict:
        self._run_in_background(
            taskId,
            self._bridge.run_evaluation_task,
            self.evaluationStatusUpdated,
            "Evaluation complete",
        )
        return {"status": "success"}

    @Slot(int, str, result=dict)
    def exportEvaluationReport(self, taskId: int, format_: str) -> dict:
        import tempfile
        ext = format_.lower() if format_ else "json"
        output_path = Path(tempfile.gettempdir()) / f"evaluation_report_{taskId}.{ext}"
        return self._bridge.export_evaluation_report(taskId, str(output_path))

    @Slot()
    def getScenarios(self):
        self.evaluationScenariosUpdated.emit([{"id": s.get("id", 0), "name": s.get("name", ""), "key": s.get("key", "")} for s in self._bridge.get_scenarios()])

    @Slot(int, int, int, dict, result=dict)
    def createTrainingTask(self, scenarioId: int, datasetId: int, algorithmId: int, parameters: dict) -> dict:
        result = self._bridge.create_training_task(scenarioId, datasetId, algorithmId, parameters or {})
        if not result.get("ok"):
            return {"status": "error", "message": result.get("message", "Unknown error")}
        return {"status": "success", "id": result["data"]["task_id"], "task_status": result["data"]["status"]}

    @Slot(int, str)
    def getTrainingTasks(self, datasetId: int, status: str):
        result = self._bridge.get_training_tasks(datasetId, status)
        self.trainingTasksUpdated.emit(result)

    def _run_training_in_background(self, task_id: int):
        def worker():
            try:
                result = self._bridge.run_training_task(task_id)
                if result.get("ok"):
                    self.trainingStatusUpdated.emit("Training complete", True, 100.0)
                else:
                    self.trainingStatusUpdated.emit(result.get("message", "Task failed"), False, 0.0)
            except Exception as exc:
                self.trainingStatusUpdated.emit(str(exc), False, 0.0)
        threading.Thread(target=worker, daemon=True).start()

    @Slot(int, result=dict)
    def startTrainingTask(self, taskId: int) -> dict:
        self._run_training_in_background(taskId)
        return {"status": "success"}

    @Slot(str, str, result=dict)
    def importTestSet(self, datasetName: str, folderPath: str) -> dict:
        result = self._bridge.import_test_set(datasetName, folderPath)
        if result.get("ok"):
            self.testSetImported.emit(result["data"])
            return {"status": "success", "data": result["data"]}
        return {"status": "error", "message": result.get("message", "Unknown error")}

    @Slot()
    def getSystemStatus(self):
        self.systemStatusUpdated.emit(self._bridge.get_system_status())

    @Slot()
    def getSettings(self):
        self.settingsUpdated.emit(self._bridge.get_settings())

    @Slot(str, "QVariant", result=dict)
    def updateSetting(self, key: str, value):
        return self._bridge.update_setting(key, value)

    @Slot(str)
    def getSetting(self, key: str):
        val = self._bridge.get_setting(key)
        self.settingValueLoaded.emit(key, val if val is not None else "")

    @Slot(int, int, str)
    def getOperationLogs(self, page: int, pageSize: int, resourceType: str):
        self.operationLogsUpdated.emit(self._bridge.get_operation_logs(page, pageSize, resourceType))

    # ── 边缘设备管理 + OTA Slots ───────────────────────────

    @Slot(str, str, str, int, result="QVariant")
    def registerEdgeDevice(self, deviceId: str, name: str, host: str, grpcPort: int = 50051) -> dict:
        print(f"[BackendService] registerEdgeDevice: id={deviceId}, name={name}, host={host}, port={grpcPort}")
        result = self._bridge.register_edge_device(deviceId, name, host, grpcPort)
        print(f"[BackendService] register result: {result}")
        self.edgeDevicesUpdated.emit(self._bridge.list_edge_devices(""))
        return result

    @Slot(str, result=dict)
    def getEdgeDevice(self, deviceId: str) -> dict:
        return self._bridge.get_edge_device(deviceId)

    @Slot(str, result=list)
    def listEdgeDevices(self, status: str) -> list:
        devices = self._bridge.list_edge_devices(status)
        # 过滤为 QML ListModel 可用的扁平字段
        result = []
        for d in devices:
            result.append({
                "device_id": d.get("device_id", ""),
                "name": d.get("name", ""),
                "host": d.get("host", ""),
                "status": d.get("status", "unknown"),
                "scene": d.get("scene", ""),
                "model_version": d.get("model_version", ""),
                "fps": d.get("fps", 0),
                "npu_usage": d.get("npu_usage", 0),
                "cpu_temp": d.get("cpu_temp", 0),
            })
        print(f"[BackendService] listEdgeDevices: {len(result)} devices for QML")
        return result

    @Slot(str, result=dict)
    def unregisterEdgeDevice(self, deviceId: str) -> dict:
        result = self._bridge.unregister_edge_device(deviceId)
        self.edgeDevicesUpdated.emit(self._bridge.list_edge_devices(""))
        return result

    @Slot(str, str, result=dict)
    def switchDeviceScene(self, deviceId: str, scene: str) -> dict:
        def worker():
            try:
                result = self._bridge.switch_device_scene(deviceId, scene)
                self.edgeDeviceOperationCompleted.emit(result)
                self.edgeDevicesUpdated.emit(self._bridge.list_edge_devices(""))
            except Exception as e:
                self.edgeDeviceOperationCompleted.emit({"status": "error", "message": str(e)})
        threading.Thread(target=worker, daemon=True).start()
        return {"status": "pending", "message": "切换场景中..."}

    @Slot(str, str, str, result=dict)
    def pushModelToDevice(self, deviceId: str, modelPath: str, modelVersion: str) -> dict:
        def worker():
            try:
                result = self._bridge.push_model_to_device(deviceId, modelPath, modelVersion)
                self.edgeDeviceOperationCompleted.emit(result)
                self.edgeDevicesUpdated.emit(self._bridge.list_edge_devices(""))
            except Exception as e:
                self.edgeDeviceOperationCompleted.emit({"status": "error", "message": str(e)})
        threading.Thread(target=worker, daemon=True).start()
        return {"status": "pending", "message": "推送模型中..."}

    @Slot(str, str, result=dict)
    def rollbackDevice(self, deviceId: str, target: str) -> dict:
        def worker():
            try:
                result = self._bridge.rollback_device(deviceId, target)
                self.edgeDeviceOperationCompleted.emit(result)
                self.edgeDevicesUpdated.emit(self._bridge.list_edge_devices(""))
            except Exception as e:
                self.edgeDeviceOperationCompleted.emit({"status": "error", "message": str(e)})
        threading.Thread(target=worker, daemon=True).start()
        return {"status": "pending", "message": "回滚中..."}

    @Slot(str, result=dict)
    def restartDevice(self, deviceId: str) -> dict:
        def worker():
            try:
                result = self._bridge.restart_device(deviceId)
                self.edgeDeviceOperationCompleted.emit(result)
                self.edgeDevicesUpdated.emit(self._bridge.list_edge_devices(""))
            except Exception as e:
                self.edgeDeviceOperationCompleted.emit({"status": "error", "message": str(e)})
        threading.Thread(target=worker, daemon=True).start()
        return {"status": "pending", "message": "重启中..."}

    @Slot(str, str, str, str, str, str, str, result=dict)
    def registerModelVersion(self, name: str, version: str, modelType: str,
                              scene: str, filePath: str, quantization: str = "fp16",
                              notes: str = "") -> dict:
        result = self._bridge.register_model_version(
            name, version, modelType, scene, filePath, quantization, notes
        )
        self.modelVersionsUpdated.emit(self._bridge.list_model_versions("", ""))
        return result

    @Slot(str, str, result=list)
    def listModelVersions(self, scene: str, modelType: str) -> list:
        return self._bridge.list_model_versions(scene, modelType)

    @Slot(str, dict, result=dict)
    def onDeviceHeartbeat(self, deviceId: str, telemetry: dict) -> dict:
        result = self._bridge.on_device_heartbeat(deviceId, telemetry)
        self.edgeDevicesUpdated.emit(self._bridge.list_edge_devices(""))
        return result

    # ── ONNX 推送 (方案B: PC导出ONNX → 板子端转换RKNN) ──────

    @Slot(str, str, str, result=dict)
    def pushOnnxToDevice(self, deviceId: str, onnxPath: str, modelVersion: str) -> dict:
        """推送 ONNX 到设备，板子端做 ONNX→RKNN 转换"""
        def worker():
            result = self._bridge.push_onnx_to_device(deviceId, onnxPath, modelVersion)
            self.edgeDeviceOperationCompleted.emit(result)
            self.edgeDevicesUpdated.emit(self._bridge.list_edge_devices(""))
        threading.Thread(target=worker, daemon=True).start()
        return {"status": "pending", "message": "推送ONNX中..."}

    # ── MQTT 实时数据 ────────────────────────────────────────

    edgeDetectionReceived = Signal(dict)
    edgeHealthReceived = Signal(dict)
    mqttConfigUpdated = Signal(dict)  # MQTT 配置更新信号

    def _on_mqtt_detection(self, data):
        """MQTT 检测结果回调 (从 MqttBridge)"""
        self.edgeDetectionReceived.emit({
            "device_id": data.device_id,
            "frame_index": data.frame_index,
            "timestamp_us": data.timestamp_us,
            "detections": data.detections or [],
        })

    def _on_mqtt_health(self, data):
        """MQTT 心跳回调 (从 MqttBridge)"""
        self.edgeHealthReceived.emit({
            "device_id": data.device_id,
            "status": data.status,
            "frame_index": data.frame_index,
            "timestamp": data.timestamp,
        })

    def _start_mqtt_bridge(self, broker_host: str, broker_port: int = 1883):
        """启动 MQTT 订阅桥接"""
        try:
            from backend.mqtt_bridge import MqttBridge
            self._mqtt_bridge = MqttBridge(
                broker_host=broker_host,
                broker_port=broker_port,
                on_detection=self._on_mqtt_detection,
                on_health=self._on_mqtt_health,
            )
            if self._mqtt_bridge.start():
                print(f"[MQTT Bridge] 已连接 {broker_host}:{broker_port}")
            else:
                print(f"[MQTT Bridge] 连接失败")
        except ImportError:
            print("[MQTT Bridge] paho-mqtt 未安装, MQTT 实时数据不可用")
        except Exception as e:
            print(f"[MQTT Bridge] 启动失败: {e}")

    def _restart_mqtt_bridge(self, broker_host: str, broker_port: int):
        """重启 MQTT Bridge (使用新配置)"""
        if hasattr(self, '_mqtt_bridge') and self._mqtt_bridge:
            self._mqtt_bridge.stop()
        self._start_mqtt_bridge(broker_host, broker_port)

    # ── MQTT 配置 Slots ─────────────────────────────────────

    @Slot(result=dict)
    def getMqttConfig(self) -> dict:
        """获取 MQTT 配置"""
        return self._bridge.get_mqtt_config()

    @Slot(str, int, result=dict)
    def updateMqttConfig(self, broker_host: str, broker_port: int) -> dict:
        """更新 MQTT 配置并重连"""
        result = self._bridge.update_mqtt_config(broker_host, broker_port)
        if result.get("ok"):
            self._restart_mqtt_bridge(broker_host, broker_port)
            self.mqttConfigUpdated.emit({
                "broker_host": broker_host,
                "broker_port": broker_port,
                "connected": getattr(self._mqtt_bridge, 'connected', False) if hasattr(self, '_mqtt_bridge') else False,
            })
        return result

    @Slot(result=bool)
    def testMqttConnection(self) -> bool:
        """测试当前 MQTT 连接状态"""
        if hasattr(self, '_mqtt_bridge') and self._mqtt_bridge:
            return self._mqtt_bridge.connected
        return False

    # ── 设备发现 ────────────────────────────────────────────

    edgeDeviceDiscovered = Signal(dict)

    @Slot(result=list)
    def scanEdgeDevices(self) -> list:
        """扫描局域网内的边缘设备 (mDNS)"""
        try:
            from backend.services.device_discovery_service import DeviceDiscoveryService
            discovery = DeviceDiscoveryService()
            devices = discovery.scan(timeout=5.0)
            return devices
        except ImportError:
            print("[DeviceDiscovery] zeroconf 未安装, 设备发现不可用")
            return []
        except Exception as e:
            print(f"[DeviceDiscovery] 扫描失败: {e}")
            return []



def start_qml_app():
    os.environ["QT_QUICK_CONTROLS_STYLE"] = "Basic"
    app = QGuiApplication(sys.argv)

    engine = QQmlApplicationEngine()

    backend_service = BackendService()

    # 从设置服务读取 MQTT 配置 (而非硬编码)
    mqtt_host = backend_service._bridge.get_mqtt_config().get("data", {}).get("broker_host", "debian10.local")
    mqtt_port = backend_service._bridge.get_mqtt_config().get("data", {}).get("broker_port", 1883)
    backend_service._start_mqtt_bridge(mqtt_host, mqtt_port)

    context = engine.rootContext()
    context.setContextProperty("backendService", backend_service)

    current_dir = os.path.dirname(os.path.abspath(__file__))
    qml_file = os.path.join(current_dir, "ui", "main_windows.qml")

    if not os.path.exists(qml_file):
        print(f"Error: QML file not found -> {qml_file}")
        sys.exit(-1)

    engine.warnings.connect(lambda warnings: print("\nQML warnings:\n" + "\n".join([w.toString() for w in warnings])))
    engine.load(QUrl.fromLocalFile(qml_file))

    if not engine.rootObjects():
        print("Error: QML failed to load; see warnings above.")
        sys.exit(-1)

    sys.exit(app.exec())


def main():
    start_qml_app()


if __name__ == "__main__":
    main()
