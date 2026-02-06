"""FastAPI worker service with S3 model loading."""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import joblib
import logging
from typing import List
import os
import tempfile
from dotenv import load_dotenv

from .batch import BatchProcessor
from .storage import ModelStorage
from .database import SessionLocal, ModelMetadata, init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI(title="ML Serving Platform")

# Global state
model = None
batch_processor = None
model_version = None


class PredictRequest(BaseModel):
    features: List[float]


class PredictResponse(BaseModel):
    prediction: int
    model_version: str


@app.on_event("startup")
async def startup_event():
    """Load model from S3 on startup."""
    global model, batch_processor, model_version
    
    # Initialize database
    init_db()
    
    # Get model metadata from database
    model_name = os.getenv("MODEL_NAME", "iris")
    print(os.getenv("DATABASE_URL"), "TESTST")
    version = os.getenv("MODEL_VERSION", "v1")
    
    db = SessionLocal()
    try:
        metadata = db.query(ModelMetadata).filter(
            ModelMetadata.model_name == model_name,
            ModelMetadata.version == version
        ).first()
        
        if not metadata:
            raise RuntimeError(
                f"Model {model_name}:{version} not found in database. "
                "Train and upload a model first."
            )
        
        # Download model from S3
        storage = ModelStorage()
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pkl') as tmp:
            local_path = tmp.name
        
        storage.download_model(metadata.s3_path, local_path)
        model = joblib.load(local_path)
        os.remove(local_path)  # Cleanup
        
        model_version = f"{model_name}_{version}"
        batch_processor = BatchProcessor(model, max_batch_size=32, max_wait_ms=50)
        
        logger.info(f"Model {model_version} loaded from {metadata.s3_path}")
        logger.info(f"Metadata: {metadata.model_metadata}")  # Changed from 'metadata'
        
    finally:
        db.close()


@app.post("/predict", response_model=PredictResponse)
async def predict(request: PredictRequest):
    """Make a prediction."""
    if batch_processor is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    if len(request.features) != 4:
        raise HTTPException(
            status_code=400,
            detail="Expected 4 features for Iris classification"
        )
    
    prediction = await batch_processor.predict(request.features)
    return PredictResponse(prediction=int(prediction), model_version=model_version)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "model_loaded": model is not None,
        "model_version": model_version,
        "batch_processor": batch_processor is not None
    }


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "ML Serving Platform", "version": model_version}