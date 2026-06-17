from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from datetime import datetime
import os
import time
import random
import threading

from ..models.evaluation_task import EvaluationTask
from ..models.evaluation_result import EvaluationResult

class ModelEvaluator:
    """模型评估器，管理评估任务"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create_evaluation_task(
        self,
        scenario: str,
        baseline_dataset_id: int,
        enhanced_dataset_id: int,
        model: str
    ) -> EvaluationTask:
        """创建评估任务"""
        task = EvaluationTask(
            scenario=scenario,
            baseline_dataset_id=baseline_dataset_id,
            enhanced_dataset_id=enhanced_dataset_id,
            model=model,
            status="created",
            progress=0.0
        )
        
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        
        return task
    
    def get_evaluation_tasks(
        self,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """获取评估任务列表"""
        query = self.db.query(EvaluationTask)
        
        if status:
            query = query.filter(EvaluationTask.status == status)
        
        tasks = query.order_by(EvaluationTask.created_at.desc()).all()
        
        return [
            {
                "id": task.id,
                "scenario": task.scenario,
                "baseline_dataset_id": task.baseline_dataset_id,
                "enhanced_dataset_id": task.enhanced_dataset_id,
                "model": task.model,
                "status": task.status,
                "progress": task.progress,
                "created_at": task.created_at.strftime("%Y-%m-%d %H:%M:%S") if task.created_at else "",
                "updated_at": task.updated_at.strftime("%Y-%m-%d %H:%M:%S") if task.updated_at else ""
            }
            for task in tasks
        ]
    
    def get_evaluation_results(self, task_id: int) -> Dict[str, Any]:
        """获取评估结果"""
        task = self.db.query(EvaluationTask).filter(EvaluationTask.id == task_id).first()
        if not task:
            return {"error": "任务不存在"}
        
        results = self.db.query(EvaluationResult).filter(
            EvaluationResult.task_id == task_id
        ).all()
        
        return {
            "task_id": task_id,
            "scenario": task.scenario,
            "model": task.model,
            "status": task.status,
            "results": [
                {
                    "id": result.id,
                    "model_type": result.model_type,
                    "metrics": result.metrics
                }
                for result in results
            ]
        }
    
    def start_task(self, task_id: int) -> Dict[str, Any]:
        """开始评估任务"""
        task = self.db.query(EvaluationTask).filter(EvaluationTask.id == task_id).first()
        if not task:
            return {"status": "error", "message": "任务不存在"}
        
        if task.status == "running":
            return {"status": "error", "message": "任务正在运行中"}
        
        task.status = "running"
        self.db.commit()
        
        # 启动异步任务来执行评估
        thread = threading.Thread(target=self._simulate_evaluation, args=(task_id,))
        thread.daemon = True
        thread.start()
        
        return {"status": "success", "message": "任务已启动"}
    
    def _simulate_evaluation(self, task_id: int):
        """模拟评估过程"""
        # 创建新的数据库会话
        from ..database import SessionLocal
        db = SessionLocal()
        
        try:
            task = db.query(EvaluationTask).filter(EvaluationTask.id == task_id).first()
            if not task:
                return
            
            # 模拟评估过程
            for i in range(10):
                task.progress = i * 10
                db.commit()
                time.sleep(0.5)
            
            # 生成基准模型评估结果
            baseline_metrics = {
                "mAP@.5": round(random.uniform(0.60, 0.70), 3),
                "Recall": round(random.uniform(0.65, 0.75), 3),
                "Precision": round(random.uniform(0.70, 0.80), 3),
                "F1-Score": round(random.uniform(0.68, 0.78), 3)
            }
            
            baseline_result = EvaluationResult(
                task_id=task_id,
                model_type="baseline",
                metrics=baseline_metrics
            )
            db.add(baseline_result)
            
            # 生成增强模型评估结果
            enhanced_metrics = {
                "mAP@.5": round(random.uniform(0.80, 0.90), 3),
                "Recall": round(random.uniform(0.82, 0.92), 3),
                "Precision": round(random.uniform(0.85, 0.95), 3),
                "F1-Score": round(random.uniform(0.83, 0.93), 3)
            }
            
            enhanced_result = EvaluationResult(
                task_id=task_id,
                model_type="enhanced",
                metrics=enhanced_metrics
            )
            db.add(enhanced_result)
            
            task.status = "completed"
            task.progress = 100
            db.commit()
        finally:
            db.close()
    
    def export_report(self, task_id: int, format: str) -> Dict[str, Any]:
        """导出评估报告"""
        task = self.db.query(EvaluationTask).filter(EvaluationTask.id == task_id).first()
        if not task:
            return {"status": "error", "message": "任务不存在"}
        
        if task.status != "completed":
            return {"status": "error", "message": "任务尚未完成"}
        
        # 生成报告文件路径
        report_dir = "reports"
        os.makedirs(report_dir, exist_ok=True)
        
        filename = f"evaluation_report_{task_id}.{format}"
        filepath = os.path.join(report_dir, filename)
        
        # 获取评估结果
        results = self.db.query(EvaluationResult).filter(
            EvaluationResult.task_id == task_id
        ).all()
        
        # 生成报告内容
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"评估报告 - 任务ID: {task_id}\n")
            f.write(f"场景: {task.scenario}\n")
            f.write(f"模型: {task.model}\n")
            f.write(f"状态: {task.status}\n")
            f.write("\n")
            f.write("评估结果:\n")
            
            for result in results:
                f.write(f"\n{result.model_type.upper()} 模型:\n")
                for metric, value in result.metrics.items():
                    f.write(f"  {metric}: {value}\n")
        
        return {
            "status": "success",
            "message": "报告已导出",
            "filepath": filepath
        }
