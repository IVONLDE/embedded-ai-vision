from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, JSON, Float
from sqlalchemy.sql import func

from ..database import Base

class EnhancementTask(Base):
    __tablename__ = "enhancement_tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False)
    algorithm = Column(String(100), nullable=False)
    parameters = Column(JSON, nullable=False)
    target_count = Column(Integer, nullable=False)
    status = Column(String(50), default="pending")
    progress = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
