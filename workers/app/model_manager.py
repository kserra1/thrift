"""
Model manager for dynamic loading/unloading of multiple models.

This handles:
- Loading models from S3 on-demand
- Caching models in memory with LRU eviction
- Thread-safe access to models
- BatchProcessor per model for efficient inference
"""
import tempfile
import os
from typing import Dict, Optional, Tuple
from collections import OrderedDict
import joblib
from threading import Lock

from .storage import ModelStorage
from .database import SessionLocal, ModelMetadata
from .batch import BatchProcessor

from .metrics import(
    model_loads_total,
    model_load_duration_seconds,
    model_unloads_total,
    models_loaded_gauge,
    models_cache_capacity,
    cache_hits_total,
    cache_misses_total,
    cache_evictions_total
)
from .logging_config import get_logger
import time 
logger = get_logger(__name__)



class ModelManager:
    """Manages multiple models with dynamic loading and LRU caching."""
    
    def __init__(self, max_models_in_memory: int = 5):
        """
        Args:
            max_models_in_memory: Maximum number of models to keep loaded.
                When exceeded, least recently used models are evicted.
        """
        self.max_models = max_models_in_memory
        self.storage = ModelStorage()
        
        # Cache structure: {(model_name, version): (model, batch_processor, metadata)}
        # Using OrderedDict for LRU tracking
        self._cache: OrderedDict[Tuple[str, str], Tuple[object, BatchProcessor, dict]] = OrderedDict()
        self._lock = Lock()  # Thread-safe access

        # Set cache capacity metric
        models_cache_capacity.set(max_models_in_memory)
        
        logger.info(f"ModelManager initialized (max_models={max_models_in_memory})")
    
    def _evict_lru(self):
        """Remove the least recently used model to free memory."""
        if not self._cache:
            return
        
        # OrderedDict maintains insertion order; first item is least recently used
        lru_key, (model, processor, metadata) = self._cache.popitem(last=False)
        model_name, version = lru_key

        # Update metrics
        cache_evictions_total.inc()
        model_unloads_total.labels(
            model_name=model_name,
            model_version=version,
            reason="lru_eviction"
        ).inc()
        models_loaded_gauge.set(len(self._cache))
        
        logger.info(f"Evicted LRU model: {model_name}:{version}")
        
        # Cleanup (model will be garbage collected)
        del model
        del processor
    
    def _move_to_end(self, key: Tuple[str, str]):
        """Mark model as recently used by moving to end of OrderedDict."""
        if key in self._cache:
            self._cache.move_to_end(key)
    
    def is_loaded(self, model_name: str, version: str) -> bool:
        """Check if a model is currently loaded in memory."""
        with self._lock:
            return (model_name, version) in self._cache
    
    def get_loaded_models(self) -> list:
        """Return list of currently loaded models."""
        with self._lock:
            return [
                {
                    "model_name": name,
                    "version": ver,
                    "framework": meta.get("framework"),
                    "metadata": meta.get("model_metadata")
                }
                for (name, ver), (_, _, meta) in self._cache.items()
            ]
    
    def load_model(
        self,
        model_name: str,
        version: str,
        batch_size: int = 32,
        batch_wait_ms: int = 50
    ) -> dict:
        """
        Load a model from the registry into memory.
        
        Returns:
            dict with status and model info
        
        Raises:
            ValueError: if model not found in registry
            Exception: if download/load fails
        """
        start_time = time.time()
        with self._lock:
            key = (model_name, version)
            
            # Already loaded? Just mark as recently used
            if key in self._cache:
                self._move_to_end(key)
                cache_hits_total.inc()
                model_loads_total.labels(
                    model_name=model_name,
                    model_version=version,
                    status="cache_hit"
                ).inc()
                logger.info(f"Model {model_name}:{version} already loaded (cache hit)")
                return {
                    "status": "already_loaded",
                    "model_name": model_name,
                    "version": version,
                    "message": "Model was already in memory"
                }
            cache_misses_total.inc()
            
            # Get model metadata from database
            db = SessionLocal()
            try:
                db_metadata = db.query(ModelMetadata).filter(
                    ModelMetadata.model_name == model_name,
                    ModelMetadata.version == version
                ).first()
                
                if not db_metadata:
                    raise ValueError(
                        f"Model {model_name}:{version} not found in registry. "
                        "Register it first with: python scripts/register_model.py"
                    )
                
                s3_path = db_metadata.s3_path
                framework = db_metadata.framework
                model_metadata = db_metadata.model_metadata or {}
                
            finally:
                db.close()
            
            # Download from S3 to temporary file
            logger.info(f"Loading {model_name}:{version} from S3: {s3_path}")
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pkl') as tmp:
                local_path = tmp.name
            
            try:
                self.storage.download_model(s3_path, local_path)
                
                # Load the model (currently supports joblib/pickle)
                # TODO: Add support for PyTorch, TensorFlow, ONNX
                model = joblib.load(local_path)
                
                # Create batch processor for this model
                batch_processor = BatchProcessor(
                    model,
                    max_batch_size=batch_size,
                    max_wait_ms=batch_wait_ms
                )
                
                # Evict LRU model if at capacity
                if len(self._cache) >= self.max_models:
                    logger.info(f"Cache full ({len(self._cache)}/{self.max_models}), evicting LRU")
                    self._evict_lru()
                
                # Add to cache
                self._cache[key] = (
                    model,
                    batch_processor,
                    {
                        "framework": framework,
                        "model_metadata": model_metadata,
                        "s3_path": s3_path
                    }
                )

                # Update metrics
                duration = time.time() - start_time
                models_loaded_gauge.set(len(self._cache))
                model_loads_total.labels(
                    model_name=model_name,
                    model_version=version,
                    status="success"
                ).inc()
                model_load_duration_seconds.labels(
                    model_name=model_name,
                    model_version=version
                ).observe(duration)
                
                logger.info(
                    "Model loaded successfully",
                    extra={
                        "model_name": model_name,
                        "model_version": version,
                        "duration_ms": duration * 1000,
                        "cache_size": len(self._cache)
                    }
                )
                
                return {
                    "status": "loaded",
                    "model_name": model_name,
                    "version": version,
                    "framework": framework,
                    "metadata": model_metadata,
                    "cache_size": len(self._cache)
                }
            except Exception as e:
                model_loads_total.labels(
                    model_name=model_name,
                    model_version=version,
                    status="failure"
                ).inc()
                logger.error(
                    "Failed to load model",
                    extra={
                        "model_name": model_name,
                        "model_version": version,
                        "error": str(e)
                    },  
                    exc_info=True
                )
                raise
            finally:
                # Clean up temp file
                if os.path.exists(local_path):
                    os.remove(local_path)
    
    def unload_model(self, model_name: str, version: str) -> dict:
        """
        Manually unload a model from memory.
        
        Returns:
            dict with status
        """
        with self._lock:
            key = (model_name, version)
            
            if key not in self._cache:
                return {
                    "status": "not_loaded",
                    "model_name": model_name,
                    "version": version,
                    "message": "Model was not in memory"
                }
            
            # Remove from cache
            model, processor, metadata = self._cache.pop(key)
            del model
            del processor

            # Update metrics
            models_loaded_gauge.set(len(self._cache))
            model_unloads_total.labels(
                model_name=model_name,
                model_version=version,
                reason="manual"
            ).inc()
            
            logger.info(
                "Model unloaded successfully",
                extra={
                    "model_name": model_name,
                    "model_version": version,
                    "cache_size": len(self._cache)
                }
            )
            
            return {
                "status": "unloaded",
                "model_name": model_name,
                "version": version,
                "cache_size": len(self._cache)
            }
    
    async def predict(
        self,
        model_name: str,
        version: str,
        features: list
    ) -> int:
        """
        Make a prediction using a loaded model.
        
        Args:
            model_name: Name of the model
            version: Version of the model
            features: Input features for prediction
        
        Returns:
            Prediction result
        
        Raises:
            ValueError: if model not loaded
        """
        with self._lock:
            key = (model_name, version)
            
            if key not in self._cache:
                raise ValueError(
                    f"Model {model_name}:{version} not loaded. "
                    f"Load it first with POST /models/load"
                )
            
            # Mark as recently used
            self._move_to_end(key)
            
            # Get batch processor
            _, batch_processor, _ = self._cache[key]
        
        # Make prediction (release lock during async operation)
        prediction = await batch_processor.predict(features)
        return prediction