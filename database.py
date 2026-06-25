# database.py
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
import time
from sqlalchemy.exc import OperationalError

DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql://admin:supersecurepassword@db:5432/transaction_pipeline"
)


engine = None
retries = 5
while retries > 0:
    try:
        engine = create_engine(DATABASE_URL)
        
        connection = engine.connect()
        connection.close()
        print("🚀 Database connection successfully established!")
        break
    except OperationalError:
        retries -= 1
        print(f"⏳ Database is starting up... Retrying in 3 seconds ({retries} retries left)")
        time.sleep(3)

if not engine:
    raise Exception("❌ Could not connect to the database after multiple attempts.")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        