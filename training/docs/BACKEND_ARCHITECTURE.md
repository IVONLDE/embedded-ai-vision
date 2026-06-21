# ISG-mian 后端架构文档

> 本文档是 CLAUDE.md 中引用的权威架构文档，描述 PC 端管理平台的后端设计与实现。

## 架构总览

ISG-mian 后端采用**分层架构**，从上到下依次为：

```
QML UI → BackendService → BackendBridge → ServiceFacade → Services → Repositories → SQLAlchemy ORM → SQLite
```

每一层职责明确，上层只依赖直接下层，不跨层调用。

## 1. 入口层 — BackendService

**文件**: `main.py`

`BackendService` 是 QML 与 Python 后端的唯一桥梁，继承自 `QObject`。

### 职责

- 定义 ~50 个 Qt 信号，通知 UI 数据更新
- 将 QML 调用转发到 `BackendBridge`
- 管理后台工作线程（`threading.Thread(daemon=True)`）
- 处理 MQTT 桥接的启动与停止

### 启动流程

```
1. _build_backend()
   ├─ 创建 BackendPaths (目录结构)
   ├─ 创建数据库引擎 (create_backend_engine)
   ├─ 创建会话工厂 (create_session_factory)
   └─ 构建 BackendServiceFacade (依赖注入)

2. 创建 BackendBridge (Facade 包装)

3. seed_data.py 注册默认算法 (50+ 算法)

4. 启动 MqttBridge (边缘设备实时数据)
```

### 信号定义（部分）

| 信号 | 用途 |
|------|------|
| `datasetsUpdated` | 数据集列表变更 |
| `cleaningTasksUpdated` | 清洗任务状态变更 |
| `generationTasksUpdated` | 增强任务状态变更 |
| `evaluationTasksUpdated` | 评估任务状态变更 |
| `systemStatsUpdated` | 系统统计信息更新 |
| `edgeDeviceStatusUpdated` | 边缘设备状态更新 |

### 关键规则

- **所有 QML 调用必须通过 BackendService**，不直接访问 core/backend 模块
- **后台任务使用 `threading.Thread(daemon=True)`**，通过信号通知 UI
- **不在线程中操作 UI**，只通过 `emit` 信号

---

## 2. 桥接层 — BackendBridge

**文件**: `backend/qt/bridge.py`

### 职责

- 提供 80+ 个方法供 `BackendService` 调用
- 错误归一化：将各种异常转为 `{"status": "error", "message": str(e)}`
- QML 序列化：将 ORM 对象转为结构化字典

### 方法分类

| 类别 | 方法示例 |
|------|---------|
| 数据集 | `create_dataset()`, `import_files()`, `import_folder()`, `import_dataset_bundle()` |
| 清洗 | `create_cleaning_task()`, `run_cleaning_task()`, `approve_cleaning_suggestion()` |
| 增强 | `create_generation_task()`, `run_generation_task()` |
| 训练 | `create_training_task()`, `run_training_task()` |
| 评估 | `create_evaluation_task()`, `export_evaluation_report()` |
| 边缘 | `register_edge_device()`, `push_model_to_device()`, `switch_device_scene()` |
| MQTT | `get_mqtt_config()`, `update_mqtt_config()` |

### 返回值约定

```python
# 成功
{"status": "ok", "data": {...}}

# 失败
{"status": "error", "message": "数据集不存在"}
```

---

## 3. 依赖注入 — BackendServiceFacade

**文件**: `backend/service_facade.py`

### 职责

组装所有依赖关系，是整个后端的**依赖注入容器**。

### 构建过程

