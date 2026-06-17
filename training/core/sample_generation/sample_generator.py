import os
import threading
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..backend_catalog import get_generation_algorithms
from ..models.dataset import Dataset
from ..models.enhancement_task import EnhancementTask
from ..models.sample import Sample
from .algorithm_manager import AlgorithmManager


class SampleGenerator:
    def __init__(self, db: Session, session_factory=SessionLocal):
        self.db = db
        self.session_factory = session_factory
        self.algorithm_manager = AlgorithmManager()

    def create_enhancement_task(
        self,
        dataset_id: int,
        algorithm: str,
        parameters: Dict[str, Any],
        target_count: int,
    ) -> EnhancementTask:
        task = EnhancementTask(
            dataset_id=dataset_id,
            algorithm=algorithm,
            parameters=parameters or {},
            target_count=target_count,
        )
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    def get_enhancement_tasks(
        self,
        dataset_id: Optional[int] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        query = self.db.query(EnhancementTask)
        if dataset_id:
            query = query.filter(EnhancementTask.dataset_id == dataset_id)
        if status:
            query = query.filter(EnhancementTask.status == status)

        items = query.order_by(EnhancementTask.created_at.desc()).all()
        return {
            "total": len(items),
            "items": [
                {
                    "id": item.id,
                    "dataset_id": item.dataset_id,
                    "algorithm": item.algorithm,
                    "status": item.status,
                    "progress": item.progress,
                    "target_count": item.target_count,
                    "created_at": item.created_at,
                }
                for item in items
            ],
        }

    def get_enhancement_task(self, task_id: int) -> Optional[EnhancementTask]:
        return self.db.query(EnhancementTask).filter(EnhancementTask.id == task_id).first()

    def start_task(self, task_id: int, background: bool = True) -> Dict[str, str]:
        task = self.get_enhancement_task(task_id)
        if not task:
            return {"status": "error", "message": "enhancement task not found"}
        if task.status == "running":
            return {"status": "error", "message": "enhancement task is already running"}

        if background:
            thread = threading.Thread(target=self._process_in_new_session, args=(task_id,), daemon=True)
            thread.start()
            return {"status": "success", "message": "enhancement task started"}

        return self.process_enhancement_task(task_id)

    def _process_in_new_session(self, task_id: int):
        db = self.session_factory()
        try:
            SampleGenerator(db, session_factory=self.session_factory).process_enhancement_task(task_id)
        finally:
            db.close()

    def stop_task(self, task_id: int) -> Dict[str, str]:
        return self.stop_enhancement_task(task_id)

    def stop_enhancement_task(self, task_id: int) -> Dict[str, str]:
        task = self.get_enhancement_task(task_id)
        if not task:
            return {"status": "error", "message": "enhancement task not found"}

        task.status = "stopped"
        self.db.commit()
        return {"status": "success", "message": "enhancement task stopped"}

    def process_enhancement_task(self, task_id: int) -> Dict[str, Any]:
        task = self.get_enhancement_task(task_id)
        if not task:
            return {"status": "error", "message": "enhancement task not found"}

        task.status = "running"
        task.progress = 0
        self.db.commit()

        try:
            if task.target_count <= 0:
                raise ValueError("target_count must be greater than zero")

            samples = self.db.query(Sample).filter(
                Sample.dataset_id == task.dataset_id,
                Sample.status.in_(["raw", "cleaned"]),
            ).all()
            if not samples:
                raise ValueError("no raw or cleaned samples available")

            dataset = self.db.query(Dataset).filter(Dataset.id == task.dataset_id).first()
            if not dataset:
                raise ValueError("dataset not found")

            enhanced_path = os.path.join(dataset.storage_path, "enhanced")
            os.makedirs(enhanced_path, exist_ok=True)

            generated_count = 0
            attempts = 0
            max_attempts = max(task.target_count * max(len(samples), 1) * 2, task.target_count)

            while generated_count < task.target_count and attempts < max_attempts:
                self.db.refresh(task)
                if task.status == "stopped":
                    self.db.commit()
                    return {"status": "success", "message": "enhancement task stopped"}

                sample = samples[attempts % len(samples)]
                enhanced_sample_path = self._generate_enhanced_sample(
                    sample,
                    task.algorithm,
                    task.parameters or {},
                    enhanced_path,
                    generated_count,
                )
                attempts += 1

                if not enhanced_sample_path:
                    continue

                enhanced_sample = Sample(
                    dataset_id=task.dataset_id,
                    name=f"enhanced_{generated_count}_{sample.name}",
                    path=enhanced_sample_path,
                    size=os.path.getsize(enhanced_sample_path),
                    type=sample.type,
                    status="enhanced",
                    sample_metadata={
                        "original_sample_id": sample.id,
                        "enhancement_algorithm": task.algorithm,
                        "enhancement_parameters": task.parameters,
                    },
                )
                self.db.add(enhanced_sample)
                generated_count += 1
                task.progress = (generated_count / task.target_count) * 100
                self.db.commit()

            if generated_count < task.target_count:
                raise ValueError(f"algorithm generated {generated_count}/{task.target_count} samples")

            task.status = "completed"
            task.progress = 100
            self.db.commit()
            self._update_dataset_stats(task.dataset_id)
            return {"status": "success", "generated_count": generated_count}
        except Exception as exc:
            task.status = "failed"
            self.db.commit()
            return {"status": "error", "message": str(exc)}

    def get_algorithms(self, modality: Optional[str] = None) -> List[Dict[str, Any]]:
        return get_generation_algorithms(modality)

    def get_algorithm_parameters(self, algorithm_name: str) -> Optional[Dict[str, Any]]:
        for algorithm in self.get_algorithms():
            if algorithm["key"] == algorithm_name or algorithm["name"] == algorithm_name:
                return algorithm
        return None

    def _generate_enhanced_sample(
        self,
        sample: Sample,
        algorithm: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        if algorithm in {
            "image_geometric_transform_demo",
            "geometric",
            "geometric_transform",
            "\u57fa\u7840\u51e0\u4f55\u53d8\u6362",
        }:
            return self.algorithm_manager.apply_geometric_transformation(sample.path, parameters, output_dir, index)
        if algorithm in {
            "image_style_transfer_demo",
            "style",
            "style_transfer",
            "\u98ce\u683c\u8fc1\u79fb\u751f\u6210",
        }:
            return self.algorithm_manager.apply_style_transfer(sample.path, parameters, output_dir, index)
        if algorithm in {
            "audio_noise_demo",
            "noise",
            "add_noise",
            "\u73af\u5883\u566a\u58f0\u53e0\u52a0",
        }:
            return self.algorithm_manager.add_noise(sample.path, parameters, output_dir, index)
        if algorithm in {
            "audio_spectrum_reconstruction_demo",
            "spectrum",
            "reconstruct_spectrum",
            "\u7279\u5f81\u9891\u8c31\u91cd\u6784",
        }:
            return self.algorithm_manager.reconstruct_spectrum(sample.path, parameters, output_dir, index)
        if algorithm in {
            "text_synonym_replacement_demo",
            "synonym",
            "replace_synonyms",
            "\u540c\u4e49\u8bcd\u8bed\u4e49\u66ff\u6362",
        }:
            return self.algorithm_manager.replace_synonyms(sample.path, parameters, output_dir, index)
        if algorithm in {
            "text_reverse_demo",
            "back_translate",
            "backtranslate",
            "\u56de\u8bd1\u589e\u5f3a\u903b\u8f91",
        }:
            return self.algorithm_manager.back_translate(sample.path, parameters, output_dir, index)
        if algorithm in {"image_gan_demo", "gan", "WGAN-GP"}:
            return self.algorithm_manager.generate_with_gan(sample.path, parameters, output_dir, index)
        if algorithm in {"image_diffusion_demo", "diffusion", "Diffusion"}:
            return self.algorithm_manager.generate_with_diffusion(sample.path, parameters, output_dir, index)
        return None

    def _update_dataset_stats(self, dataset_id: int):
        dataset = self.db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not dataset:
            return

        samples = self.db.query(Sample).filter(Sample.dataset_id == dataset_id, Sample.status != "deleted").all()
        dataset.total_samples = len(samples)
        dataset.size = sum(sample.size for sample in samples)
        dataset.status = "processed" if samples else "created"
        self.db.commit()
