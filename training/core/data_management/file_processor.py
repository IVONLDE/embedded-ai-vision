import os
import shutil
from typing import Dict, Any

from ..models.dataset import Dataset
from ..models.sample import Sample
from ..database import SessionLocal

class FileProcessor:
    def process_file(self, file_path_or_obj, dataset_id: int) -> Dict[str, Any]:
        """处理上传的文件

        支持两种输入:
          - 本地文件路径 (str/Path): 桌面应用 QML 传入
          - 文件对象 (有 .filename 和 .file 属性): Web API 传入
        """
        db = SessionLocal()
        try:
            # 创建存储目录
            dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
            if not dataset:
                return {"status": "error", "message": "数据集不存在"}

            storage_path = dataset.storage_path
            os.makedirs(storage_path, exist_ok=True)

            # 处理两种输入模式
            if isinstance(file_path_or_obj, str):
                # 桌面应用: 传入本地文件路径
                source_path = file_path_or_obj
                filename = os.path.basename(source_path)
                dest_path = os.path.join(storage_path, filename)
                shutil.copy2(source_path, dest_path)
                file_type, _ = mimetypes.guess_type(source_path) or ("application/octet-stream", None)
            elif hasattr(file_path_or_obj, 'filename'):
                # Web API: 上传的文件对象
                filename = file_path_or_obj.filename
                dest_path = os.path.join(storage_path, filename)
                with open(dest_path, "wb") as f:
                    source = getattr(file_path_or_obj, 'file', file_path_or_obj)
                    if hasattr(source, 'read'):
                        shutil.copyfileobj(source, f)
                    else:
                        f.write(source)
                file_type = getattr(file_path_or_obj, 'content_type', 'application/octet-stream')
            else:
                return {"status": "error", "message": "不支持的文件输入类型"}

            if not file_type:
                file_type = "application/octet-stream"
            
            # 提取元数据
            metadata = self.extract_metadata(dest_path, file_type)

            # 验证文件
            if not self.validate_file(dest_path, file_type):
                os.remove(dest_path)
                return {"status": "error", "message": "文件验证失败"}

            # 创建样本记录
            sample = Sample(
                dataset_id=dataset_id,
                name=filename,
                path=dest_path,
                size=os.path.getsize(dest_path),
                type=file_type.split("/")[0],
                sample_metadata=metadata
            )
            db.add(sample)
            db.commit()
            
            return {"status": "success", "message": "文件上传成功", "file_id": sample.id}
        finally:
            db.close()

    def process_folder(self, folder_path: str, dataset_id: int, include_subfolders: bool = True) -> Dict[str, Any]:
        """处理导入的文件夹"""
        db = SessionLocal()
        try:
            # 检查文件夹是否存在
            if not os.path.isdir(folder_path):
                return {"status": "error", "message": "文件夹不存在"}
            
            # 创建存储目录
            dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
            if not dataset:
                return {"status": "error", "message": "数据集不存在"}
            
            storage_path = dataset.storage_path
            os.makedirs(storage_path, exist_ok=True)
            
            # 递归处理文件
            processed_count = 0
            for root, dirs, files in os.walk(folder_path):
                if not include_subfolders and root != folder_path:
                    continue
                
                for file_name in files:
                    file_path = os.path.join(root, file_name)
                    # 复制文件
                    relative_path = os.path.relpath(file_path, folder_path)
                    dest_path = os.path.join(storage_path, relative_path)
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    shutil.copy2(file_path, dest_path)
                    
                    # 提取文件类型
                    import mimetypes
                    file_type, _ = mimetypes.guess_type(file_path)
                    if not file_type:
                        file_type = "application/octet-stream"
                    
                    # 提取元数据
                    metadata = self.extract_metadata(dest_path, file_type)
                    
                    # 验证文件
                    if self.validate_file(dest_path, file_type):
                        # 创建样本记录
                        sample = Sample(
                            dataset_id=dataset_id,
                            name=relative_path,
                            path=dest_path,
                            size=os.path.getsize(dest_path),
                            type=file_type.split("/")[0],
                            sample_metadata=metadata
                        )
                        db.add(sample)
                        processed_count += 1
            
            db.commit()
            return {"status": "success", "message": f"文件夹导入成功，处理了 {processed_count} 个文件"}
        finally:
            db.close()

    def extract_metadata(self, file_path: str, file_type: str) -> Dict[str, Any]:
        """提取文件元数据"""
        metadata = {}
        
        # 根据文件类型提取不同的元数据
        if file_type.startswith("image/"):
            try:
                from PIL import Image
                with Image.open(file_path) as img:
                    metadata["width"] = img.width
                    metadata["height"] = img.height
                    metadata["format"] = img.format
            except Exception:
                pass
        elif file_type.startswith("audio/"):
            try:
                import mutagen
                audio = mutagen.File(file_path)
                if audio:
                    metadata["duration"] = audio.info.length if hasattr(audio.info, 'length') else None
                    metadata["format"] = audio.info.format if hasattr(audio.info, 'format') else None
            except Exception:
                pass
        elif file_type.startswith("text/") or file_type == "application/json" or file_type == "application/csv":
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    metadata["lines"] = len(content.splitlines())
                    metadata["characters"] = len(content)
            except Exception:
                pass
        
        return metadata

    def validate_file(self, file_path: str, file_type: str) -> bool:
        """验证文件有效性"""
        # 检查文件大小
        if os.path.getsize(file_path) == 0:
            return False
        
        # 根据文件类型进行不同的验证
        if file_type.startswith("image/"):
            try:
                from PIL import Image
                with Image.open(file_path) as img:
                    img.verify()
                return True
            except Exception:
                return False
        elif file_type.startswith("audio/"):
            try:
                import mutagen
                audio = mutagen.File(file_path)
                return audio is not None
            except Exception:
                return False
        elif file_type.startswith("text/") or file_type == "application/json" or file_type == "application/csv":
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    f.read()
                return True
            except Exception:
                return False
        
        # 其他类型的文件默认通过验证
        return True