```python
@classmethod
def build(cls, paths, engine, session_factory):
    # 1. 创建 8 个 Repository
    dataset_repo = DatasetRepository(session_factory)
    task_repo = TaskRepository(session_factory)
    algorithm_repo = AlgorithmRepository(session_factory)
    settings_repo = SettingsRepository(session_factory)
    log_repo = LogRepository(session_factory)
    edge_device_repo = EdgeDeviceRepository(session_factory)
    model_version_repo = ModelVersionRepository(session_factory)

    # 2. 创建 TaskManager
    task_manager = TaskManager(task_repo, log_repo, paths)

    # 3. 创建 PluginRunner
    plugin_runner = PluginRunner(paths.plugins_dir)

    # 4. 创建 9 个 Service (注入 repo + task_manager + plugin_runner)
    dataset_service = DatasetService(paths, session_factory, dataset_repo, task_manager)
    cleaning_service = CleaningService(...)
    generation_service = GenerationService(...)
    # ...

    return cls(
        dataset_service=dataset_service,
        cleaning_service=cleaning_service,
        # ...
    )
```

---

## 4. 服务层

**目录**: `backend/services/`

所有服务继承自 `ServiceBase`，持有 `paths` 和 `session_factory`。

### 服务清单

| 服务 | 文件 | 职责 |
|------|------|------|
| `DatasetService` | `dataset_service.py` | 数据集 CRUD、文件导入/导出、存储路径管理 |
| `CleaningService` | `cleaning_service.py` | 清洗任务编排、建议生成、审批执行 |
| `GenerationService` | `generation_service.py` | 样本生成/增强任务、输出持久化、标签继承 |
| `TrainingService` | `training_service.py` | 模型训练任务管理 |
| `EvaluationService` | `evaluation_service.py` | 评估场景、任务执行、报告导出、多 Agent 仿真 |
| `AlgorithmService` | `algorithm_service.py` | 算法插件注册、验证、启用/禁用、多模态过滤 |
| `ExportService` | `export_service.py` | 模型导出 (ONNX/RKNN) |
| `EdgeService` | `edge_service.py` | 边缘设备 OTA、模型推送 |
| `SettingsService` | `settings_service.py` | 应用设置管理 |

### 服务调用模式

```python
# 典型服务方法
def create_cleaning_task(self, dataset_id, algorithm_key, parameters):
    # 1. 验证输入
    dataset = self.dataset_repo.get_by_id(dataset_id)
    if not dataset:
        raise NotFoundError(f"数据集 {dataset_id} 不存在")

    # 2. 创建任务记录
    task = self.task_manager.start(
        task_type=TaskType.CLEANING,
        dataset_id=dataset_id,
        algorithm_key=algorithm_key,
    )

    # 3. 启动后台线程执行
    thread = threading.Thread(
        target=self._run_cleaning_worker,
        args=(task.id, dataset, algorithm_key, parameters),
        daemon=True,
    )
    thread.start()

    return task.to_dict()
```

---

## 5. 数据访问层 — Repositories

**目录**: `backend/repositories/`

所有 Repository 继承自 `RepositoryBase`，提供类型化的查询方法。

### Repository 清单

| Repository | 文件 | 主要方法 |
|-----------|------|---------|
| `DatasetRepository` | `dataset_repository.py` | `get_by_id()`, `list_all()`, `create()`, `update_stats()` |
| `TaskRepository` | `task_repository.py` | `get_by_id()`, `list_by_dataset()`, `update_status()` |
| `AlgorithmRepository` | `algorithm_repository.py` | `get_by_key()`, `list_by_category()`, `toggle_enabled()` |
| `SettingsRepository` | `settings_repository.py` | `get()`, `set()`, `get_all()` |
| `LogRepository` | `log_repository.py` | `append()`, `list_by_task()` |
| `EdgeDeviceRepository` | `edge_device_repository.py` | `get_by_id()`, `register()`, `update_status()` |
| `ModelVersionRepository` | `model_version_repository.py` | `create()`, `get_latest()`, `list_by_device()` |

### 会话管理

