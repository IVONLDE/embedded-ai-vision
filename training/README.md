# ISG-mian — PC 端 AI 管控平台

ISG-mian 是 RK-NPU Cortex 项目的 PC 端管理平台，负责数据管理、模型训练、边缘设备管控等全流程工作。

## 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| GUI 框架 | PySide6 + QML | 桌面应用，非 Web 架构 |
| 数据库 | SQLite (SQLAlchemy ORM) | 本地存储，无需外部数据库服务 |
| 深度学习 | PyTorch ≥ 2.0 | 模型训练与推理 |
| 模型导出 | RKNN-Toolkit1 ≥ 1.7 | PyTorch → ONNX → RKNN 转换 + INT8 量化 |
| 设备通信 | MQTT + gRPC | 边缘设备管控与数据回收 |
| 后台任务 | threading.Thread | 长耗时任务异步执行，Qt 信号通知 UI |

## 快速开始

### 环境要求

- Python ≥ 3.10
- 推荐使用虚拟环境

### 安装

```bash
cd training
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows

pip install -r requirements.txt
```

### 运行

```bash
python main.py
```

首次启动会自动创建数据库（`data/isg_backend.db`）并注册默认算法插件。

## 核心功能

### 数据管理

- **数据集导入**：支持图像、音频、时序、表格、多模态数据
- **数据清洗**：AI 驱动的清洗建议（模糊检测、重复检测、异常值检测等）
- **样本增强**：几何变换、颜色抖动、音频增强、文本增强等 30+ 算法
- **数据预览**：缩略图浏览、标签查看、统计信息

### 模型训练

- **目标检测**：YOLOv5 训练（船舶、车辆、人脸等）
- **图像分类**：声纳图像分类（OLTR）
- **时序分析**：传感器时序预测
- **故障诊断**：工业设备故障分类
- **多模态融合**：图像 + 雷达 + AIS 多传感器融合

### 模型评估

- **评估场景**：预定义评估配置
- **指标计算**：mAP、Precision、Recall、F1 等
- **报告导出**：评估报告生成与导出

### 模型导出与部署

- **导出流程**：PyTorch (.pt) → ONNX (.onnx) → RKNN (.rknn)
- **INT8 量化**：校准数据集驱动的量化优化
- **边缘部署**：一键推送模型到 RK3399Pro 设备

### 边缘设备管理

- **设备注册**：自动发现或手动添加边缘设备
- **实时监控**：MQTT 心跳、检测结果回收
- **场景切换**：远程切换推理场景（检测/分类/分割）
- **OTA 更新**：模型热加载、应用远程升级、自动回滚

## 架构概览

```
┌─────────────────────────────────────────────────────────┐
│                    QML 用户界面                          │
│  数据集页面 │ 清洗页面 │ 增强页面 │ 训练页面 │ 设备页面  │
└───────────────────────┬─────────────────────────────────┘
                        │ Qt signals/slots
┌───────────────────────▼─────────────────────────────────┐
│              BackendService (main.py)                    │
│              QML ↔ Python 桥接层                         │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│              BackendBridge (qt/bridge.py)                │
│              错误归一化 + QML 序列化                      │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│          BackendServiceFacade (service_facade.py)        │
│          依赖注入容器，组装所有服务                        │
├─────────────────────────────────────────────────────────┤
│  Services              │  TaskManager                    │
│  ├─ DatasetService     │  ├─ 任务生命周期管理             │
│  ├─ CleaningService    │  ├─ 进度追踪                    │
│  ├─ GenerationService  │  └─ 取消支持                    │
│  ├─ TrainingService    │                                  │
│  ├─ EvaluationService  │  PluginRunner                    │
│  ├─ AlgorithmService   │  ├─ 插件加载与执行               │
│  ├─ ExportService      │  └─ 参数反射                     │
│  ├─ EdgeService        │                                  │
│  └─ SettingsService    │  MqttBridge                      │
│                        │  └─ 实时数据回收                  │
├─────────────────────────────────────────────────────────┤
│  Repositories (8个)                                     │
│  DatasetRepo │ TaskRepo │ AlgorithmRepo │ SettingsRepo   │
│  LogRepo │ EdgeDeviceRepo │ ModelVersionRepo │ BaseRepo  │
├─────────────────────────────────────────────────────────┤
│  SQLAlchemy ORM → SQLite (data/isg_backend.db)          │
└─────────────────────────────────────────────────────────┘
```

