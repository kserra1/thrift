from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import joblib
import numpy as np
from pathlib import Path
import logging


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Thrift Worker",
    description="High-performance ML model serving",
    version="0.1.0"
)

MODEL_PATH = Path(__file__).parent.parent.parent / "models" / "iris_v1.pkl"
model = None


@app.on_event("startup")
async def load_model():
    """Load model into memory on startup"""
    global model
    try:
        model = joblib.load(MODEL_PATH)
        logger.info(f"Model loaded from {MODEL_PATH}")
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
        "model_loaded": model is not None
    }


# Prediction endpoint
@app.post("/predict", response_model=PredictResponse)
async def predict(request: PredictRequest):
    """
    Serve predictions from loaded model.
    
    Input: List of features (length must match model's expected input)
    Output: Predicted class
    """
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    try:
        # Convert to numpy array
        input_array = np.array(request.features).reshape(1, -1)
        
        # Predict
        prediction = model.predict(input_array)
        
        logger.info(f"Prediction: {prediction[0]} for input: {request.features}")
        
        return PredictResponse(
            prediction=int(prediction[0])
        )
    
    except Exception as e:
        logger.error(f"Prediction error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
# Root endpoint
@app.get("/")
async def root():
    return {
        "service": "Thrift Worker",
        "version": "0.1.0",
        "status": "running"
    }