# 测试指南

ISG-mian 项目的测试策略、运行方法和测试用例说明。

## 测试概览

本项目包含 Python 后端测试、C++ 推理应用测试，以及边缘端集成测试。

| 测试类型 | 工具 | 覆盖范围 |
|---------|------|---------|
| **后端单元测试** | pytest | 数据库、Repository、Service、Plugin |
| **集成测试** | pytest | 完整工作流（清洗→增强→训练） |
| **QML Contract 测试** | pytest | QML → BackendService 接口契约 |
| **C++ 推理测试** | 手动 | 边缘端本地编译 + 摄像头/文件输入 |

## 测试环境

### 必需工具

```bash
# Python 测试
pip install pytest pytest-cov pytest-asyncio pytest-mock

# C++ 测试
cmake >= 3.13
GCC >= 9.0

# 边缘端测试
RK3399Pro 开发板 或 x86 模拟器
```

### 虚拟环境

```bash
cd training
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install pytest pytest-cov
```

## 运行测试

### 1. 后端基础测试

```bash
cd training

# 运行所有测试
python -m pytest tests/ -v

# 运行特定目录
python -m pytest tests/test_backend_*.py -v

# 显示覆盖率
python -m pytest tests/ --cov=backend --cov-report=html
# 打开 htmlcov/index.html 查看报告
```

### 2. 集成测试

```bash
# 完整的数据清洗→增强流程
python -m pytest tests/test_backend_chain.py::test_full_dataset_workflow -v

# 训练→评估流程
python -m pytest tests/test_backend_chain.py::test_training_evaluation_chain -v
```

### 3. 测试失败重试

```bash
# 失败时自动重试 3 次
python -m pytest tests/ -v --lf --maxfail=3 --reruns 3
```

### 4. 查看 pytest 输出

```bash
# 详细输出
python -m pytest tests/ -v -s

# 只显示错误和失败
python -m pytest tests/ --tb=short
```

## 测试用例说明

### 后端基础设施测试

**test_backend_infrastructure.py** (~2453 行)

- 测试后端包导出
- 验证 TaskStatus 接口契约
- 数据库初始化测试
- BackendServiceFacade 构建测试
- PluginRunner 执行测试

```bash
python -m pytest tests/test_backend_infrastructure.py -v
```

### 数据集服务测试

**test_backend_dataset_service.py** (~404 行)

- Dataset CRUD 操作
- 文件导入（YOLO bbox labels, Sonar OLTR projects）
- 数据集预览功能
- 存储路径处理

```bash
python -m pytest tests/test_backend_dataset_service.py -v
```

### 算法服务测试

**test_backend_algorithm_service.py** (~193 行)

- Algorithm CRUD
- 参数验证
- 算法启用/禁用
- 多模态算法过滤

```bash
python -m pytest tests/test_backend_algorithm_service.py -v
```

### 清洗任务测试

**test_backend_task_and_cleaning.py** (~724 行)

- 清洗任务创建
- 清洗建议生成
- 执行清理操作
- 重复检测
- 图像近重复检测

```bash
python -m pytest tests/test_backend_task_and_cleaning.py -v
```

### 增强任务测试

**test_backend_generation_service.py** (~406 行)

- 增强任务创建
- AGL 算法集成
- 输出持久化
- 标签继承

```bash
python -m pytest tests/test_backend_generation_service.py -v
```

### 评估任务测试

**test_backend_evaluation_service.py** (~259 行)

- 评估场景管理
- 任务执行
- 报告导出
- 多 Agent 仿真

```bash
python -m pytest tests/test_backend_evaluation_service.py -v
```

### 集成流程测试

**test_backend_chain.py**

- 数据清洗→增强→训练→评估完整流程
- 测试跨服务数据流转
- 验证任务依赖关系

```bash
python -m pytest tests/test_backend_chain.py::test_full_dataset_workflow -v
```

### QML Contract 测试

**test_desktop_backend_contract.py** (~389 行)

- QML → BackendService 接口契约测试
- 图标存在检查
- 主题切换测试
- 数据页检查
- 数据暴露标记测试

```bash
python -m pytest tests/test_desktop_backend_contract.py -v
```

### UI 辅助测试

**test_ui_guidance.py** (~187 行)

- 主题单例测试
- 帮助图标测试
- 显示数据标记测试
- 深色色值避免测试

```bash
python -m pytest tests/test_ui_guidance.py -v
```

### 插件反射测试

**test_reflect_plugin.py** (~90 行)

- 插件参数反射测试
- PARAMETERS 列表解析测试

```bash
python -m pytest tests/test_reflect_plugin.py -v
```

## 测试策略

### 单元测试 vs 集成测试

