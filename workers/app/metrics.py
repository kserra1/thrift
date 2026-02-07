"""
Prometheus metrics for the ML serving platform.

This module defines all the metrics we track:
- Request counts and latency
- Model operations (load, unload, predict)
- Cache performance
- Resource usage
"""
from prometheus_client import Counter, Histogram, Gauge, Info
import time
from functools import wraps
from typing import Callable
import asyncio

# ============================================
# Request Metrics
# ============================================

# Total number of HTTP requests
http_requests_total = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status']
)

# Request latency distribution
http_request_duration_seconds = Histogram(
    'http_request_duration_seconds',
    'HTTP request latency',
    ['method', 'endpoint'],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
    # Buckets: 5ms, 10ms, 25ms, 50ms, 100ms, 250ms, 500ms, 1s, 2.5s, 5s, 10s
)

# ============================================
# Model Operation Metrics
# ============================================

# Total predictions made
predictions_total = Counter(
    'predictions_total',
    'Total predictions made',
    ['model_name', 'model_version']
)

# Prediction latency
prediction_duration_seconds = Histogram(
    'prediction_duration_seconds',
    'Prediction latency',
    ['model_name', 'model_version'],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5)
)

# Prediction errors
prediction_errors_total = Counter(
    'prediction_errors_total',
    'Total prediction errors',
    ['model_name', 'model_version', 'error_type']
)

# Model load operations
model_loads_total = Counter(
    'model_loads_total',
    'Total model load operations',
    ['model_name', 'model_version', 'status']
    # status: success, failure, cache_hit
)

# Model load time
model_load_duration_seconds = Histogram(
    'model_load_duration_seconds',
    'Model load time',
    ['model_name', 'model_version'],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)
)

# Model unload operations
model_unloads_total = Counter(
    'model_unloads_total',
    'Total model unload operations',
    ['model_name', 'model_version', 'reason']
    # reason: manual, lru_eviction
)

# ============================================
# Cache Metrics
# ============================================

# Currently loaded models
models_loaded_gauge = Gauge(
    'models_loaded_current',
    'Number of models currently loaded in memory'
)

# Cache capacity
models_cache_capacity = Gauge(
    'models_cache_capacity',
    'Maximum number of models that can be loaded'
)

# Cache hit rate
cache_hits_total = Counter(
    'cache_hits_total',
    'Total cache hits (model already loaded)'
)

cache_misses_total = Counter(
    'cache_misses_total',
    'Total cache misses (model needs to be loaded)'
)

# LRU evictions
cache_evictions_total = Counter(
    'cache_evictions_total',
    'Total LRU cache evictions'
)

# ============================================
# Batch Processing Metrics
# ============================================

# Batch size distribution
batch_size_histogram = Histogram(
    'batch_size',
    'Batch sizes used for inference',
    ['model_name', 'model_version'],
    buckets=(1, 2, 4, 8, 16, 32, 64, 128)
)

# Batch wait time
batch_wait_duration_seconds = Histogram(
    'batch_wait_duration_seconds',
    'Time requests wait to form a batch',
    ['model_name', 'model_version'],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1)
)

# ============================================
# System Info
# ============================================

# Service version info
service_info = Info(
    'service_info',
    'Service version and metadata'
)

# ============================================
# Decorator Utilities
# ============================================

def track_time(histogram: Histogram, labels: dict = None):
    """
    Decorator to track execution time of a function.
    
    Usage:
        @track_time(prediction_duration_seconds, {'model_name': 'iris', 'model_version': 'v1'})
        async def predict(...):
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start
                if labels:
                    histogram.labels(**labels).observe(duration)
                else:
                    histogram.observe(duration)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start
                if labels:
                    histogram.labels(**labels).observe(duration)
                else:
                    histogram.observe(duration)
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def track_counter(counter: Counter, labels: dict = None):
    """
    Decorator to increment a counter when function is called.
    
    Usage:
        @track_counter(predictions_total, {'model_name': 'iris', 'model_version': 'v1'})
        async def predict(...):
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            result = await func(*args, **kwargs)
            if labels:
                counter.labels(**labels).inc()
            else:
                counter.inc()
            return result
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            if labels:
                counter.labels(**labels).inc()
            else:
                counter.inc()
            return result
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator