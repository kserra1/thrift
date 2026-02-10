package com.thrift.gateway.service;

import com.thrift.gateway.model.WorkerInfo;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.ReactiveRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.util.HashMap;
import java.util.Map;
import java.util.Set;

/**
 * Periodically reconciles Redis model assignments with actual worker state.
 */
@Service
public class ModelRegistryReconciler {

    private static final Logger log = LoggerFactory.getLogger(ModelRegistryReconciler.class);

    private final ReactiveRedisTemplate<String, String> redisTemplate;
    private final WorkerHealthService workerHealthService;
    private final ModelRegistryService modelRegistryService;

    @Value("${model-registry.redis-key-prefix}")
    private String modelKeyPrefix;

    @Value("${model-registry.worker-load-key-prefix}")
    private String workerLoadKeyPrefix;

    @Value("${model-registry.ttl-seconds}")
    private long ttlSeconds;

    public ModelRegistryReconciler(
            ReactiveRedisTemplate<String, String> redisTemplate,
            WorkerHealthService workerHealthService,
            ModelRegistryService modelRegistryService) {
        this.redisTemplate = redisTemplate;
        this.workerHealthService = workerHealthService;
        this.modelRegistryService = modelRegistryService;
    }

    /**
     * Every minute:
     * - Fetch models loaded on each healthy worker
     * - Ensure Redis assignments match actual models
     * - Update worker load counters
     */
    @Scheduled(fixedRate = 60000)
    public void reconcile() {
        log.debug("Reconciling model registry with worker state");

        workerHealthService.getHealthyWorkers()
            .flatMap(worker -> modelRegistryService.fetchWorkerModels(worker)
                .map(models -> Map.entry(worker, models)))
            .collectList()
            .flatMap(workerModels -> {
                Map<String, Set<String>> modelsByWorker = new HashMap<>();
                for (Map.Entry<WorkerInfo, Set<String>> entry : workerModels) {
                    modelsByWorker.put(entry.getKey().getId(), entry.getValue());
                }

                modelRegistryService.updateWorkerModelCache(modelsByWorker);

                return reconcileAssignments(modelsByWorker)
                    .then(updateWorkerLoads(modelsByWorker));
            })
            .doOnError(e -> log.warn("Registry reconcile failed: {}", e.getMessage()))
            .subscribe();
    }

    private Mono<Void> reconcileAssignments(Map<String, Set<String>> modelsByWorker) {
        String pattern = modelKeyPrefix + "*";

        return redisTemplate.keys(pattern)
            .flatMap(modelKey -> redisTemplate.opsForValue().get(modelKey)
                .flatMap(workerId -> {
                    String model = modelKey.substring(modelKeyPrefix.length());
                    Set<String> models = modelsByWorker.get(workerId);
                    if (models == null || !models.contains(model)) {
                        log.info("Clearing stale assignment {} -> {}", modelKey, workerId);
                        return redisTemplate.opsForValue().delete(modelKey).then();
                    }
                    return Mono.empty();
                }))
            .then(ensureAssignments(modelsByWorker));
    }

    private Mono<Void> ensureAssignments(Map<String, Set<String>> modelsByWorker) {
        return Flux.fromIterable(modelsByWorker.entrySet())
            .flatMap(entry -> Flux.fromIterable(entry.getValue())
                .flatMap(model -> {
                    String modelKey = modelKeyPrefix + model;
                    return redisTemplate.opsForValue()
                        .setIfAbsent(modelKey, entry.getKey(), Duration.ofSeconds(ttlSeconds))
                        .then();
                }))
            .then();
    }

    private Mono<Void> updateWorkerLoads(Map<String, Set<String>> modelsByWorker) {
        return Flux.fromIterable(modelsByWorker.entrySet())
            .flatMap(entry -> {
                String loadKey = workerLoadKeyPrefix + entry.getKey();
                int count = entry.getValue().size();
                return redisTemplate.opsForValue().set(loadKey, String.valueOf(count)).then();
            })
            .then();
    }
}
