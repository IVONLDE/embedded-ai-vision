import os
import shutil
import datetime
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from typing import List, Optional, Dict, Any

from ..models.dataset import Dataset
from ..models.sample import Sample
from ..models.system_log import SystemLog
from .file_processor import FileProcessor

class DataManager:
    def __init__(self, db: Session):
        self.db = db
        self.file_processor = FileProcessor()

    def _sanitize_dataset_dirname(self, name: str) -> str:
        invalid = '<>:"/\\|?*'
        sanitized = "".join("_" if ch in invalid else ch for ch in (name or ""))
        sanitized = sanitized.strip().strip(".")
        return sanitized or "dataset"

    def create_dataset(self, name: str, type: str, description: str = "") -> Dataset:
        """创建新数据集"""
        if not name or not name.strip():
            raise ValueError("数据集名称不能为空")

        exists = self.db.query(Dataset).filter(Dataset.name == name).first()
        if exists:
            raise ValueError("数据集名称已存在")

        base_dir = os.path.abspath(os.path.join(".", "data", "datasets"))
        os.makedirs(base_dir, exist_ok=True)
        safe_dir = self._sanitize_dataset_dirname(name)
        storage_path = os.path.join(base_dir, safe_dir)
        candidate = storage_path
        suffix = 1
        while os.path.exists(candidate):
            candidate = f"{storage_path}_{suffix}"
            suffix += 1
        storage_path = candidate
        os.makedirs(storage_path, exist_ok=True)
        
        dataset = Dataset(
            name=name,
            type=type,
            description=description,
            storage_path=storage_path
        )
        try:
            self.db.add(dataset)
            self.db.commit()
            self.db.refresh(dataset)
            
            log = SystemLog(
                user_id=1,
                action="create",
                resource_type="dataset",
                resource_id=dataset.id,
                description=f"创建了新的数据集: {name}"
            )
            self.db.add(log)
            self.db.commit()
            return dataset
        except Exception:
            self.db.rollback()
            try:
                if os.path.isdir(storage_path) and not os.listdir(storage_path):
                    os.rmdir(storage_path)
            except Exception:
                pass
            raise

    def get_datasets(self, page: int = 1, page_size: int = 10, status: Optional[str] = None) -> Dict[str, Any]:
        """获取数据集列表"""
        query = self.db.query(Dataset)
        if status:
            query = query.filter(Dataset.status == status)
        
        total = query.count()
        items = query.offset((page - 1) * page_size).limit(page_size).all()
        
        # 转换为字典列表
        items_list = []
        for item in items:
            items_list.append({
                "id": item.id,
                "name": item.name,
                "type": item.type,
                "status": item.status,
                "total_samples": item.total_samples,
                "size": item.size,
                "created_at": item.created_at
            })
        
        return {"total": total, "items": items_list}

    def get_dataset(self, dataset_id: int) -> Optional[Dataset]:
        """获取数据集详情"""
        return self.db.query(Dataset).filter(Dataset.id == dataset_id).first()

    def update_dataset(self, dataset_id: int, name: Optional[str] = None, description: Optional[str] = None) -> Optional[Dataset]:
        """更新数据集信息"""
        dataset = self.get_dataset(dataset_id)
        if not dataset:
            return None
        
        if name:
            dataset.name = name
        if description is not None:
            dataset.description = description
        
        self.db.commit()
        self.db.refresh(dataset)
        return dataset

    def delete_dataset(self, dataset_id: int) -> bool:
        """删除数据集"""
        dataset = self.get_dataset(dataset_id)
        if not dataset:
            return False
        
        name = dataset.name
        
        # 删除文件
        import shutil
        if os.path.exists(dataset.storage_path):
            shutil.rmtree(dataset.storage_path)
        
        self.db.delete(dataset)
        
        # 记录活动日志
        log = SystemLog(
            user_id=1,
            action="delete",
            resource_type="dataset",
            resource_id=dataset_id,
            description=f"删除了数据集: {name}"
        )
        self.db.add(log)
        
        self.db.commit()
        return True

    def get_dataset_stats(self, dataset_id: int) -> Dict[str, Any]:
        """获取数据集统计信息"""
        dataset = self.get_dataset(dataset_id)
        if not dataset:
            return {}
        
        samples = self.db.query(Sample).filter(Sample.dataset_id == dataset_id).all()
        type_distribution = {}
        for sample in samples:
            if sample.type not in type_distribution:
                type_distribution[sample.type] = 0
            type_distribution[sample.type] += 1
        
        return {
            "total_samples": len(samples),
            "size": dataset.size,
            "type_distribution": type_distribution
        }

    def upload_file(self, dataset_id: int, file) -> Dict[str, Any]:
        """上传文件到数据集"""
        dataset = self.get_dataset(dataset_id)
        if not dataset:
            return {"status": "error", "message": "数据集不存在"}
        
        result = self.file_processor.process_file(file, dataset_id)
        if result["status"] == "success":
            # 更新数据集统计信息
            self._update_dataset_stats(dataset_id)
            
            # 记录活动日志
            log = SystemLog(
                user_id=1,
                action="create",
                resource_type="sample",
                resource_id=dataset_id,
                description=f"向数据集 {dataset.name} 上传了文件: {file.filename}"
            )
            self.db.add(log)
            self.db.commit()
        
        return result

    def import_folder(self, dataset_id: int, folder_path: str, include_subfolders: bool = True) -> Dict[str, Any]:
        """导入文件夹到数据集"""
        dataset = self.get_dataset(dataset_id)
        if not dataset:
            return {"status": "error", "message": "数据集不存在"}
        
        result = self.file_processor.process_folder(folder_path, dataset_id, include_subfolders)
        if result["status"] == "success":
            # 更新数据集统计信息
            self._update_dataset_stats(dataset_id)
            
            # 记录活动日志
            log = SystemLog(
                user_id=1,
                action="create",
                resource_type="dataset",
                resource_id=dataset_id,
                description=f"向数据集 {dataset.name} 导入了文件夹: {os.path.basename(folder_path)}"
            )
            self.db.add(log)
            self.db.commit()
        
        return result

    def get_samples(self, dataset_id: int, page: int = 1, page_size: int = 10, status: Optional[str] = None) -> Dict[str, Any]:
        """获取数据集样本列表"""
        query = self.db.query(Sample).filter(Sample.dataset_id == dataset_id)
        if status:
            query = query.filter(Sample.status == status)
        
        total = query.count()
        items = query.order_by(Sample.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
        
        # 转换为字典列表
        items_list = []
        for item in items:
            items_list.append({
                "id": item.id,
                "name": item.name,
                "type": item.type,
                "status": item.status,
                "size": item.size,
                "path": item.path,
                "created_at": item.created_at
            })
        
        return {"total": total, "items": items_list}

    def get_dataset_preview_samples(self, dataset_id: int, limit: int = 20, status: Optional[str] = None) -> Dict[str, Any]:
        query = self.db.query(Sample).filter(Sample.dataset_id == dataset_id)
        if status:
            query = query.filter(Sample.status == status)

        total = query.count()
        safe_limit = max(0, min(int(limit or 0), 200))
        if safe_limit == 0:
            return {"total": total, "items": []}

        items = query.order_by(func.random()).limit(safe_limit).all()
        items_list = []
        for item in items:
            items_list.append({
                "id": item.id,
                "name": item.name,
                "type": item.type,
                "status": item.status,
                "size": item.size,
                "path": item.path,
                "created_at": item.created_at
            })
        return {"total": total, "items": items_list}

    def get_sample(self, sample_id: int) -> Optional[Sample]:
        """获取样本详情"""
        return self.db.query(Sample).filter(Sample.id == sample_id).first()

    def delete_sample(self, sample_id: int) -> bool:
        """删除样本"""
        sample = self.get_sample(sample_id)
        if not sample:
            return False
        
        # 删除文件
        if os.path.exists(sample.path):
            os.remove(sample.path)
        
        self.db.delete(sample)
        self.db.commit()
        
        # 更新数据集统计信息
        self._update_dataset_stats(sample.dataset_id)
        return True

    def batch_delete_samples(self, sample_ids: List[int]) -> Dict[str, Any]:
        """批量删除样本"""
        deleted_count = 0
        dataset_ids = set()
        
        for sample_id in sample_ids:
            sample = self.get_sample(sample_id)
            if sample:
                # 删除文件
                if os.path.exists(sample.path):
                    os.remove(sample.path)
                
                dataset_ids.add(sample.dataset_id)
                self.db.delete(sample)
                deleted_count += 1
        
        self.db.commit()
        
        # 更新数据集统计信息
        for dataset_id in dataset_ids:
            self._update_dataset_stats(dataset_id)
        
        return {"status": "success", "deleted_count": deleted_count}

    def _update_dataset_stats(self, dataset_id: int):
        """更新数据集统计信息"""
        dataset = self.get_dataset(dataset_id)
        if not dataset:
            return
        
        samples = self.db.query(Sample).filter(Sample.dataset_id == dataset_id, Sample.status != "deleted").all()
        total_size = sum(sample.size for sample in samples)
        
        dataset.total_samples = len(samples)
        dataset.size = total_size
        dataset.status = "processed" if samples else "created"
        
        self.db.commit()
    
    def get_recent_activities(self, limit: int = 5) -> List[Dict[str, Any]]:
        """获取最近的活动记录"""
        logs = self.db.query(SystemLog).order_by(SystemLog.created_at.desc()).limit(limit).all()
        
        activities = []
        for log in logs:
            activities.append({
                "title": log.description,
                "time": log.created_at.strftime("%Y/%m/%d %H:%M"),
                "col": self._get_activity_color(log.action)
            })
        
        # 如果没有日志记录，返回一些默认的活动
        if not activities:
            default_activities = [
                {"title": "导入了新的船舶图像数据集", "time": "今天 09:45", "col": "#165DFF"},
                {"title": "删除了过期的测试数据集", "time": "昨天 16:20", "col": "#36CFC9"},
                {"title": "样本生成任务完成", "time": "昨天 14:10", "col": "#52C41A"},
                {"title": "数据清洗发现128个异常样本", "time": "2023/11/28 11:35", "col": "#FAAD14"},
                {"title": "模型训练任务失败", "time": "2023/11/27 08:42", "col": "#FF4D4F"}
            ]
            return default_activities
        
        return activities
    
    def get_system_stats(self) -> Dict[str, Any]:
        """获取系统整体数据指标"""
        # 总数据集数量
        total_datasets = self.db.query(Dataset).count()
        
        # 总样本数
        total_samples = self.db.query(Sample).count()
        
        # 已处理样本数
        processed_samples = self.db.query(Sample).filter(Sample.status.in_(["processed", "cleaned", "enhanced"])).count()
        
        # 计算总存储空间
        total_size = 0
        datasets = self.db.query(Dataset).all()
        for dataset in datasets:
            total_size += dataset.size
        
        total_size_gb = total_size / (1024 * 1024 * 1024)
        total_disk_gb = 0.0
        try:
            storage_root = os.path.abspath("./data")
            os.makedirs(storage_root, exist_ok=True)
            total_disk, used_disk, _ = shutil.disk_usage(storage_root)
            total_disk_gb = total_disk / (1024 * 1024 * 1024) if total_disk else 0.0
            storage_usage = int((total_size / total_disk) * 100) if total_disk else 0
        except Exception:
            storage_usage = 0

        return {
            "total_datasets": total_datasets,
            "total_samples": total_samples,
            "processed_samples": processed_samples,
            "total_storage": f"{total_size_gb:.1f}/{total_disk_gb:.1f} GB" if total_disk_gb > 0 else f"{total_size_gb:.1f} GB",
            "storage_usage": storage_usage
        }
    
    def get_sample_growth_trend(self, period: str = "week") -> Dict[str, Any]:
        """获取样本增长趋势"""
        now = datetime.datetime.now()

        if period == "day":
            start_date = now - datetime.timedelta(days=1)
            step = datetime.timedelta(hours=1)
            label_fmt = "%H:00"
        elif period == "month":
            start_date = now - datetime.timedelta(days=30)
            step = datetime.timedelta(days=1)
            label_fmt = "%m-%d"
        elif period == "year":
            start_date = now - datetime.timedelta(days=365)
            step = datetime.timedelta(days=30)
            label_fmt = "%Y-%m"
        else:
            start_date = now - datetime.timedelta(days=7)
            step = datetime.timedelta(days=1)
            label_fmt = "%m-%d"

        bucket_ends: List[datetime.datetime] = []
        labels: List[str] = []
        current = start_date
        while current <= now:
            bucket_ends.append(current)
            labels.append(current.strftime(label_fmt))
            current += step

        created_list = self.db.query(Sample.created_at).filter(Sample.created_at >= start_date).all()
        timestamps = [row[0] for row in created_list if row and row[0] is not None]
        timestamps.sort()

        data: List[int] = []
        idx = 0
        total = 0
        for bucket_end in bucket_ends:
            while idx < len(timestamps) and timestamps[idx] <= bucket_end:
                total += 1
                idx += 1
            data.append(total)

        return {"labels": labels, "data": data}
    
    def get_data_type_distribution(self) -> Dict[str, Any]:
        """获取数据类型分布"""
        # 统计各类型的样本数量
        type_counts = {}
        samples = self.db.query(Sample).all()
        
        for sample in samples:
            if sample.type not in type_counts:
                type_counts[sample.type] = 0
            type_counts[sample.type] += 1
        
        # 如果没有样本，返回默认数据
        if not type_counts:
            return {
                "labels": ["图像", "音频", "文本"],
                "data": [45, 30, 25]
            }
        
        # 转换为前端需要的格式
        labels = []
        data = []
        for type_name, count in type_counts.items():
            # 转换类型名称为中文
            type_map = {
                "image": "图像",
                "audio": "音频",
                "text": "文本",
                "application": "其他"
            }
            labels.append(type_map.get(type_name, type_name))
            data.append(count)
        
        return {
            "labels": labels,
            "data": data
        }
    
    def _get_activity_color(self, action: str) -> str:
        """根据活动类型返回对应的颜色"""
        color_map = {
            "create": "#165DFF",
            "delete": "#36CFC9",
            "complete": "#52C41A",
            "warning": "#FAAD14",
            "error": "#FF4D4F"
        }
        return color_map.get(action, "#64748B")
