package com.thrift.gateway.filter;

import com.thrift.gateway.model.WorkerInfo;
import com.thrift.gateway.service.ModelRegistryService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cloud.gateway.filter.GatewayFilter;
import org.springframework.cloud.gateway.filter.factory.AbstractGatewayFilterFactory;
import org.springframework.stereotype.Component;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.net.URI;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.springframework.cloud.gateway.support.ServerWebExchangeUtils.GATEWAY_REQUEST_URL_ATTR;

/**
 * Gateway filter that routes requests to the worker that has the requested model.
 * 
 * This filter:
 * 1. Extracts model name and version from the request path
 * 2. Looks up which worker has that model (or assigns one)
 * 3. Modifies the request to route to that specific worker
 */
@Slf4j
@Component
public class ModelRoutingFilter extends AbstractGatewayFilterFactory<ModelRoutingFilter.Config> {

    private final ModelRegistryService modelRegistryService;
    
    // Regex to extract model and version from path: /models/{model}/versions/{version}/predict
    private static final Pattern MODEL_PATH_PATTERN = 
        Pattern.compile("/models/([^/]+)/versions/([^/]+)/");

    public ModelRoutingFilter(ModelRegistryService modelRegistryService) {
        super(Config.class);
        this.modelRegistryService = modelRegistryService;
    }

    @Override
    public GatewayFilter apply(Config config) {
        return (exchange, chain) -> {
            String path = exchange.getRequest().getURI().getPath();
            
            // Extract model name and version from path
            Matcher matcher = MODEL_PATH_PATTERN.matcher(path);
            if (!matcher.find()) {
                return chain.filter(exchange);
            }
            
            String modelName = matcher.group(1);
            String version = matcher.group(2);
            
            log.debug("Routing request for model {}:{}", modelName, version);
            
            // Get worker for this model
            return modelRegistryService.getWorkerForModel(modelName, version)
                .flatMap(worker -> {
                    // CHANGE THIS SECTION:
                    // Extract the action from the path (predict, load, etc.)
                    String action = path.substring(path.lastIndexOf("/") + 1);
                    
                    // Map gateway path to worker path
                    String workerPath;
                    if (action.equals("load")) {
                        workerPath = "/models/load";  // Worker's load endpoint
                    } else if (action.equals("predict")) {
                        workerPath = "/models/" + modelName + "/versions/" + version + "/predict";
                    } else {
                        workerPath = path;  // Keep original for unknown actions
                    }
                    
                    URI workerUri = URI.create(worker.getBaseUrl() + workerPath);
                    ServerHttpRequest request = exchange.getRequest().mutate().uri(workerUri).build();
                    ServerWebExchange mutatedExchange = exchange.mutate().request(request).build();
                    mutatedExchange.getAttributes().put(GATEWAY_REQUEST_URL_ATTR, workerUri);
                    
                    log.debug("Routing to worker {} at {}", worker.getId(), workerUri);
                    
                    return chain.filter(mutatedExchange);
                })
                .onErrorResume(error -> {
                    log.error("Failed to route request for model {}:{}: {}", 
                        modelName, version, error.getMessage());
                    return Mono.error(new RuntimeException(
                        "Failed to find available worker for model " + modelName + ":" + version));
                });
        };
    }

    public static class Config {
        // Empty config class for now, can add config options later
    }
}
