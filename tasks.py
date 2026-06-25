from celery import Celery
import os
import traceback

from pipeline_utils import TransactionPipeline
from database import SessionLocal
from models import Job, TransactionRecord, JobSummaryRecord

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery(
    "tasks",
    broker=REDIS_URL,
    backend=REDIS_URL
)


@celery_app.task(name="tasks.process_csv_pipeline")
def process_csv_pipeline(job_id, file_path):
    print(f"🚀 Job {job_id} processing initiated...")

    db = SessionLocal()
    pipeline = TransactionPipeline()

    try:
        # Update job status
        job_record = db.query(Job).filter(Job.id == job_id).first()

        if job_record:
            job_record.status = "processing"
            db.commit()

        
        cleaned_df = pipeline.clean_data(file_path)
        analyzed_df = pipeline.detect_anomalies(cleaned_df)
        
        #final_df = pipeline.classify_missing_categories_batch(analyzed_df)
        #summary_report = pipeline.generate_narrative_summary(final_df)
        final_df = analyzed_df

        summary_report = {
                "total_spend_inr": float(final_df[final_df["currency"] == "INR"]["amount"].sum()),
                "total_spend_usd": float(final_df[final_df["currency"] == "USD"]["amount"].sum()),
                "top_merchants": final_df["merchant"].value_counts().head(3).index.tolist(),
                "anomaly_count": int(final_df["is_anomaly"].sum()),
                "narrative": "Transactions processed successfully.",
                "risk_level": "low"
            }

        

        # Save transaction rows
        for index, row in final_df.iterrows():

            try:
                txn_id = None if str(row.get("txn_id")) == "nan" else str(row.get("txn_id"))
                txn_date = None if str(row.get("date")) == "nan" else str(row.get("date"))
                txn_amount = float(row.get("amount", 0.0))

                print(
                    f"ROW {index} -> "
                    f"txn_id={txn_id}, "
                    f"date={txn_date}, "
                    f"amount={txn_amount}"
                )

                txn_row = TransactionRecord(
                    job_id=job_id,
                    txn_id=txn_id,
                    date=txn_date,
                    merchant=None if str(row.get("merchant")) == "nan" else str(row.get("merchant")),
                    amount=txn_amount,
                    currency=None if str(row.get("currency")) == "nan" else str(row.get("currency")),
                    status=None if str(row.get("status")) == "nan" else str(row.get("status")),
                    category=None if str(row.get("category")) == "nan" else str(row.get("category")),
                    account_id=None if str(row.get("account_id")) == "nan" else str(row.get("account_id")),
                    is_anomaly=bool(row.get("is_anomaly", False)),
                    anomaly_reason=None if str(row.get("anomaly_reason")) == "nan" else str(row.get("anomaly_reason")),
                    llm_category=None if str(row.get("llm_category")) == "nan" else str(row.get("llm_category")),
                    llm_failed=bool(row.get("llm_failed", False))
                )

                db.add(txn_row)

            except Exception as row_error:
                print("\n========== ROW ERROR ==========")
                print("ROW INDEX:", index)
                print("ROW DATA:", row.to_dict())
                print("ERROR:", row_error)
                print("================================\n")
                raise

        # Save summary
        summary_row = JobSummaryRecord(
            job_id=job_id,
            total_spend_inr=float(summary_report["total_spend_inr"]),
            total_spend_usd=float(summary_report["total_spend_usd"]),
            top_merchants=summary_report["top_merchants"],
            anomaly_count=int(summary_report["anomaly_count"]),
            narrative=summary_report["narrative"],
            risk_level=summary_report["risk_level"]
        )

        db.add(summary_row)

        if job_record:
            job_record.status = "completed"
            job_record.row_count_clean = len(final_df)

        db.commit()

        print(f"✅ Job {job_id} completed successfully")

        return {
            "status": "SUCCESS",
            "job_id": job_id
        }

    except Exception as e:

        traceback.print_exc()

        db.rollback()

        job_record = db.query(Job).filter(Job.id == job_id).first()

        if job_record:
            job_record.status = "failed"
            job_record.error_message = str(e)
            db.commit()

        print(f"❌ Job {job_id} FAILED")
        print(f"❌ ERROR: {e}")

        return {
            "status": "FAILED",
            "error": str(e)
        }

    finally:
        db.close()