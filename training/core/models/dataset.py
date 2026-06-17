from sqlalchemy import Column, Integer, String, Text, BigInteger, DateTime
from sqlalchemy.sql import func

from ..database import Base

class Dataset(Base):
    __tablename__ = "datasets"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False)
    description = Column(Text)
    total_samples = Column(Integer, default=0)
    size = Column(BigInteger, default=0)
    status = Column(String(50), default="created")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    storage_path = Column(String(500), nullable=False)
