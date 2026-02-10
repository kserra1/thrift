package com.thrift.gateway.service;

import com.thrift.gateway.model.ModelLoadRequest;
import com.thrift.gateway.model.WorkerInfo;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.ReactiveRedisTemplate;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;

/**
 * Service that manages the model registry using Redis.
 * 
 * Key operations:
 * 1. getWorkerForModel() - Find which worker has a model, or assign one
 * 2. loadModelOnWorker() - Trigger model loading on a specific worker
 * 3. recordModelLoad() - Update registry when model is loaded
 * 4. selectLeastLoadedWorker() - Pick worker with fewest models
 */
@Slf4j
@Service
public class ModelRegistryService {

    private final ReactiveRedisTemplate<String, String> redisTemplate;
    private final WorkerHealthService workerHealthService;
    private final WebClient webClient;
    private final ConcurrentMap<String, Set<String>> workerModelCache = new ConcurrentHashMap<>();
    private final ConcurrentMap<String, Long> modelVerifiedAt = new ConcurrentHashMap<>();
    private static final long MODEL_VERIFY_TTL_MS = 30000;
    
    @Value("${model-registry.redis-key-prefix}")
    private String modelKeyPrefix;
    
    @Value("${model-registry.worker-load-key-prefix}")
    private String workerLoadKeyPrefix;
    
    @Value("${model-registry.ttl-seconds}")
    private long ttlSeconds;

    public ModelRegistryService(
            @Qualifier("reactiveRedisTemplate") ReactiveRedisTemplate<String, String> redisTemplate,
            WorkerHealthService workerHealthService,
            WebClient.Builder webClientBuilder) {
        this.redisTemplate = redisTemplate;
        this.workerHealthService = workerHealthService;
        this.webClient = webClientBuilder.build();
    }

    /**
     * Get the worker that has this model loaded, or assign one if not loaded anywhere.
     * 
     * This is the main routing logic:
     * 1. Check Redis if model is already assigned to a worker
     * 2. If yes, verify worker is still healthy
     * 3. If no, select least-loaded healthy worker and trigger model load
     */
    public Mono<WorkerInfo> getWorkerForModel(String modelName, String version) {
        String modelKey = getModelKey(modelName, version);
        
        return redisTemplate.opsForValue()
            .get(modelKey)
            .flatMap(workerId -> {
                // Model is assigned to a worker, verify it's healthy
                return workerHealthService.getWorkerById(workerId)
                    .flatMap(worker -> {
                        if (worker.isHealthy()) {
                            String modelKeyName = modelName + ":" + version;
                            Set<String> cachedModels = workerModelCache.get(workerId);
                            if (cachedModels != null && cachedModels.contains(modelKeyName)
                                && isRecentlyVerified(workerId, modelKeyName)) {
                                log.debug("Found model {}:{} on worker {} (cache hit)", modelName, version, workerId);
                                return Mono.just(worker);
                            }

                            // Cache miss or stale: attempt load on assigned worker
                            log.debug("Model {}:{} not in cache for {}, attempting load on assigned worker",
                                modelName, version, workerId);
                            return loadModelOnWorker(worker, modelName, version)
                                .then(Mono.fromCallable(() -> {
                                    workerModelCache.compute(workerId, (k, v) -> {
                                        Set<String> updated = v != null ? new HashSet<>(v) : new HashSet<>();
                                        updated.add(modelKeyName);
                                        return updated;
                                    });
                                    markVerified(workerId, modelKeyName);
                                    return worker;
                                }))
                                .onErrorResume(error -> {
                                    log.warn("Load failed on assigned worker {}, reassigning: {}",
                                        workerId, error.getMessage());
                                    return redisTemplate.opsForValue()
                                        .delete(modelKey)
                                        .then(assignModelToWorker(modelName, version));
                                });
                        } else {
                            // Worker is down, clear assignment and reassign
                            log.warn("Worker {} for model {}:{} is unhealthy, reassigning", 
                                workerId, modelName, version);
                            return redisTemplate.opsForValue()
                                .delete(modelKey)
                                .then(assignModelToWorker(modelName, version));
                        }
                    })
                    .switchIfEmpty(assignModelToWorker(modelName, version));
            })
            .switchIfEmpty(assignModelToWorker(modelName, version));
    }

    /**
     * Find the worker that currently has a model loaded without auto-assigning.
     * First checks Redis, then falls back to probing healthy workers.
     */
    public Mono<WorkerInfo> findWorkerWithModel(String modelName, String version) {
        String modelKey = getModelKey(modelName, version);

        return redisTemplate.opsForValue()
            .get(modelKey)
            .flatMap(workerId -> workerHealthService.getWorkerById(workerId))
            .switchIfEmpty(findWorkerByHealth(modelName, version));
    }