详细架构说明见 [BACKEND_ARCHITECTURE.md](docs/BACKEND_ARCHITECTURE.md)。

## 目录结构

```
training/
├── main.py                 # 应用入口 (BackendService + QML 引擎)
├── requirements.txt        # Python 依赖
├── CLAUDE.md               # 编码规范
├── AGENTS.md               # AI Agent 编码规范
│
├── backend/                # 后端核心
│   ├── database.py         # 数据库引擎与会话工厂
│   ├── models.py           # SQLAlchemy ORM 模型 (27个)
│   ├── enums.py            # 枚举定义 (TaskStatus/TaskType/AlgorithmCategory)
│   ├── errors.py           # 异常层次 (BackendError/ValidationError/NotFoundError)
│   ├── dtos.py             # 数据传输对象
│   ├── service_facade.py   # 依赖注入容器
│   ├── task_manager.py     # 后台任务管理器
│   ├── edge_client.py      # 边缘设备通信客户端
│   ├── mqtt_bridge.py      # MQTT 实时数据桥接
│   ├── seed_data.py        # 默认算法注册数据 (50+ 算法)
│   │
│   ├── repositories/       # 数据访问层
│   │   ├── base.py         #   RepositoryBase 基类
│   │   ├── dataset_repository.py
│   │   ├── task_repository.py
│   │   ├── algorithm_repository.py
│   │   ├── settings_repository.py
│   │   ├── log_repository.py
│   │   ├── edge_device_repository.py
│   │   └── model_version_repository.py
│   │
│   ├── services/           # 业务逻辑层
│   │   ├── base.py         #   ServiceBase 基类
│   │   ├── dataset_service.py      # 数据集导入/导出/清理
│   │   ├── cleaning_service.py     # 数据清洗编排
│   │   ├── generation_service.py   # 样本生成/增强
│   │   ├── training_service.py     # 模型训练
│   │   ├── evaluation_service.py   # 模型评估
│   │   ├── algorithm_service.py    # 算法插件管理
│   │   ├── export_service.py       # 模型导出 (ONNX/RKNN)
│   │   ├── edge_service.py         # 边缘设备 OTA
│   │   └── settings_service.py     # 应用设置
│   │
│   ├── plugins/            # 插件系统
│   │   ├── runner.py       #   PluginRunner (加载/执行/反射)
│   │   ├── contract.py     #   插件协议定义
│   │   ├── reflector.py    #   参数反射
│   │   └── builtin/        #   内置插件
│   │
│   ├── qt/                 # QML 桥接
│   │   └── bridge.py       #   BackendBridge (80+ 方法)
│   │
│   ├── storage/            # 存储工具
│   │   ├── paths.py        #   BackendPaths (目录管理)
│   │   └── file_indexer.py #   FileIndexer (文件索引/去重)
│   │
│   └── integrations/       # 外部集成
│       └── agl_generation.py
│
├── plugins/                # 算法插件目录
│   ├── detection/          #   目标检测训练
│   ├── cleaning/           #   数据清洗 (图像/音频/表格/文本)
│   ├── generation/         #   数据增强 (图像/音频/文本)
│   ├── evaluation/         #   模型评估
│   ├── training/           #   训练插件 (检测/分类/分割/时序)
│   ├── timeseries/         #   时序分析
│   ├── fault_diagnosis/    #   工业故障诊断
│   ├── export/             #   模型导出
│   ├── user/               #   用户自定义插件
│   └── multimodal/         #   多模态融合
│
├── ui/                     # QML 界面
├── core/                   # 核心逻辑 (旧版兼容)
├── utils/                  # 共享工具
├── settings/               # 应用设置
├── scripts/                # 模型导出 + 部署脚本
│   ├── export_to_rknn1.py  #   RKNN 模型导出工具
│   ├── deploy_to_edge.sh   #   边缘设备部署脚本
│   └── parallel_download.py #  多线程下载器
│
├── docs/                   # 文档
│   ├── ALGORITHM_PLUGIN_SPEC.md  # 算法插件开发规范
│   ├── BACKEND_ARCHITECTURE.md   # 后端架构文档
│   └── datasets/                 # 数据集文档 (7个)
│
├── data/                   # 运行时数据 (gitignore)
│   ├── datasets/           #   数据集文件
│   ├── tasks/              #   任务输出
│   ├── reports/            #   评估报告
│   └── isg_backend.db      #   SQLite 数据库
│
└── tests/                  # 测试
    ├── test_backend_infrastructure.py
    ├── test_backend_dataset_service.py
    ├── test_backend_algorithm_service.py
    ├── test_backend_task_and_cleaning.py
    ├── test_backend_generation_service.py
    ├── test_backend_evaluation_service.py
    ├── test_backend_chain.py
    ├── test_backend_compat.py
    ├── test_backend_agl_integration.py
    ├── test_desktop_backend_contract.py
    ├── test_ui_guidance.py
    └── test_reflect_plugin.py
```

