package com.thrift.gateway.filter;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.thrift.gateway.model.WorkerInfo;
import com.thrift.gateway.service.ModelRegistryService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.cloud.gateway.filter.GatewayFilter;
import org.springframework.cloud.gateway.filter.factory.AbstractGatewayFilterFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.server.HandlerStrategies;
import org.springframework.web.reactive.function.server.ServerRequest;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;
import reactor.core.publisher.Flux;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.List;

import static org.springframework.cloud.gateway.support.ServerWebExchangeUtils.GATEWAY_REQUEST_URL_ATTR;
import static org.springframework.cloud.gateway.support.ServerWebExchangeUtils.cacheRequestBodyAndRequest;

/**
 * Routes model management requests (currently /models/unload) to the worker
 * that has the model assigned/loaded. Also clears the assignment on success.
 */
@Component
public class ModelManagementRoutingFilter extends AbstractGatewayFilterFactory<ModelManagementRoutingFilter.Config> {

    private static final Logger log = LoggerFactory.getLogger(ModelManagementRoutingFilter.class);

    private final ModelRegistryService modelRegistryService;
    private final ObjectMapper objectMapper;

    public ModelManagementRoutingFilter(ModelRegistryService modelRegistryService, ObjectMapper objectMapper) {
        super(Config.class);
        this.modelRegistryService = modelRegistryService;
        this.objectMapper = objectMapper;
    }

    @Override
    public GatewayFilter apply(Config config) {
        return (exchange, chain) -> cacheRequestBodyAndRequest(exchange, serverHttpRequest -> {
            ServerWebExchange cachedExchange = exchange.mutate().request(serverHttpRequest).build();
            ServerRequest serverRequest = ServerRequest.create(cachedExchange, HandlerStrategies.withDefaults().messageReaders());

            return serverRequest.bodyToMono(String.class)
                .defaultIfEmpty("")
                .flatMap(body -> {
                    String modelName;
                    String version;

                    try {
                        JsonNode root = objectMapper.readTree(body);
                        modelName = root.path("model_name").asText(null);
                        version = root.path("version").asText(null);
                    } catch (Exception e) {
                        return respondBadRequest(cachedExchange, "Invalid JSON body");
                    }

                    if (modelName == null || version == null) {
                        return respondBadRequest(cachedExchange, "model_name and version are required");
                    }

                    return modelRegistryService.findWorkersWithModel(modelName, version)
                        .collectList()
                        .flatMap(workers -> {
                            if (workers.isEmpty()) {
                                return respondNotFound(cachedExchange, "Model not found on any worker");
                            }
                            return unloadGlobally(cachedExchange, modelName, version, workers);
                        });
                })
                .onErrorResume(error -> {
                    log.error("Failed to route management request: {}", error.getMessage());
                    return Mono.error(new RuntimeException(error.getMessage()));
                });
        });
    }

    private Mono<Void> unloadGlobally(
            ServerWebExchange exchange,
            String modelName,
            String version,
            List<WorkerInfo> workers) {
        return modelRegistryService.unloadModelGlobally(modelName, version, workers)
            .flatMap(unloadedWorkers -> modelRegistryService
                .unassignModelForWorkers(modelName, version, unloadedWorkers)
                .then(writeJson(exchange, HttpStatus.OK, String.format(
                    "{\"status\":\"unloaded\",\"model_name\":\"%s\",\"version\":\"%s\",\"workers\":%s}",
                    modelName,
                    version,
                    toJsonArray(unloadedWorkers)
                ))));
    }

    private String toJsonArray(List<String> items) {
        StringBuilder sb = new StringBuilder();
        sb.append("[");
        for (int i = 0; i < items.size(); i++) {
            if (i > 0) {
                sb.append(",");
            }
            sb.append("\"").append(items.get(i)).append("\"");
        }
        sb.append("]");
        return sb.toString();
    }

    private Mono<Void> routeToWorkerAndUpdate(
            ServerWebExchange exchange,
            org.springframework.cloud.gateway.filter.GatewayFilterChain chain,
            WorkerInfo worker,
            String modelName,
            String version) {
        String path = exchange.getRequest().getURI().getPath();
        URI workerUri = URI.create(worker.getBaseUrl() + path);

        ServerHttpRequest request = exchange.getRequest().mutate().uri(workerUri).build();
        ServerWebExchange mutatedExchange = exchange.mutate().request(request).build();
        mutatedExchange.getAttributes().put(GATEWAY_REQUEST_URL_ATTR, workerUri);

        log.debug("Routing management request for {}:{} to {}", modelName, version, workerUri);

        return chain.filter(mutatedExchange)
            .then(Mono.defer(() -> {
                HttpStatusCode status = mutatedExchange.getResponse().getStatusCode();
                if (status != null && status.is2xxSuccessful()) {
                    return modelRegistryService.unassignModel(modelName, version, worker.getId()).then();
                }
                return Mono.empty();
            }));
    }

    private Mono<Void> respondBadRequest(ServerWebExchange exchange, String message) {
        exchange.getResponse().setStatusCode(HttpStatus.BAD_REQUEST);
        log.warn("Bad request for model management: {}", message);
        return exchange.getResponse().setComplete();
    }

    private Mono<Void> respondNotFound(ServerWebExchange exchange, String message) {
        exchange.getResponse().setStatusCode(HttpStatus.NOT_FOUND);
        log.warn("Not found: {}", message);
        return exchange.getResponse().setComplete();
    }

    private Mono<Void> writeJson(ServerWebExchange exchange, HttpStatus status, String json) {
        exchange.getResponse().setStatusCode(status);
        exchange.getResponse().getHeaders().set("Content-Type", "application/json");
        byte[] bytes = json.getBytes(StandardCharsets.UTF_8);
        DataBuffer buffer = exchange.getResponse().bufferFactory().wrap(bytes);
        return exchange.getResponse().writeWith(Flux.just(buffer));
    }

    public static class Config {
    }
}