| 类型 | 目的 | 示例 |
|------|------|------|
| 单元测试 | 测试独立函数/方法 | `repository.get_by_id()` |
| 集成测试 | 测试模块间协作 | 从 DatasetService → PluginRunner → 数据库 |

### 测试数据

- 使用 `tempfile` 创建临时数据库
- 所有测试独立运行，互不干扰
- 测试后自动清理临时文件

### Mock 和 Fixture

```python
import pytest
from unittest.mock import Mock, patch

@pytest.fixture
def temporary_session():
    """线程局部临时会话"""
    session = SessionLocal()
    yield session
    session.close()

def test_dataset_crud(temporary_session):
    repo = DatasetRepository(temporary_session)
    dataset = repo.create(name="test", modality="image")
    assert dataset.name == "test"
```

## 边缘端测试

边缘端目前无自动化测试框架，建议手动测试。

### 本地编译测试

```bash
cd edge

# 本地 aarch64 编译（需要交叉编译工具链）
cmake -S . -B build -DCMAKE_TOOLCHAIN_FILE=cmake/aarch64-toolchain.cmake
make -C build -j4

# x86 语法检查
cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug
make -C build -j4
```

### 无摄像头模式（文件输入）

```yaml
# pipeline.yaml
input:
  type: "video_file"
  file_path: "/opt/edge-ai/models/dog_640.jpg"
```

```bash
./build/edge-ai-camera -c /opt/edge-ai/config/pipeline.yaml
```

### MQTT 验证

```bash
# 在另一个终端订阅 MQTT
mosquitto_sub -h 192.168.1.50 -t 'edge/rk3399pro-edge-001/detections' -v

# 检查输出
# 应该收到 JSON 格式的检测结果
```

### gRPC 验证

```bash
# 查询设备状态
grpcurl -plaintext 192.168.1.50:50051 EdgeService/GetStatus \
    -d '{"device_id": "rk3399pro-edge-001"}'

# 期望返回：
# {
#   "status": 0,
#   "device_id": "rk3399pro-edge-001",
#   "scene": "vehicle",
#   "fps": 25.0,
#   "npu_usage": 85.0,
#   ...
# }
```

### 性能测试

```bash
# 在 pipeline.yaml 中启用性能统计
# 编译时添加 RKNN_FLAG_COLLECT_PERF_MASK 标志

# 查看日志中的推理耗时
journalctl -u edge-ai-camera | grep "inference"
```

期望：
- YOLOv5 n: 640×640, FPS ≥ 25
- NPU 利用率 ≥ 80%
- 内存占用 < 500MB

### 回归测试清单

✅ **核心功能**
- [ ] V4L2 摄像头采集正常
- [ ] NPU 推理成功
- [ ] YOLOv5 后处理输出正确
- [ ] SORT 跟踪稳定
- [ ] MQTT 心跳正常
- [ ] MQTT 检测结果格式正确

✅ **错误处理**
- [ ] 摄像头断开时优雅退出
- [ ] NPU 推理失败时重试
- [ ] MQTT 断连时自动重连
- [ ] 模型热加载成功

✅ **性能指标**
- [ ] 推理耗时 < 40ms (YOLOv5n)
- [ ] 端到端延迟 < 200ms
- [ ] CPU4 (A72) 利用率 < 60%
- [ ] 队列未出现长时间积压

✅ **多场景**
- [ ] 场景切换成功
- [ ] 新模型热加载不中断推理
- [ ] 配置参数动态生效

## CI/CD（待实现）

本项目目前没有 CI/CD 配置（无 `.github/workflows/`），建议后续添加：

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  backend-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
      - run: cd training && pip install -r requirements.txt && pip install pytest-cov
      - run: cd training && python -m pytest tests/ --cov=backend --fail-under=80

  build-edge:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Build edge
        run: cd edge && cmake -S . -B build && make -C build -j4
```

## 常见问题

### 测试失败："Database connection error"

确保测试前创建了虚拟环境：
```bash
source training/.venv/bin/activate
```

### 测试数据太多，运行太慢

```bash
# 只运行数据库相关测试
python -m pytest tests/test_backend_dataset_service.py tests/test_backend_task_and_cleaning.py -v
```

### C++ 编译失败

```bash
# 检查 CMake 版本
cmake --version

# 检查工具链
ls cmake/*

# 尝试重新配置
rm -rf build && mkdir build && cmake -S . -B build
```

### 边缘端测试无输出

检查配置文件路径是否正确：
```bash
./build/edge-ai-camera -c /opt/edge-ai/config/pipeline.yaml
```

或使用命令行覆盖参数测试早期阶段：
```bash
./build/edge-ai-camera -c pipeline.yaml -s vehicle
```
