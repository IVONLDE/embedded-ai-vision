from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func

from ..database import Base

class SystemLog(Base):
    __tablename__ = "system_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer)
    action = Column(String(255), nullable=False)
    resource_type = Column(String(50))
    resource_id = Column(Integer)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
