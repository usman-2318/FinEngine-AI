# main.py
from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import uuid
import shutil
import os


from database import get_db, engine, Base
from models import Job, TransactionRecord, JobSummaryRecord
from tasks import process_csv_pipeline


Base.metadata.create_all(bind=engine)

app = FastAPI(title="AI-Powered Transaction Processing Pipeline API")


UPLOAD_DIR = "/tmp/uploaded_files"
os.makedirs(UPLOAD_DIR, exist_ok=True)



@app.post("/jobs/upload", status_code=202)
async def upload_transactions(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Accepts raw CSV file, registers a pending job tracking token in DB, 
    and hands over processing execution asynchronously to Celery.
    """
   
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Invalid file type. Only standard CSV layouts permitted.")
        
    job_id = str(uuid.uuid4())
    saved_file_path = os.path.join(UPLOAD_DIR, f"{job_id}.csv")
    
  
    with open(saved_file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    
    with open(saved_file_path, "r", encoding="utf-8") as f:
        row_count = sum(1 for line in f) - 1 
        
    
    new_job = Job(
        id=job_id,
        filename=file.filename,
        status="pending",
        row_count_raw=row_count
    )
    db.add(new_job)
    db.commit()
    
   
    process_csv_pipeline.delay(job_id, saved_file_path)
    
    return {"job_id": job_id, "status": "pending"}



@app.get("/jobs/{job_id}/status")
async def get_job_status(job_id: str, db: Session = Depends(get_db)):
    """
    Returns high-level active operational pipeline tracking metrics parameters.
    """
    job_record = db.query(Job).filter(Job.id == job_id).first()
    if not job_record:
        raise HTTPException(status_code=404, detail="Requested Job ID tracking vector not found.")
        
    response_data = {
        "job_id": job_record.id,
        "status": job_record.status,
        "filename": job_record.filename,
        "created_at": job_record.created_at
    }
    
   
    if job_record.status == "completed":
        response_data["summary"] = {
            "row_count_raw": job_record.row_count_raw,
            "row_count_clean": job_record.row_count_clean
        }
    elif job_record.status == "failed":
        response_data["error_message"] = job_record.error_message
        
    return response_data



@app.get("/jobs/{job_id}/results")
async def get_job_results(job_id: str, db: Session = Depends(get_db)):
    """
    Fetches clean transactional array records alongside custom generated LLM reports.
    """
    job_record = db.query(Job).filter(Job.id == job_id).first()
    if not job_record:
        raise HTTPException(status_code=404, detail="Target processing records context missing.")
        
    if job_record.status != "completed":
        return {"job_id": job_id, "status": job_record.status, "message": "Results pending completion."}
        
  
    transactions = db.query(TransactionRecord).filter(TransactionRecord.job_id == job_id).all()
    summary = db.query(JobSummaryRecord).filter(JobSummaryRecord.job_id == job_id).first()
    
   
    category_breakdown = {}
    for tx in transactions:
        category_breakdown[tx.category] = category_breakdown.get(tx.category, 0.0) + tx.amount

    return {
        "job_id": job_id,
        "status": job_record.status,
        "metadata": {
            "filename": job_record.filename,
            "raw_rows": job_record.row_count_raw,
            "clean_rows": job_record.row_count_clean
        },
        "llm_narrative_summary": {
            "total_spend_inr": summary.total_spend_inr if summary else 0.0,
            "total_spend_usd": summary.total_spend_usd if summary else 0.0,
            "top_merchants": summary.top_merchants if summary else [],
            "anomaly_count": summary.anomaly_count if summary else 0,
            "narrative": summary.narrative if summary else "",
            "risk_level": summary.risk_level if summary else "low"
        },
        "category_spend_breakdown": category_breakdown,
        "flagged_anomalies": [
            {
                "txn_id": tx.txn_id,
                "merchant": tx.merchant,
                "amount": tx.amount,
                "currency": tx.currency,
                "reason": tx.anomaly_reason
            } for tx in transactions if tx.is_anomaly
        ],
        "cleaned_transactions": [
            {
                "txn_id": tx.txn_id,
                "date": tx.date,
                "merchant": tx.merchant,
                "amount": tx.amount,
                "currency": tx.currency,
                "status": tx.status,
                "category": tx.category,
                "account_id": tx.account_id
            } for tx in transactions
        ]
    }



@app.get("/jobs")
async def list_all_jobs(status: str = Query(None), db: Session = Depends(get_db)):
    """
    Returns chronological operational logs tracking parameters across structural items.
    """
    query = db.query(Job)
    if status:
        query = query.filter(Job.status == status.lower().strip())
        
    jobs_list = query.order_by(Job.created_at.desc()).all()
    
    return [
        {
            "job_id": job.id,
            "filename": job.filename,
            "status": job.status,
            "row_count": job.row_count_raw,
            "created_at": job.created_at
        } for job in jobs_list
    ]