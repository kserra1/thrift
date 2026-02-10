package com.thrift.gateway.config;

import com.thrift.gateway.filter.ModelRoutingFilter;
import com.thrift.gateway.filter.ModelManagementRoutingFilter;
import org.springframework.cloud.gateway.route.RouteLocator;
import org.springframework.cloud.gateway.route.builder.RouteLocatorBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Gateway route configuration.
 * 
 * Defines all the routes and applies appropriate filters:
 * - Model prediction requests: Use ModelRoutingFilter for smart routing
 * - Other requests: Pass through to any worker (round-robin)
 */
@Configuration
public class RouteConfig {

    @Bean
    public RouteLocator customRouteLocator(
            RouteLocatorBuilder builder,
            ModelRoutingFilter modelRoutingFilter,
            ModelManagementRoutingFilter modelManagementRoutingFilter) {
        
        return builder.routes()
            // Route for model predictions - uses smart routing
        .route("model_predict", r -> r
            .path("/models/{model}/versions/{version}/predict")
            .filters(f -> f.filter(modelRoutingFilter.apply(new ModelRoutingFilter.Config())))
            .uri("http://thrift-worker-service"))
        
        // Route for model operations - also uses smart routing
        .route("model_operations", r -> r
            .path("/models/{model}/versions/{version}/**")
            .filters(f -> f.filter(modelRoutingFilter.apply(new ModelRoutingFilter.Config())))
            .uri("http://thrift-worker-service"))

            // Route for model unload - routes to the worker that owns the model
            .route("model_unload", r -> r
                .path("/models/unload")
                .filters(f -> f.filter(modelManagementRoutingFilter.apply(new ModelManagementRoutingFilter.Config())))
                .uri("http://thrift-worker-service"))
        
            
            // Route for general model management - round-robin to any worker
            .route("model_management", r -> r
                .path("/models/**")
                .uri("http://thrift-worker-service"))
            
            // Route for health and metrics - any worker
            .route("health", r -> r
                .path("/health", "/metrics")
                .uri("lb://thrift-worker-service"))
            
            // Fallback route
            .route("fallback", r -> r
                .path("/**")
                .uri("lb://thrift-worker-service"))
            
            .build();
    }
}
