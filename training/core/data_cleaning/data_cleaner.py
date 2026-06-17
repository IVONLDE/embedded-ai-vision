import os
import threading
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any

from ..database import SessionLocal
from ..models.cleaning_task import CleaningTask
from ..models.cleaning_suggestion import CleaningSuggestion
from ..models.dataset import Dataset
from ..models.sample import Sample
from .multi_modal_processor import MultiModalProcessor

class DataCleaner:
    def __init__(self, db: Session, session_factory=SessionLocal):
        self.db = db
        self.session_factory = session_factory
        self.multi_modal_processor = MultiModalProcessor()

    def create_cleaning_task(self, dataset_id: int, modality: str, parameters: Dict[str, Any]) -> CleaningTask:
        """创建清洗任务"""
        if dataset_id is None:
            raise ValueError("dataset_id 不能为空")
        if not modality:
            raise ValueError("modality 不能为空")
        if parameters is None:
            parameters = {}

        task = CleaningTask(
            dataset_id=dataset_id,
            modality=modality,
            parameters=parameters
        )
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    def get_cleaning_tasks(self, dataset_id: Optional[int] = None, status: Optional[str] = None) -> Dict[str, Any]:
        """获取清洗任务列表"""
        query = self.db.query(CleaningTask)
        if dataset_id:
            query = query.filter(CleaningTask.dataset_id == dataset_id)
        if status:
            query = query.filter(CleaningTask.status == status)
        
        total = query.count()
        items = query.order_by(CleaningTask.created_at.desc()).all()
        
        # 转换为字典列表
        items_list = []
        for item in items:
            items_list.append({
                "id": item.id,
                "dataset_id": item.dataset_id,
                "modality": item.modality,
                "status": item.status,
                "progress": item.progress,
                "created_at": item.created_at
            })
        
        return {"total": total, "items": items_list}

    def get_cleaning_task(self, task_id: int) -> Optional[CleaningTask]:
        """获取清洗任务详情"""
        return self.db.query(CleaningTask).filter(CleaningTask.id == task_id).first()

    def start_task(self, task_id: int, background: bool = True) -> Dict[str, str]:
        task = self.get_cleaning_task(task_id)
        if not task:
            return {"status": "error", "message": "cleaning task not found"}
        if task.status == "running":
            return {"status": "error", "message": "cleaning task is already running"}

        if background:
            thread = threading.Thread(target=self._process_in_new_session, args=(task_id,), daemon=True)
            thread.start()
            return {"status": "success", "message": "cleaning task started"}

        return self.process_cleaning_task(task_id)

    def _process_in_new_session(self, task_id: int):
        db = self.session_factory()
        try:
            DataCleaner(db, session_factory=self.session_factory).process_cleaning_task(task_id)
        finally:
            db.close()

    def stop_cleaning_task(self, task_id: int) -> Dict[str, str]:
        """停止清洗任务"""
        task = self.get_cleaning_task(task_id)
        if not task:
            return {"status": "error", "message": "任务不存在"}
        
        task.status = "stopped"
        self.db.commit()
        return {"status": "success", "message": "任务已停止"}

    def process_cleaning_task(self, task_id: int) -> Dict[str, Any]:
        """处理清洗任务"""
        task = self.get_cleaning_task(task_id)
        if not task:
            return {"status": "error", "message": "cleaning task not found"}
        
        task.status = "running"
        self.db.commit()
        
        try:
            normalized = self._normalize_parameters(task.modality, task.parameters or {})
            # 获取数据集中的样本
            samples = self.db.query(Sample).filter(
                Sample.dataset_id == task.dataset_id,
                Sample.type == task.modality,
                Sample.status != "deleted"
            ).all()
            
            total_samples = len(samples)
            processed_samples = 0

            if total_samples == 0:
                task.status = "completed"
                task.progress = 100.0
                self.db.commit()
                return {"status": "success", "message": "cleaning task completed", "processed_count": 0}

            duplicate_sample_ids = set()
            if task.modality == "image" and normalized.get("deduplicate", False):
                duplicate_sample_ids = set(self._detect_image_duplicates(samples, normalized.get("deduplicate_params", {})))
                for dup_id in duplicate_sample_ids:
                    suggestion = CleaningSuggestion(
                        task_id=task.id,
                        sample_id=dup_id,
                        suggestion="去重",
                        confidence=1.0
                    )
                    self.db.add(suggestion)
                self.db.commit()
            
            for sample in samples:
                if sample.id in duplicate_sample_ids:
                    processed_samples += 1
                    task.progress = (processed_samples / total_samples) * 100
                    if processed_samples % 20 == 0:
                        self.db.commit()
                    continue

                # 检测质量问题
                issues = self.multi_modal_processor.detect_quality_issues(
                    sample.path, sample.type, normalized
                )
                
                # 生成清洗建议
                for issue in issues:
                    suggestion = CleaningSuggestion(
                        task_id=task.id,
                        sample_id=sample.id,
                        suggestion=issue["suggestion"],
                        confidence=issue["confidence"]
                    )
                    self.db.add(suggestion)
                
                processed_samples += 1
                task.progress = (processed_samples / total_samples) * 100
                self.db.commit()
            
            task.status = "completed"
            task.progress = 100.0
            self.db.commit()
            return {
                "status": "success",
                "message": "cleaning task completed",
                "processed_count": processed_samples,
            }
        except Exception as e:
            task.status = "failed"
            self.db.commit()
            return {"status": "error", "message": str(e)}

    def get_cleaning_suggestions(self, task_id: int, status: Optional[str] = None, 
                                page: int = 1, page_size: int = 10) -> Dict[str, Any]:
        """获取清洗建议列表"""
        query = self.db.query(CleaningSuggestion).filter(
            CleaningSuggestion.task_id == task_id
        )
        if status:
            query = query.filter(CleaningSuggestion.status == status)
        
        total = query.count()
        items = query.order_by(CleaningSuggestion.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
        
        # 转换为字典列表
        items_list = []
        for item in items:
            sample = self.db.query(Sample).filter(Sample.id == item.sample_id).first()
            items_list.append({
                "id": item.id,
                "sample_id": item.sample_id,
                "sample_name": sample.name if sample else f"sample_{item.sample_id}",
                "suggestion": item.suggestion,
                "confidence": item.confidence,
                "status": item.status,
                "created_at": item.created_at
            })
        
        return {"total": total, "items": items_list}

    def approve_cleaning_suggestion(self, suggestion_id: int, action: str) -> Dict[str, str]:
        """审批清洗建议"""
        suggestion = self.db.query(CleaningSuggestion).filter(
            CleaningSuggestion.id == suggestion_id
        ).first()
        
        if not suggestion:
            return {"status": "error", "message": "建议不存在"}
        
        if action not in ["approve", "reject"]:
            return {"status": "error", "message": "无效的操作"}
        
        suggestion.status = "approved" if action == "approve" else "rejected"
        
        # 如果批准，执行清洗操作
        if action == "approve":
            sample = self.db.query(Sample).filter(
                Sample.id == suggestion.sample_id
            ).first()
            if sample:
                # 根据建议类型执行清洗
                if suggestion.suggestion == "去模糊":
                    self.multi_modal_processor.clean_image(sample.path, {"deblur": True})
                elif suggestion.suggestion == "去重":
                    # 处理重复样本
                    dataset_id = sample.dataset_id
                    try:
                        if os.path.exists(sample.path):
                            os.remove(sample.path)
                    except Exception:
                        pass
                    sample.status = "deleted"
                    self.db.commit()
                    self._update_dataset_stats(dataset_id)
                    return {"status": "success", "message": "重复样本已标记删除"}
                else:
                    sample.status = "cleaned"
        
        self.db.commit()
        return {"status": "success", "message": "建议已审批"}

    def batch_approve_cleaning_suggestions(self, suggestion_ids: List[int], action: str) -> Dict[str, Any]:
        """批量审批清洗建议"""
        if action not in ["approve", "reject"]:
            return {"status": "error", "message": "无效的操作"}
        
        approved_count = 0
        touched_datasets = set()
        for suggestion_id in suggestion_ids:
            suggestion = self.db.query(CleaningSuggestion).filter(
                CleaningSuggestion.id == suggestion_id
            ).first()
            if suggestion:
                suggestion.status = "approved" if action == "approve" else "rejected"
                
                # 如果批准，执行清洗操作
                if action == "approve":
                    sample = self.db.query(Sample).filter(
                        Sample.id == suggestion.sample_id
                    ).first()
                    if sample:
                        # 根据建议类型执行清洗
                        if suggestion.suggestion == "去模糊":
                            self.multi_modal_processor.clean_image(sample.path, {"deblur": True})
                        elif suggestion.suggestion == "去重":
                            # 处理重复样本
                            try:
                                if os.path.exists(sample.path):
                                    os.remove(sample.path)
                            except Exception:
                                pass
                            touched_datasets.add(sample.dataset_id)
                            sample.status = "deleted"
                        else:
                            sample.status = "cleaned"
                approved_count += 1
        
        self.db.commit()
        for dataset_id in touched_datasets:
            self._update_dataset_stats(dataset_id)
        return {"status": "success", "approved_count": approved_count}

    def _detect_image_duplicates(self, samples: List[Sample], params: Dict[str, Any]) -> List[int]:
        threshold = 0
        try:
            threshold = int(params.get("hamming_threshold", 0))
        except Exception:
            threshold = 0
        if threshold < 0:
            threshold = 0
        if threshold > 16:
            threshold = 16

        hashes: Dict[str, int] = {}
        hash_list: List[str] = []
        duplicates: List[int] = []
        for sample in samples:
            h = self.multi_modal_processor.compute_image_ahash(sample.path)
            if not h:
                continue
            if threshold == 0:
                if h in hashes:
                    duplicates.append(sample.id)
                else:
                    hashes[h] = sample.id
                continue

            if len(hash_list) > 5000:
                if h in hashes:
                    duplicates.append(sample.id)
                else:
                    hashes[h] = sample.id
                    hash_list.append(h)
                continue

            is_dup = False
            for prev in hash_list:
                if self.multi_modal_processor.hamming_distance_hex64(h, prev) <= threshold:
                    is_dup = True
                    break
            if is_dup:
                duplicates.append(sample.id)
            else:
                hashes[h] = sample.id
                hash_list.append(h)
        return duplicates

    def _update_dataset_stats(self, dataset_id: int):
        dataset = self.db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not dataset:
            return
        samples = self.db.query(Sample).filter(Sample.dataset_id == dataset_id, Sample.status != "deleted").all()
        dataset.total_samples = len(samples)
        dataset.size = sum(s.size for s in samples)
        dataset.status = "processed" if samples else "created"
        self.db.commit()

    def _normalize_parameters(self, modality: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        normalized: Dict[str, Any] = {}

        strategies = parameters.get("strategies")
        if isinstance(strategies, list):
            for item in strategies:
                if not isinstance(item, dict):
                    continue
                if not item.get("enabled", True):
                    continue
                key = item.get("key")
                params = item.get("params") if isinstance(item.get("params"), dict) else {}
                if modality == "image" and key == "image_deduplicate":
                    normalized["deduplicate"] = True
                    normalized["deduplicate_params"] = params
                if modality == "image" and key == "image_blur_detect":
                    normalized["detect_blur"] = True

        if parameters.get("deduplicate") is True:
            normalized["deduplicate"] = True
            normalized["deduplicate_params"] = parameters.get("deduplicate_params", {})
        if parameters.get("detect_blur") is True:
            normalized["detect_blur"] = True

        normalized["detect_contrast"] = bool(parameters.get("detect_contrast", True))
        return normalized