    /**
     * Find all healthy workers that currently have a model loaded.
     */
    public Flux<WorkerInfo> findWorkersWithModel(String modelName, String version) {
        String target = modelName + ":" + version;
        return workerHealthService.getHealthyWorkers()
            .flatMap(worker -> fetchWorkerModels(worker)
                .filter(models -> models.contains(target))
                .map(models -> worker));
    }

    private Mono<WorkerInfo> findWorkerByHealth(String modelName, String version) {
        String target = modelName + ":" + version;
        return workerHealthService.getHealthyWorkers()
            .flatMap(worker -> fetchWorkerModels(worker)
                .filter(models -> models.contains(target))
                .map(models -> worker))
            .next();
    }

    /**
     * Assign a model to the least-loaded worker and trigger loading.
     */
    private Mono<WorkerInfo> assignModelToWorker(String modelName, String version) {
        log.info("Assigning model {}:{} to a worker", modelName, version);
        
        return selectLeastLoadedWorker()
            .flatMap(worker -> {
                String modelKey = getModelKey(modelName, version);
                
                // Store assignment in Redis
                return redisTemplate.opsForValue()
                    .set(modelKey, worker.getId(), Duration.ofSeconds(ttlSeconds))
                    .then(incrementWorkerLoad(worker.getId()))
                    .then(loadModelOnWorker(worker, modelName, version))
                    .thenReturn(worker);
            });
    }

    /**
     * Select the worker with the fewest models loaded.
     */
    private Mono<WorkerInfo> selectLeastLoadedWorker() {
        return workerHealthService.getHealthyWorkers()
            .collectList()
            .flatMap(workers -> {
                if (workers.isEmpty()) {
                    return Mono.error(new RuntimeException("No healthy workers available"));
                }

                // For each worker, fetch its load and attach it, then pick the least-loaded
                return Flux.fromIterable(workers)
                    .flatMap(worker -> getWorkerLoad(worker.getId())
                        .map(load -> {
                            worker.setLoadedModels(load);
                            return worker;
                        }))
                    .collectList()
                    .map(list -> {
                        WorkerInfo leastLoaded = list.stream()
                            .min((w1, w2) -> Integer.compare(w1.getLoadedModels(), w2.getLoadedModels()))
                            .orElse(workers.get(0));

                        log.info("Selected least-loaded worker: {} (load: {})",
                            leastLoaded.getId(), leastLoaded.getLoadedModels());
                        return leastLoaded;
                    });
            });
    }

    /**
     * Get the number of models loaded on a worker.
     */
    private Mono<Integer> getWorkerLoad(String workerId) {
        String loadKey = workerLoadKeyPrefix + workerId;
        return redisTemplate.opsForValue()
            .get(loadKey)
            .map(Integer::parseInt)
            .defaultIfEmpty(0);
    }

    /**
     * Increment the load counter for a worker.
     */
    private Mono<Long> incrementWorkerLoad(String workerId) {
        String loadKey = workerLoadKeyPrefix + workerId;
        return redisTemplate.opsForValue()
            .increment(loadKey);
    }

    private Mono<Long> decrementWorkerLoad(String workerId) {
        String loadKey = workerLoadKeyPrefix + workerId;
        return redisTemplate.opsForValue()
            .increment(loadKey, -1);
    }

    /**
     * Remove model assignment and decrement worker load.
     */
    public Mono<Boolean> unassignModel(String modelName, String version, String workerId) {
        String modelKey = getModelKey(modelName, version);
        String modelKeyName = modelName + ":" + version;
        String verifiedKey = workerId + "|" + modelKeyName;
        return redisTemplate.opsForValue()
            .delete(modelKey)
            .then(decrementWorkerLoad(workerId))
            .doOnSuccess(v -> workerModelCache.computeIfPresent(workerId, (k, vset) -> {
                Set<String> updated = new HashSet<>(vset);
                updated.remove(modelKeyName);
                return updated;
            }))
            .doOnSuccess(v -> modelVerifiedAt.remove(verifiedKey))
            .thenReturn(true);
    }

