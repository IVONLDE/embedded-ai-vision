from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from .database import Base
from .enums import TaskStatus


class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    modality = Column(String(50), nullable=False)
    description = Column(Text, default="")
    status = Column(String(50), default="draft", nullable=False, index=True)
    parent_dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=True, index=True)
    storage_path = Column(String(500), nullable=False)
    total_samples = Column(Integer, default=0, nullable=False)
    valid_samples = Column(Integer, default=0, nullable=False)
    invalid_samples = Column(Integer, default=0, nullable=False)
    generated_samples = Column(Integer, default=0, nullable=False)
    size_bytes = Column(BigInteger, default=0, nullable=False)
    tags_json = Column(JSON, default=list, nullable=False)
    extra_json = Column(JSON, default=dict, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Sample(Base):
    __tablename__ = "samples"

    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False, index=True)
    source_sample_id = Column(Integer, ForeignKey("samples.id"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    modality = Column(String(50), nullable=False, index=True)
    file_path = Column(String(500), nullable=False)
    relative_path = Column(String(500), nullable=True)
    sha256 = Column(String(128), nullable=True, index=True)
    mime_type = Column(String(100), nullable=True)
    extension = Column(String(32), nullable=True)
    size_bytes = Column(BigInteger, default=0, nullable=False)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    status = Column(String(50), default="raw", nullable=False, index=True)
    metadata_json = Column(JSON, default=dict, nullable=False)
    labels_json = Column(JSON, default=list, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class DatasetStatistics(Base):
    __tablename__ = "dataset_statistics"

    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False, unique=True, index=True)
    total_samples = Column(Integer, default=0, nullable=False)
    valid_samples = Column(Integer, default=0, nullable=False)
    invalid_samples = Column(Integer, default=0, nullable=False)
    generated_samples = Column(Integer, default=0, nullable=False)
    size_bytes = Column(BigInteger, default=0, nullable=False)
    modality_breakdown_json = Column(JSON, default=dict, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Algorithm(Base):
    __tablename__ = "algorithms"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(120), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False)
    category = Column(String(50), nullable=False, index=True)
    modality = Column(String(50), nullable=False, index=True)
    status = Column(String(50), default="enabled", nullable=False, index=True)
    entry_type = Column(String(50), nullable=False)
    module_path = Column(String(255), nullable=True)
    callable_name = Column(String(120), nullable=True)
    script_path = Column(String(500), nullable=True)
    executable_path = Column(String(500), nullable=True)
    version = Column(String(50), default="1.0.0", nullable=False)
    input_contract_json = Column(JSON, default=dict, nullable=False)
    output_contract_json = Column(JSON, default=dict, nullable=False)
    validation_rules_json = Column(JSON, default=dict, nullable=False)
    tags_json = Column(JSON, default=list, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class AlgorithmParameter(Base):
    __tablename__ = "algorithm_parameters"

    id = Column(Integer, primary_key=True, index=True)
    algorithm_id = Column(Integer, ForeignKey("algorithms.id"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    label = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False)
    required = Column(Boolean, default=False, nullable=False)
    default_value = Column(JSON, nullable=True)
    min_value = Column(Float, nullable=True)
    max_value = Column(Float, nullable=True)
    options_json = Column(JSON, default=list, nullable=False)
    description = Column(Text, default="", nullable=False)
    order_index = Column(Integer, default=0, nullable=False)


class AlgorithmBinding(Base):
    """训练算法与评估算法的绑定关系。一个训练算法最多绑定一个评估算法。"""
    __tablename__ = "algorithm_bindings"

    id = Column(Integer, primary_key=True, index=True)
    training_algorithm_id = Column(Integer, ForeignKey("algorithms.id"), nullable=False, unique=True, index=True)
    evaluation_algorithm_id = Column(Integer, ForeignKey("algorithms.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_type = Column(String(50), nullable=False, index=True)
    status = Column(String(50), default=TaskStatus.PENDING.value, nullable=False, index=True)
    title = Column(String(255), nullable=False)
    source_dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=True, index=True)
    target_dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=True, index=True)
    algorithm_id = Column(Integer, ForeignKey("algorithms.id"), nullable=True)
    scenario_id = Column(Integer, ForeignKey("evaluation_scenarios.id"), nullable=True)
    progress = Column(Float, default=0.0, nullable=False)
    progress_message = Column(String(255), default="", nullable=False)
    parameters_json = Column(JSON, default=dict, nullable=False)
    payload_json = Column(JSON, default=dict, nullable=False)
    result_json = Column(JSON, default=dict, nullable=False)
    error_code = Column(String(120), nullable=True)
    error_message = Column(Text, nullable=True)
    output_dir = Column(String(500), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class TaskLog(Base):
    __tablename__ = "task_logs"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, index=True)
    level = Column(String(20), nullable=False, index=True)
    message = Column(Text, nullable=False)
    payload_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CleaningSuggestion(Base):
    __tablename__ = "cleaning_suggestions"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, index=True)
    sample_id = Column(Integer, ForeignKey("samples.id"), nullable=False, index=True)
    algorithm_id = Column(Integer, ForeignKey("algorithms.id"), nullable=True)
    issue_type = Column(String(100), nullable=False, index=True)
    suggested_action = Column(String(50), nullable=False)
    status = Column(String(50), default="pending", nullable=False, index=True)
    confidence = Column(Float, default=0.0, nullable=False)
    message = Column(Text, default="", nullable=False)
    details_json = Column(JSON, default=dict, nullable=False)
    output_sample_id = Column(Integer, ForeignKey("samples.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class GenerationOutput(Base):
    __tablename__ = "generation_outputs"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, index=True)
    source_sample_id = Column(Integer, ForeignKey("samples.id"), nullable=True)
    output_sample_id = Column(Integer, ForeignKey("samples.id"), nullable=True, index=True)
    algorithm_id = Column(Integer, ForeignKey("algorithms.id"), nullable=True)
    status = Column(String(50), default="created", nullable=False, index=True)
    metadata_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EvaluationScenario(Base):
    __tablename__ = "evaluation_scenarios"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(120), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False)
    modality = Column(String(50), nullable=False)
    description = Column(Text, default="", nullable=False)
    baseline_models_json = Column(JSON, default=list, nullable=False)
    metric_schema_json = Column(JSON, default=list, nullable=False)
    status = Column(String(50), default="seeded", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, index=True)
    scenario_id = Column(Integer, ForeignKey("evaluation_scenarios.id"), nullable=True)
    baseline_dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False)
    target_dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False)
    algorithm_id = Column(Integer, ForeignKey("algorithms.id"), nullable=True)
    model_name = Column(String(255), nullable=False)
    metrics_json = Column(JSON, default=dict, nullable=False)
    summary = Column(Text, default="", nullable=False)
    artifacts_json = Column(JSON, default=list, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AppSetting(Base):
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(120), nullable=False, unique=True, index=True)
    value_json = Column(JSON, nullable=False)
    description = Column(Text, default="", nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class OperationLog(Base):
    __tablename__ = "operation_logs"

    id = Column(Integer, primary_key=True, index=True)
    level = Column(String(20), nullable=False, index=True)
    action = Column(String(120), nullable=False)
    resource_type = Column(String(50), nullable=True)
    resource_id = Column(String(120), nullable=True)
    message = Column(Text, nullable=False)
    payload_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SystemLog(Base):
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, index=True)
    level = Column(String(20), nullable=False, index=True)
    action = Column(String(120), nullable=False)
    resource_type = Column(String(50), nullable=True)
    resource_id = Column(String(120), nullable=True)
    message = Column(Text, nullable=False)
    payload_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ── 边缘设备管理 (新增) ──────────────────────────────────

class EdgeDevice(Base):
    """边缘推理设备"""
    __tablename__ = "edge_devices"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String(120), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False)
    host = Column(String(255), nullable=False)          # IP 地址
    grpc_port = Column(Integer, default=50051)
    status = Column(String(50), default="offline", nullable=False, index=True)
    scene = Column(String(50), default="", nullable=False)
    model_version = Column(String(50), default="")
    fps = Column(Float, default=0.0)
    npu_usage = Column(Float, default=0.0)
    cpu_temp = Column(Float, default=0.0)
    memory_bytes = Column(BigInteger, default=0)
    uptime_sec = Column(Integer, default=0)
    frame_count = Column(Integer, default=0)
    avg_inference_ms = Column(Float, default=0.0)
    last_heartbeat = Column(DateTime(timezone=True), nullable=True)
    tags_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class ModelVersion(Base):
    """模型版本管理"""
    __tablename__ = "model_versions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    version = Column(String(50), nullable=False)
    model_type = Column(String(50), nullable=False, index=True)  # yolov5 / osnet / classifier
    scene = Column(String(50), nullable=False)                   # face / body / vehicle / defect
    file_path = Column(String(500), nullable=False)              # .rknn 文件路径
    onnx_path = Column(String(500), nullable=True)               # 源 ONNX 路径
    pt_path = Column(String(500), nullable=True)                 # 源 PyTorch 路径
    sha256 = Column(String(128), nullable=True)
    file_size = Column(BigInteger, default=0)
    quantization = Column(String(20), default="fp16")            # fp16 / int8
    accuracy_metric = Column(Float, nullable=True)                # mAP / F1
    status = Column(String(50), default="active", nullable=False, index=True)
    deployed_devices_json = Column(JSON, default=list, nullable=False)
    notes = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
