"""FastAPI worker service with S3 model loading."""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import joblib
import logging
from typing import List, Optional
import os
import tempfile
from dotenv import load_dotenv

from .model_manager import ModelManager
from .batch import BatchProcessor
from .storage import ModelStorage
from .database import init_db
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


app = FastAPI(
    title="ML Serving Platform",
    description="Dynamic multi-model serving with on-demand loading",
    version="2.0.0"
)

# Global model manager
model_manager: Optional[ModelManager] = None


class LoadModelRequest(BaseModel):
    model_name: str
    version: str
    batch_size: int = 32
    batch_wait_ms: int = 50


class UnloadModelRequest(BaseModel):
    model_name: str
    version: str


class PredictRequest(BaseModel):
    features: List[float]


class PredictResponse(BaseModel):
    prediction: int
    model_name: str
    model_version: str


@app.on_event("startup")
async def startup_event():
    """Initialize model manager and database."""
    global model_manager
    
    # Initialize database
    init_db()
    
    # Create model manager (max 5 models in memory by default)
    max_models = int(os.getenv("MAX_MODELS_IN_MEMORY", 5))
    model_manager = ModelManager(max_models_in_memory=max_models)
    
    logger.info(f"ML Serving Platform started (max_models={max_models})")
    logger.info("Models can be loaded dynamically via POST /models/load")


# ===== Model Management Endpoints =====

@app.post("/models/load")
async def load_model(request: LoadModelRequest):
    """
    Load a model from the registry into memory.
    
    Example:
        POST /models/load
        {
            "model_name": "iris",
            "version": "v1",
            "batch_size": 32,
            "batch_wait_ms": 50
        }
    """
    try:
        result = model_manager.load_model(
            model_name=request.model_name,
            version=request.version,
            batch_size=request.batch_size,
            batch_wait_ms=request.batch_wait_ms
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error loading model: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load model: {str(e)}")


@app.post("/models/unload")
async def unload_model(request: UnloadModelRequest):
    """
    Manually unload a model from memory.
    
    Example:
        POST /models/unload
        {
            "model_name": "iris",
            "version": "v1"
        }
    """
    result = model_manager.unload_model(
        model_name=request.model_name,
        version=request.version
    )
    return result


@app.get("/models")
async def list_loaded_models():
    """
    List all currently loaded models in memory.
    
    Returns:
        {
            "loaded_models": [...],
            "count": 2,
            "max_capacity": 5
        }
    """
    loaded = model_manager.get_loaded_models()
    return {
        "loaded_models": loaded,
        "count": len(loaded),
        "max_capacity": model_manager.max_models
    }


# ===== Prediction Endpoints =====

@app.post("/models/{model_name}/versions/{version}/predict", response_model=PredictResponse)
async def predict(model_name: str, version: str, request: PredictRequest):
    """
    Make a prediction using a specific model version.
    
    The model must be loaded first via POST /models/load.
    
    Example:
        POST /models/iris/versions/v1/predict
        {
            "features": [5.1, 3.5, 1.4, 0.2]
        }
    """
    try:
        prediction = await model_manager.predict(
            model_name=model_name,
            version=version,
            features=request.features
        )
        
        return PredictResponse(
            prediction=int(prediction),
            model_name=model_name,
            model_version=version
        )
    
    except ValueError as e:
        raise HTTPException(
            status_code=404,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Prediction error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Prediction failed: {str(e)}"
        )


# ===== Health & Info Endpoints =====

@app.get("/health")
async def health():
    """Health check endpoint."""
    loaded_models = model_manager.get_loaded_models()
    return {
        "status": "healthy",
        "loaded_models_count": len(loaded_models),
        "max_capacity": model_manager.max_models,
        "models": [f"{m['model_name']}:{m['version']}" for m in loaded_models]
    }


@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "service": "ML Serving Platform",
        "version": "2.0.0",
        "features": [
            "Dynamic model loading",
            "Multi-model serving",
            "Automatic LRU eviction",
            "Batch processing"
        ],
        "endpoints": {
            "load_model": "POST /models/load",
            "unload_model": "POST /models/unload",
            "list_models": "GET /models",
            "predict": "POST /models/{name}/versions/{version}/predict",
            "health": "GET /health"
        }
    }