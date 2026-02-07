"""
Async prediction logging to database.

Logs predictions in the background so they don't slow down the API response.
"""
import asyncio
from datetime import datetime
from typing import List, Any
from sqlalchemy.orm import Session
from .database import SessionLocal, PredictionLog
from .logging_config import get_logger, get_correlation_id

logger = get_logger(__name__)


class PredictionLoggerService:
    """
    Service for logging predictions to database asynchronously.
    
    Usage:
        await prediction_logger.log(
            model_name="iris",
            model_version="v1",
            features=[5.1, 3.5, 1.4, 0.2],
            prediction=0,
            latency_ms=12.3
        )
    """
    
    def __init__(self):
        self.queue = asyncio.Queue()
        self.worker_task = None
    
    async def start(self):
        """Start background worker."""
        self.worker_task = asyncio.create_task(self._worker())
        logger.info("Prediction logger started")
    
    async def stop(self):
        """Stop background worker."""
        if self.worker_task:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass
        logger.info("Prediction logger stopped")
    
    async def log(
        self,
        model_name: str,
        model_version: str,
        features: List[float],
        prediction: Any,
        latency_ms: float,
        batch_size: int = 1,
        client_ip: str = None
    ):
        """
        Queue a prediction log entry.
        
        This is non-blocking - the log is written in the background.
        """
        log_entry = {
            "correlation_id": get_correlation_id(),
            "model_name": model_name,
            "model_version": model_version,
            "input_features": features,
            "prediction": prediction,
            "latency_ms": latency_ms,
            "batch_size": batch_size,
            "client_ip": client_ip,
            "created_at": datetime.utcnow()
        }
        
        await self.queue.put(log_entry)
    
    async def _worker(self):
        """
        Background worker that writes logs to database.
        
        Batches writes for efficiency.
        """
        batch = []
        batch_size = 100
        flush_interval = 5.0  # Flush every 5 seconds
        last_flush = asyncio.get_event_loop().time()
        
        while True:
            try:
                # Get next log entry with timeout
                try:
                    entry = await asyncio.wait_for(
                        self.queue.get(),
                        timeout=1.0
                    )
                    batch.append(entry)
                except asyncio.TimeoutError:
                    pass
                
                # Flush if batch is full or time interval passed
                now = asyncio.get_event_loop().time()
                should_flush = (
                    len(batch) >= batch_size or
                    (batch and now - last_flush >= flush_interval)
                )
                
                if should_flush:
                    await self._flush_batch(batch)
                    batch = []
                    last_flush = now
            
            except asyncio.CancelledError:
                # Flush remaining logs before stopping
                if batch:
                    await self._flush_batch(batch)
                raise
            
            except Exception as e:
                logger.error(
                    "Error in prediction logger worker",
                    extra={"error": str(e)},
                    exc_info=True
                )
                # Continue running even if there's an error
    
    async def _flush_batch(self, batch: List[dict]):
        """Write batch of logs to database."""
        if not batch:
            return
        
        db = SessionLocal()
        try:
            # Bulk insert
            logs = [PredictionLog(**entry) for entry in batch]
            db.bulk_save_objects(logs)
            db.commit()
            
            logger.debug(
                "Flushed prediction logs",
                extra={"count": len(batch)}
            )
        
        except Exception as e:
            db.rollback()
            logger.error(
                "Failed to write prediction logs",
                extra={"error": str(e), "count": len(batch)},
                exc_info=True
            )
        
        finally:
            db.close()


# Global instance
prediction_logger = PredictionLoggerService()