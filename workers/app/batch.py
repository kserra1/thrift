import asyncio
import time
from collections import deque
from typing import Any, List
import numpy as np
import logging

logger = logging.getLogger(__name__)


class BatchProcessor:
    def __init__(self, model, max_batch_size: int = 32, max_wait_ms: int = 50):
        """
        Args:
            model: The ML model to run predictions on
            max_batch_size: Maximum number of requests to batch together
            max_wait_ms: Maximum time to wait for more requests (milliseconds)
        """
        self.model = model
        self.max_batch_size = max_batch_size
        self.max_wait_ms = max_wait_ms
        self.queue = deque()
        self.processing = False
        self.lock = asyncio.Lock()
        
    async def predict(self, features: List[float]) -> int:
        """
        Add prediction request to batch queue and wait for result.
        
        Returns:
            Predicted class (int)
        """
        # Create a future for this request
        future = asyncio.Future()
        
        async with self.lock:
            self.queue.append((features, future))
            queue_size = len(self.queue)
        
        # Start processing if not already running
        if not self.processing:
            asyncio.create_task(self._process_batch())
        
        # Wait for result
        result = await future
        return result
    
    async def _process_batch(self):
        """
        Process accumulated batch of requests.
        Waits max_wait_ms to collect more requests, then processes together.
        """
        self.processing = True
        
        # Wait to collect more requests (or until max_batch_size reached)
        await asyncio.sleep(self.max_wait_ms / 1000.0)
        
        async with self.lock:
            if not self.queue:
                self.processing = False
                return
            
            # Collect batch
            batch_size = min(len(self.queue), self.max_batch_size)
            batch = [self.queue.popleft() for _ in range(batch_size)]
        
        start_time = time.time()
        
        try:
            # Extract features and futures
            features_list = [item[0] for item in batch]
            futures_list = [item[1] for item in batch]
            
            # Stack into batch
            features_batch = np.array(features_list)
            
            # Process entire batch at once
            predictions = self.model.predict(features_batch)
            
            # Return results to each future
            for future, prediction in zip(futures_list, predictions):
                if not future.done():
                    future.set_result(int(prediction))
            
            duration_ms = (time.time() - start_time) * 1000
            logger.info(
                f"Processed batch of {batch_size} in {duration_ms:.1f}ms "
                f"({batch_size / (duration_ms / 1000):.0f} req/sec)"
            )
        
        except Exception as e:
            logger.error(f"Batch processing error: {e}")
            # Set exception on all futures
            for _, future in batch:
                if not future.done():
                    future.set_exception(e)
        
        self.processing = False
        
        # If more items in queue, process them
        if self.queue:
            asyncio.create_task(self._process_batch())