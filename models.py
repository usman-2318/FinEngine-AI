
from sqlalchemy import Column, String, Float, Boolean, ForeignKey, DateTime, Integer, JSON
from sqlalchemy.sql import func
from database import Base

class Job(Base):
    __tablename__ = "jobs"
    
  
    
    id = Column(String, primary_key=True, index=True)


    filename = Column(String, nullable=False)
    status = Column(String, default="pending")
    row_count_raw = Column(Integer, default=0)
    row_count_clean = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
    error_message = Column(String, nullable=True)

class TransactionRecord(Base):
    __tablename__ = "transactions"
    
    id = Column(Integer, primary_key=True, index=True)

    job_id = Column(String, ForeignKey("jobs.id", ondelete="CASCADE"))
    txn_id = Column(String, nullable=True)
    date = Column(String, nullable=True)
    merchant = Column(String, nullable=True)
    amount = Column(Float, default=0.0)
    currency = Column(String, nullable=True)
    status = Column(String, nullable=True)
    category = Column(String, nullable=True)
    account_id = Column(String, nullable=True)
    is_anomaly = Column(Boolean, default=False)
    anomaly_reason = Column(String, nullable=True)
    llm_category = Column(String, nullable=True)
    llm_failed = Column(Boolean, default=False)

class JobSummaryRecord(Base):
    __tablename__ = "job_summaries"
    
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String, ForeignKey("jobs.id", ondelete="CASCADE"))
    total_spend_inr = Column(Float, default=0.0)
    total_spend_usd = Column(Float, default=0.0)
    top_merchants = Column(JSON, nullable=True)
    anomaly_count = Column(Integer, default=0)
    narrative = Column(String, nullable=True)
    risk_level = Column(String, nullable=True)