```python
# 主线程：复用会话（依赖注入）
session = self.session_factory()

# 后台线程：线程局部会话
session = SessionLocal()  # 每个线程独立会话
try:
    # ... 数据库操作 ...
    session.commit()
except:
    session.rollback()
    raise
finally:
    session.close()
```

---

## 6. 数据模型

**文件**: `backend/models.py`

共 27 个 SQLAlchemy ORM 模型，核心模型如下：

### 核心模型关系

```
Dataset ──1:N──→ Sample
  │
  ├──1:N──→ DatasetStatistics
  │
  └──1:N──→ Task ──1:N──→ TaskLog
                │
                ├──1:N──→ CleaningSuggestion
                │
                └──1:N──→ GenerationOutput

Algorithm ──1:N──→ AlgorithmParameter
     │
     └──1:1──→ AlgorithmBinding

EvaluationScenario ──1:N──→ EvaluationResult

EdgeDevice ──1:N──→ ModelVersion

AppSetting (独立)
OperationLog (独立)
SystemLog (独立)
```

### 关键模型字段

#### Dataset

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Integer (PK) | 数据集 ID |
| `name` | String | 数据集名称 |
| `modality` | String | 模态 (image/audio/timeseries/tabular/multimodal) |
| `status` | String | 状态 (importing/ready/cleaning/training) |
| `sample_count` | Integer | 样本总数 |
| `storage_path` | String | 存储路径 |

#### Task

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Integer (PK) | 任务 ID |
| `type` | Enum | 任务类型 (CLEANING/GENERATION/EVALUATION) |
| `status` | Enum | 状态 (PENDING/RUNNING/COMPLETED/FAILED/CANCELLED) |
| `dataset_id` | Integer (FK) | 关联数据集 |
| `algorithm_key` | String | 使用的算法标识 |
| `progress` | Integer | 进度 0-100 |
| `output_dir` | String | 输出目录 |

#### Algorithm

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Integer (PK) | 算法 ID |
| `key` | String (Unique) | 算法唯一标识 (如 `generation.image.geometric_transform`) |
| `category` | Enum | 类别 (CLEANING/GENERATION/EVALUATION) |
| `name` | String | UI 显示名称 |
| `entry_point` | String | 插件模块路径 |
| `enabled` | Boolean | 是否启用 |

#### EdgeDevice

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Integer (PK) | 设备 ID |
| `device_id` | String (Unique) | 设备标识 (如 `rk3399pro-edge-001`) |
| `ip_address` | String | IP 地址 |
| `scene` | String | 当前场景 |
| `status` | String | 在线状态 |
| `last_heartbeat` | DateTime | 最后心跳时间 |

---

## 7. 插件系统

**目录**: `backend/plugins/`

### 组件

| 组件 | 文件 | 职责 |
|------|------|------|
| `PluginRunner` | `runner.py` | 加载/执行插件，管理生命周期 |
| `PluginContext` | `contract.py` | 提供进度上报、日志、取消检查 |
| `Reflector` | `reflector.py` | 反射 PARAMETERS 列表，生成 UI 控件 |

### 插件协议

```python
class AlgorithmPlugin(Protocol):
    PARAMETERS: list[dict[str, Any]]  # 模块级变量
    def run(self, payload: dict, context: PluginContext) -> dict: ...
```

### 执行流程

```
1. AlgorithmService 获取算法 key
2. PluginRunner 根据 entry_point 加载 .py 模块
3. Reflector 反射 PARAMETERS → UI 生成参数控件
4. 用户配置参数 → 创建任务
5. PluginRunner.run() 执行插件
   ├─ 传入 payload (parameters + input + output)
   └─ 传入 context (progress + log + cancel)
6. 插件返回结果 → 服务持久化
```

详见 [ALGORITHM_PLUGIN_SPEC.md](ALGORITHM_PLUGIN_SPEC.md)。

---

## 8. 任务管理器

**文件**: `backend/task_manager.py`

### 职责

