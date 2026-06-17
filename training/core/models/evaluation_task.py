from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Float
from sqlalchemy.sql import func

from ..database import Base

class EvaluationTask(Base):
    __tablename__ = "evaluation_tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    scenario = Column(String(255), nullable=False)
    baseline_dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False)
    enhanced_dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False)
    model = Column(String(255), nullable=False)
    status = Column(String(50), default="pending")
    progress = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