## 插件系统

ISG-mian 采用插件化架构，所有算法（清洗、增强、训练、评估）均以 Python 模块形式注册。

### 插件开发

详见 [ALGORITHM_PLUGIN_SPEC.md](docs/ALGORITHM_PLUGIN_SPEC.md)，核心要点：

1. 创建 `.py` 文件，声明 `PARAMETERS` 列表和 `run(payload, context)` 入口函数
2. 系统自动反射参数列表，在 UI 中生成配置控件
3. 插件可放置在 `plugins/user/` 目录或通过 `module_path` 引用

### 快速示例

```python
# plugins/user/my_cleaner.py
PARAMETERS = [
    {"name": "threshold", "type": "float", "label": "阈值",
     "default": 0.5, "min": 0.0, "max": 1.0},
]

def run(payload, context):
    params = payload.get("parameters", {})
    threshold = float(params.get("threshold", 0.5))
    # ... 执行清洗逻辑 ...
    return {"ok": True, "suggestions": [...]}
```

## 模型导出与部署

### 导出 RKNN 模型

```bash
cd scripts
python export_to_rknn1.py \
    --model_path ../data/models/yolov5n.pt \
    --model_type yolov5 \
    --output_path ../data/models/yolov5n.rknn \
    --do_quantization \
    --dataset ../data/datasets/calibration_images
```

### 部署到边缘设备

```bash
# 方式 1: 使用部署脚本
./deploy_to_edge.sh 192.168.1.50 ../data/models/yolov5n.rknn vehicle

# 方式 2: 通过 ISG-mian GUI
# 设备管理页面 → 选择设备 → 推送模型
```

## 测试

```bash
# 运行全部测试
cd training
python -m pytest tests/ -v

# 运行单个测试
python -m pytest tests/test_backend_dataset_service.py -v

# 运行并查看覆盖率
python -m pytest tests/ --cov=backend --cov-report=html
```

## 配置

应用配置存储在 SQLite 数据库的 `app_settings` 表中，通过 GUI 设置页面管理。

关键配置项：
- **数据目录**：数据集、任务输出、报告的存储路径
- **MQTT Broker**：边缘设备通信的 Broker 地址和端口
- **模型导出**：RKNN-Toolkit1 路径、量化参数

## 常见问题

### 启动报错 "No module named 'PySide6"

```bash
pip install PySide6>=6.5
```

### 数据库损坏

删除 `data/isg_backend.db` 后重启，系统会自动重建。

### RKNN 导出失败

确保已安装 RKNN-Toolkit1：
```bash
pip install rknn-toolkit2  # RK3588
# 或
pip install rknn-toolkit   # RK3399Pro (Python 3.6 环境)
```

### 边缘设备连接失败

1. 检查网络连通性：`ping 192.168.1.50`
2. 检查 MQTT Broker：`mosquitto_sub -h 192.168.1.50 -t 'edge/#' -v`
3. 检查 gRPC 服务：`grpcurl -plaintext 192.168.1.50:50051 list`
