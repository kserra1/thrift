from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import joblib
import numpy as np
from pathlib import Path
import logging

from app.batch import BatchProcessor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Thrift Worker",
    description="High-performance ML model serving",
    version="0.2.0"
)

MODEL_PATH = Path(__file__).parent.parent.parent / "models" / "iris_v1.pkl"
model = None
batch_processor = None


@app.on_event("startup")
async def load_model():
    """Load model into memory on startup"""
    global model, batch_processor
    try:
        model = joblib.load(MODEL_PATH)
        batch_processor = BatchProcessor(
            model,
            max_batch_size=32,
            max_wait_ms=50
        )
        logger.info("Batch processor initialized (max_batch_size=32, max_wait_ms=50)")
    except Exception as e:
        logger.error(f"Failed to load model: {e}")
        raise


# Request/Response models
class PredictRequest(BaseModel):
    features: List[float]
    
    class Config:
        schema_extra = {
            "example": {
                "features": [5.1, 3.5, 1.4, 0.2]
            }
        }

class PredictResponse(BaseModel):
    prediction: int
    model_version: str = "iris_v1"

# Health check
@app.get("/health")
async def health():
    """Health check endpoint for load balancer"""
    return {
        "status": "healthy",
        "model_loaded": model is not None,
        "batch_processor": batch_processor is not None
    }


# Prediction endpoint
@app.post("/predict", response_model=PredictResponse)
async def predict(request: PredictRequest):
    """
    Serve predictions from loaded model.
    
    Input: List of features (length must match model's expected input)
    Output: Predicted class
    """
    if batch_processor is None:
        raise HTTPException(status_code=503, detail="Batch processor not initialized")
    
    try:
        # Use batch processor (automatically batches with concurrent requests)
        input_array = np.array(request.features).reshape(1, -1)
        
        # Predict
        prediction = await batch_processor.predict(request.features)
        
        
        return PredictResponse(
            prediction=prediction
        )
    
    except Exception as e:
        logger.error(f"Prediction error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
# Root endpoint
@app.get("/")
async def root():
    return {
        "service": "Thrift Worker",
        "version": "0.2.0",
        "status": "running",
        "features": ["request_batching"]
    }