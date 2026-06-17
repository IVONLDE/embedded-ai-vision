from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, JSON
from sqlalchemy.sql import func

from ..database import Base

class EvaluationResult(Base):
    __tablename__ = "evaluation_results"
    
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("evaluation_tasks.id"), nullable=False)
    model_type = Column(String(50), nullable=False)  # baseline/enhanced
    metrics = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
