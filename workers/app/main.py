"""FastAPI worker service with S3 model loading."""
import time
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import joblib
from typing import List, Optional
import os
import tempfile
from dotenv import load_dotenv

from .model_manager import ModelManager
from .batch import BatchProcessor
from .storage import ModelStorage
from .database import init_db
from .middleware import ObservabilityMiddleware
from .logging_config import setup_logging, get_logger
from .prediction_logger import prediction_logger
from .metrics import (
    predictions_total,
    prediction_duration_seconds,
    prediction_errors_total,
    batch_size_histogram,
    service_info
)

from prometheus_client import make_asgi_app

load_dotenv()

# Setup structured logging
setup_logging(level=os.getenv("LOG_LEVEL", "INFO"))
logger = get_logger(__name__)


app = FastAPI(
    title="ML Serving Platform",
    description="Dynamic multi-model serving with on-demand loading",
    version="2.1.0"
)
# ==== Metrics Endpoint ====

# Mount Promtheus metrics endpoint
# This exposes /metrics for Prometheus to scrape
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Add observability middleware
app.add_middleware(ObservabilityMiddleware)

# Global model manager
model_manager: Optional[ModelManager] = None


class LoadModelRequest(BaseModel):
    model_name: str
    version: str
    batch_size: Optional[int] = None
    batch_wait_ms: Optional[int] = None


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

    logger.info("Starting Thrift ML Serving Platform...")
    
    # Initialize database
    init_db()
    logger.info("Database initialized")

    # Start prediction logger
    await prediction_logger.start()
    
    # Create model manager (max 5 models in memory by default)
    max_models = int(os.getenv("MAX_MODELS_IN_MEMORY", 5))
    model_manager = ModelManager(max_models_in_memory=max_models)

    # Set service info metrics
    service_info.info({
        "version": "2.1.0",
        "max_models": str(max_models)
    })
    logger.info(
        "ML Serving Platform started",
        extra={"max_models": max_models}
    )

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("Shutting down Thrift ML Serving Platform")
    await prediction_logger.stop()
    logger.info("Shutdown complete")

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
        default_batch_size = int(os.getenv("DEFAULT_BATCH_SIZE", 32))
        default_batch_wait_ms = int(os.getenv("DEFAULT_BATCH_WAIT_MS", 50))
        batch_size = request.batch_size if request.batch_size is not None else default_batch_size
        batch_wait_ms = request.batch_wait_ms if request.batch_wait_ms is not None else default_batch_wait_ms

        result = model_manager.load_model(
            model_name=request.model_name,
            version=request.version,
            batch_size=batch_size,
            batch_wait_ms=batch_wait_ms
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error loading model: {e}", exc_info=True)
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
async def predict(model_name: str, version: str, request_body: PredictRequest, request: Request):
    """
    Make a prediction using a specific model version.
    
    The model must be loaded first via POST /models/load.
    
    Example:
        POST /models/iris/versions/v1/predict
        {
            "features": [5.1, 3.5, 1.4, 0.2]
        }
    """
    start_time = time.time()
    try:
        try:
            prediction = await model_manager.predict(
                model_name=model_name,
                version=version,
                features=request_body.features
            )
        except ValueError as e:
            # Auto-load on miss, then retry once
            if "not loaded" in str(e):
                default_batch_size = int(os.getenv("DEFAULT_BATCH_SIZE", 32))
                default_batch_wait_ms = int(os.getenv("DEFAULT_BATCH_WAIT_MS", 50))
                model_manager.load_model(
                    model_name=model_name,
                    version=version,
                    batch_size=default_batch_size,
                    batch_wait_ms=default_batch_wait_ms
                )
                prediction = await model_manager.predict(
                    model_name=model_name,
                    version=version,
                    features=request_body.features
                )
            else:
                raise
        latency_ms = (time.time() - start_time) * 1000

        # Record metrics
        predictions_total.labels(
            model_name=model_name,
            model_version=version
        ).inc()

        prediction_duration_seconds.labels(
            model_name=model_name,
            model_version=version
        ).observe(time.time() - start_time)

        # Log prediction asynchronously
        client_ip = request.client.host if request.client else None
        await prediction_logger.log(
            model_name=model_name,
            model_version=version,
            features=request_body.features,
            prediction=prediction,
            latency_ms=latency_ms,
            client_ip=client_ip
        )

        logger.info(
            "Prediction completed",
            extra={
                "model_name": model_name,
                "model_version": version,
                "latency_ms": latency_ms,
                "prediction": int(prediction)
            }
        )
        return PredictResponse(
            prediction=int(prediction),
            model_name=model_name,
            model_version=version
        )
    
    except ValueError as e:
        prediction_errors_total.labels(
            model_name=model_name,
            model_version=version,
            error_type="model_not_loaded"
        ).inc()
        logger.warning("Prediction failed: model not loaded",
                       extra={
                "model_name": model_name,
                "model_version": version}
        )
        raise HTTPException(status_code=404, detail=str(e))

    except Exception as e:
        prediction_errors_total.labels(
            model_name=model_name,
            model_version=version,
            error_type="prediction_error"
        ).inc()
        logger.error(
            "Prediction failed",
            extra={
                "model_name": model_name,
                "model_version": version,
                "error": str(e)
            },
            exc_info=True
        )
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
        "service": "Thrift ML Serving Platform",
        "version": "2.1.0",
        "features": [
            "Dynamic model loading",
            "Multi-model serving",
            "Automatic LRU eviction",
            "Batch processing",
            "Prometheus metrics",
            "Structured logging",
            "Request tracing"
        ],
        "endpoints": {
            "metrics": "GET /metrics",
            "load_model": "POST /models/load",
            "unload_model": "POST /models/unload",
            "list_models": "GET /models",
            "predict": "POST /models/{name}/versions/{version}/predict",
            "health": "GET /health"
        }
    }
