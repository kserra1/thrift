"""Database models and connection management."""
from sqlalchemy import create_engine, Column, String, Integer, DateTime, Float, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://thrift:dev_password@localhost:5432/thrift"
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class ModelMetadata(Base):
    """Track deployed models and their metadata."""
    __tablename__ = "model_metadata"

    id = Column(Integer, primary_key=True, index=True)
    model_name = Column(String, nullable=False, index=True)
    version = Column(String, nullable=False, index=True)
    s3_path = Column(String, nullable=False)  # e.g., "models/iris_v1.pkl"
    framework = Column(String)  # sklearn, pytorch, etc.
    created_at = Column(DateTime, default=datetime.utcnow)
    model_metadata = Column(JSON)  # Changed from 'metadata' to 'model_metadata'


class PredictionLog(Base):
    """Optional: log predictions for monitoring/retraining."""
    __tablename__ = "prediction_logs"

    id = Column(Integer, primary_key=True, index=True)
    model_name = Column(String, index=True)
    model_version = Column(String)
    request_id = Column(String, index=True)
    latency_ms = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    input_features = Column(JSON)
    prediction = Column(Integer)


def init_db():
    """Create all tables."""
    Base.metadata.create_all(bind=engine)