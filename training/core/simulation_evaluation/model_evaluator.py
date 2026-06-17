import os
import threading
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any

from ..database import SessionLocal
from ..models.evaluation_task import EvaluationTask
from ..models.evaluation_result import EvaluationResult
from .performance_analyzer import PerformanceAnalyzer

class ModelEvaluator:
    def __init__(self, db: Session, session_factory=SessionLocal):
        self.db = db
        self.session_factory = session_factory
        self.performance_analyzer = PerformanceAnalyzer()

    def create_evaluation_task(self, scenario: str, baseline_dataset_id: int, 
                             enhanced_dataset_id: int, model: str) -> EvaluationTask:
        """创建评估任务"""
        task = EvaluationTask(
            scenario=scenario,
            baseline_dataset_id=baseline_dataset_id,
            enhanced_dataset_id=enhanced_dataset_id,
            model=model
        )
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    def get_evaluation_tasks(self, status: Optional[str] = None) -> Dict[str, Any]:
        """获取评估任务列表"""
        query = self.db.query(EvaluationTask)
        if status:
            query = query.filter(EvaluationTask.status == status)
        
        total = query.count()
        items = query.all()
        
        # 转换为字典列表
        items_list = []
        for item in items:
            items_list.append({
                "id": item.id,
                "scenario": item.scenario,
                "model": item.model,
                "status": item.status,
                "progress": item.progress,
                "created_at": item.created_at
            })
        
        return {"total": total, "items": items_list}

    def get_evaluation_task(self, task_id: int) -> Optional[EvaluationTask]:
        """获取评估任务详情"""
        return self.db.query(EvaluationTask).filter(EvaluationTask.id == task_id).first()

    def start_task(self, task_id: int, background: bool = True) -> Dict[str, str]:
        task = self.get_evaluation_task(task_id)
        if not task:
            return {"status": "error", "message": "evaluation task not found"}
        if task.status in ["training", "evaluating", "running"]:
            return {"status": "error", "message": "evaluation task is already running"}

        if background:
            thread = threading.Thread(target=self._process_in_new_session, args=(task_id,), daemon=True)
            thread.start()
            return {"status": "success", "message": "evaluation task started"}

        return self.process_evaluation_task(task_id)

    def _process_in_new_session(self, task_id: int):
        db = self.session_factory()
        try:
            ModelEvaluator(db, session_factory=self.session_factory).process_evaluation_task(task_id)
        finally:
            db.close()

    def stop_evaluation_task(self, task_id: int) -> Dict[str, str]:
        """停止评估任务"""
        task = self.get_evaluation_task(task_id)
        if not task:
            return {"status": "error", "message": "任务不存在"}
        
        task.status = "stopped"
        self.db.commit()
        return {"status": "success", "message": "任务已停止"}

    def process_evaluation_task(self, task_id: int) -> Dict[str, Any]:
        """处理评估任务"""
        task = self.get_evaluation_task(task_id)
        if not task:
            return {"status": "error", "message": "evaluation task not found"}
        
        task.status = "training"
        self.db.commit()
        
        try:
            # 训练基准模型
            task.progress = 25
            self.db.commit()
            baseline_model_path = self.performance_analyzer.train_model(
                task.baseline_dataset_id, task.model, {}
            )
            
            # 训练增强模型
            task.progress = 50
            self.db.commit()
            enhanced_model_path = self.performance_analyzer.train_model(
                task.enhanced_dataset_id, task.model, {}
            )
            
            # 评估模型
            task.status = "evaluating"
            task.progress = 75
            self.db.commit()
            
            # 评估基准模型
            baseline_metrics = self.performance_analyzer.evaluate_model(
                baseline_model_path, task.baseline_dataset_id
            )
            
            # 评估增强模型
            enhanced_metrics = self.performance_analyzer.evaluate_model(
                enhanced_model_path, task.enhanced_dataset_id
            )
            
            # 保存评估结果
            baseline_result = EvaluationResult(
                task_id=task.id,
                model_type="baseline",
                metrics=baseline_metrics
            )
            self.db.add(baseline_result)
            
            enhanced_result = EvaluationResult(
                task_id=task.id,
                model_type="enhanced",
                metrics=enhanced_metrics
            )
            self.db.add(enhanced_result)
            
            task.status = "completed"
            task.progress = 100
            self.db.commit()
            return {"status": "success", "message": "evaluation task completed"}
        except Exception as e:
            task.status = "failed"
            self.db.commit()
            return {"status": "error", "message": str(e)}

    def get_evaluation_results(self, task_id: int) -> Dict[str, Any]:
        """获取评估结果"""
        results = self.db.query(EvaluationResult).filter(
            EvaluationResult.task_id == task_id
        ).all()
        
        result_dict = {}
        for result in results:
            result_dict[result.model_type] = result.metrics
        
        return result_dict

    def export_evaluation_report(self, task_id: int, format: str = "pdf") -> Optional[str]:
        """导出评估报告"""
        try:
            # 获取评估结果
            results = self.get_evaluation_results(task_id)
            
            # 生成报告
            report_content = self.performance_analyzer.generate_comparison_report(
                results.get("baseline", {}),
                results.get("enhanced", {})
            )
            
            # 保存报告
            output_dir = "./reports"
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, f"evaluation_report_{task_id}.{format}")
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(report_content)
            
            return output_path
        except Exception:
            return None

    def get_scenarios(self) -> List[Dict[str, Any]]:
        """获取可用场景列表"""
        scenarios = [
            {
                "name": "水下目标检测与识别",
                "description": "用于水下目标的检测与识别任务"
            },
            {
                "name": "自动驾驶场景理解",
                "description": "用于自动驾驶系统的场景理解任务"
            },
            {
                "name": "医疗影像分析",
                "description": "用于医疗影像的分析和诊断任务"
            },
            {
                "name": "自然语言处理",
                "description": "用于文本分类、情感分析等自然语言处理任务"
            },
            {
                "name": "音频识别",
                "description": "用于语音识别、声纹识别等音频处理任务"
            }
        ]
        return scenarios

    def get_scenario(self, scenario_name: str) -> Optional[Dict[str, Any]]:
        """获取场景详情"""
        scenarios = self.get_scenarios()
        for scenario in scenarios:
            if scenario["name"] == scenario_name:
                # 添加场景支持的模型
                scenario["models"] = self._get_scenario_models(scenario_name)
                return scenario
        return None

    def _get_scenario_models(self, scenario_name: str) -> List[str]:
        """获取场景支持的模型"""
        model_mapping = {
            "水下目标检测与识别": ["YOLOv8s-Marine", "Faster-RCNN-Base", "RetinaNet-Marine"],
            "自动驾驶场景理解": ["YOLOv8x", "EfficientDet", "DETR"],
            "医疗影像分析": ["ResNet50-Med", "UNet-Med", "EfficientNet-Med"],
            "自然语言处理": ["BERT-Base", "RoBERTa-Base", "DistilBERT"],
            "音频识别": ["Wav2Vec2-Base", "Hubert-Base", "Whisper-Small"]
        }
        return model_mapping.get(scenario_name, [])