- 任务生命周期：`start()` → `set_progress()` → `complete()` / `fail()` / `cancel()`
- 取消支持：`request_cancel()` + `is_cancel_requested()`
- 输出目录管理：自动创建任务输出目录
- 日志附加：将执行日志关联到任务

### 状态机

```
PENDING → RUNNING → COMPLETED
                  → FAILED
                  → CANCELLED
                  → INTERRUPTED
```

---

## 9. 边缘设备通信

### EdgeClient

**文件**: `backend/edge_client.py`

支持三种通信模式：

| 模式 | 用途 | 说明 |
|------|------|------|
| MQTT | 实时数据 | 推荐，支持心跳/检测结果/OTA 状态 |
| SSH + JSON-RPC | 兼容模式 | 通过 Unix Socket 执行命令 |
| gRPC | 直接连接 | 可选，支持模型推送/场景切换 |

### MqttBridge

**文件**: `backend/mqtt_bridge.py`

订阅 `edge/#` 主题，接收：
- `edge/{device_id}/detections` — 实时检测结果
- `edge/{device_id}/health` — 心跳/遥测
- `edge/{device_id}/ota_status` — OTA 状态

断线重连：指数退避（5s 初始，60s 最大）。

---

## 10. 存储管理

### BackendPaths

**文件**: `backend/storage/paths.py`

管理应用目录结构：

```
root/
├── data/
│   ├── datasets/        # 数据集文件
│   ├── tasks/           # 任务输出
│   ├── reports/         # 评估报告
│   └── isg_backend.db   # SQLite 数据库
├── plugins/             # 算法插件
├── logs/                # 日志
└── settings/            # 配置
```

### FileIndexer

**文件**: `backend/storage/file_indexer.py`

- 文件复制到数据集目录（去重）
- SHA256 计算
- MIME 类型检测

---

## 11. 异常体系

**文件**: `backend/errors.py`

```
BackendError (基类)
├── ValidationError    # 输入验证失败
├── NotFoundError      # 资源不存在
└── TaskCancellationRequested  # 任务取消
```

---

## 12. 默认算法注册

**文件**: `backend/seed_data.py`

首次启动时注册 50+ 默认算法：

| 类别 | 数量 | 示例 |
|------|------|------|
| 清洗 (CLEANING) | ~10 | 图像模糊检测、重复检测、异常值检测 |
| 增强 (GENERATION) | ~30 | 几何变换、颜色抖动、音频增强、文本增强 |
| 训练 (TRAINING) | ~5 | YOLOv5 检测器、声纳分类器、船舶分类器 |
| 评估 (EVALUATION) | ~5 | 样本计数比较、多 Agent 仿真 |

---

## 13. 数据流

### 数据集处理流程

```
导入文件 → FileIndexer (去重/索引) → Dataset (元数据)
                                          │
                                    Sample (样本记录)
                                          │
                                    清洗任务 → PluginRunner → 清洗建议
                                          │
                                    审批/执行 → 更新 Sample
                                          │
                                    增强任务 → PluginRunner → GenerationOutput
                                          │
                                    训练任务 → PyTorch → 模型文件
                                          │
                                    评估任务 → PluginRunner → EvaluationResult
                                          │
                                    导出 → ONNX → RKNN
                                          │
                                    推送 → EdgeClient → 边缘设备
```

### 边缘设备交互流程

```
PC 端                                    边缘端
  │                                        │
  ├─ MQTT: 订阅 edge/# ──────────────────→│
  │  ←──── 心跳/检测结果/OTA 状态 ────────┤
  │                                        │
  ├─ gRPC: PushModel ────────────────────→│
  │  ←──── ModelResponse ────────────────┤
  │                                        │
  ├─ gRPC: SwitchScene ──────────────────→│
  │  ←──── SceneResponse ────────────────┤
  │                                        │
  └─ MQTT: command ──────────────────────→│
     ←──── 执行结果 ──────────────────────┤
```