    public Mono<Void> unassignModelForWorkers(String modelName, String version, List<String> workerIds) {
        String modelKey = getModelKey(modelName, version);
        String modelKeyName = modelName + ":" + version;
        return redisTemplate.opsForValue()
            .delete(modelKey)
            .thenMany(Flux.fromIterable(workerIds)
                .flatMap(this::decrementWorkerLoad))
            .doOnComplete(() -> workerIds.forEach(workerId ->
                workerModelCache.computeIfPresent(workerId, (k, vset) -> {
                    Set<String> updated = new HashSet<>(vset);
                    updated.remove(modelKeyName);
                    return updated;
                })
            ))
            .doOnComplete(() -> workerIds.forEach(workerId ->
                modelVerifiedAt.remove(workerId + "|" + modelKeyName)
            ))
            .then();
    }

    public Mono<List<String>> unloadModelGlobally(String modelName, String version, List<WorkerInfo> workers) {
        if (workers.isEmpty()) {
            return Mono.just(List.of());
        }

        List<String> unloaded = new ArrayList<>();
        return Flux.fromIterable(workers)
            .flatMap(worker -> unloadOnWorker(worker, modelName, version)
                .thenReturn(worker.getId()))
            .doOnNext(unloaded::add)
            .then(Mono.just(unloaded));
    }

    private Mono<Void> unloadOnWorker(WorkerInfo worker, String modelName, String version) {
        String url = worker.getBaseUrl() + "/models/unload";
        Map<String, String> payload = Map.of(
            "model_name", modelName,
            "version", version
        );
        return webClient.post()
            .uri(url)
            .bodyValue(payload)
            .retrieve()
            .bodyToMono(String.class)
            .doOnSuccess(resp -> log.info("Unloaded model {}:{} on {}", modelName, version, worker.getId()))
            .doOnError(err -> log.warn("Failed to unload model {}:{} on {}: {}", modelName, version, worker.getId(), err.getMessage()))
            .then();
    }

    /**
     * Trigger model loading on a specific worker by calling its /models/load endpoint.
     */
    private Mono<Void> loadModelOnWorker(WorkerInfo worker, String modelName, String version) {
        log.info("Triggering model load for {}:{} on worker {}", modelName, version, worker.getId());
        
        ModelLoadRequest request = new ModelLoadRequest(modelName, version, 32, 50);
        
        return webClient.post()
            .uri(worker.getBaseUrl() + "/models/load")
            .bodyValue(request)
            .retrieve()
            .bodyToMono(String.class)
            .doOnSuccess(response -> log.info("Successfully loaded model {}:{} on {}", 
                modelName, version, worker.getId()))
            .doOnError(error -> log.error("Failed to load model {}:{} on {}: {}", 
                modelName, version, worker.getId(), error.getMessage()))
            .then();
    }

    /**
     * Generate Redis key for a model.
     */
    private String getModelKey(String modelName, String version) {
        return modelKeyPrefix + modelName + ":" + version;
    }

    Mono<Set<String>> fetchWorkerModels(WorkerInfo worker) {
        String url = worker.getBaseUrl() + "/health";
        return webClient.get()
            .uri(url)
            .retrieve()
            .bodyToMono(String.class)
            .map(body -> {
                Set<String> models = new HashSet<>();
                try {
                    com.fasterxml.jackson.databind.JsonNode root =
                        new com.fasterxml.jackson.databind.ObjectMapper().readTree(body);
                    com.fasterxml.jackson.databind.JsonNode modelsNode = root.path("models");
                    if (modelsNode.isArray()) {
                        for (com.fasterxml.jackson.databind.JsonNode node : modelsNode) {
                            models.add(node.asText());
                        }
                    }
                } catch (Exception e) {
                    log.debug("Failed to parse /health from {}: {}", worker.getId(), e.getMessage());
                }
                return models;
            })
            .onErrorReturn(new HashSet<>());
    }

    public void updateWorkerModelCache(Map<String, Set<String>> modelsByWorker) {
        workerModelCache.clear();
        modelsByWorker.forEach((workerId, models) -> workerModelCache.put(workerId, new HashSet<>(models)));
        modelVerifiedAt.clear();
        long now = System.currentTimeMillis();
        modelsByWorker.forEach((workerId, models) -> {
            for (String model : models) {
                modelVerifiedAt.put(workerId + "|" + model, now);
            }
        });
    }

    private boolean isRecentlyVerified(String workerId, String modelKeyName) {
        Long ts = modelVerifiedAt.get(workerId + "|" + modelKeyName);
        return ts != null && (System.currentTimeMillis() - ts) < MODEL_VERIFY_TTL_MS;
    }

    private void markVerified(String workerId, String modelKeyName) {
        modelVerifiedAt.put(workerId + "|" + modelKeyName, System.currentTimeMillis());
    }
}
