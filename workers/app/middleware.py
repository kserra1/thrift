"""
Middleware for request tracking and metrics.

This middleware:
- Assigns a correlation ID to each request
- Tracks request latency
- Logs all requests
- Counts requests by status code
"""
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
import time
from .logging_config import set_correlation_id, get_logger
from .metrics import http_requests_total, http_request_duration_seconds

logger = get_logger(__name__)


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """
    Middleware that adds observability to all requests.
    
    For each request:
    1. Generate correlation ID
    2. Log request start
    3. Track execution time
    4. Record metrics
    5. Log request completion
    """
    
    async def dispatch(self, request: Request, call_next):
        # Generate correlation ID (or use X-Request-ID header if provided)
        correlation_id = request.headers.get("X-Request-ID")
        correlation_id = set_correlation_id(correlation_id)
        
        # Add correlation ID to response headers
        request.state.correlation_id = correlation_id
        
        # Track start time
        start_time = time.time()
        
        # Log request start
        logger.info(
            "Request started",
            extra={
                "method": request.method,
                "path": request.url.path,
                "client": request.client.host if request.client else "unknown"
            }
        )
        
        # Process request
        try:
            response = await call_next(request)
            
            # Calculate duration
            duration = time.time() - start_time
            
            # Record metrics
            http_requests_total.labels(
                method=request.method,
                endpoint=request.url.path,
                status=response.status_code
            ).inc()
            
            http_request_duration_seconds.labels(
                method=request.method,
                endpoint=request.url.path
            ).observe(duration)
            
            # Log request completion
            logger.info(
                "Request completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration * 1000
                }
            )
            
            # Add correlation ID to response headers
            response.headers["X-Request-ID"] = correlation_id
            
            return response
        
        except Exception as e:
            # Log errors
            duration = time.time() - start_time
            
            logger.error(
                "Request failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "error": str(e),
                    "duration_ms": duration * 1000
                },
                exc_info=True
            )
            
            # Still record metrics for failed requests
            http_requests_total.labels(
                method=request.method,
                endpoint=request.url.path,
                status=500
            ).inc()
            
            raise