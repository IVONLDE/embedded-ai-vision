from sqlalchemy import Column, Integer, String, ForeignKey, BigInteger, DateTime, JSON
from sqlalchemy.sql import func

from ..database import Base

class Sample(Base):
    __tablename__ = "samples"
    
    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False)
    name = Column(String(255), nullable=False)
    path = Column(String(500), nullable=False)
    size = Column(BigInteger, default=0)
    type = Column(String(50), nullable=False)
    sample_metadata = Column(JSON)
    status = Column(String(50), default="raw")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
