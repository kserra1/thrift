package com.thrift.gateway.service;

import com.thrift.gateway.model.WorkerInfo;
import io.kubernetes.client.openapi.ApiClient;
import io.kubernetes.client.openapi.ApiException;
import io.kubernetes.client.openapi.Configuration;
import io.kubernetes.client.openapi.apis.CoreV1Api;
import io.kubernetes.client.openapi.models.V1Endpoints;
import io.kubernetes.client.util.Config;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import jakarta.annotation.PostConstruct;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;

/**
 * Service that tracks the health of worker instances.
 * 
 * In Kubernetes: Discovers workers via Endpoints API
 * Standalone: Uses static worker list
 * 
 * Periodically health-checks all workers and maintains a registry.
 */
@Slf4j
@Service
public class WorkerHealthService {

    private final WebClient webClient;
    private final ConcurrentMap<String, WorkerInfo> workerRegistry = new ConcurrentHashMap<>();
    
    @Value("${workers.kubernetes.namespace:thrift}")
    private String k8sNamespace;
    
    @Value("${workers.kubernetes.service:thrift-worker-service}")
    private String k8sService;
    
    @Value("${workers.kubernetes.port:80}")
    private int k8sServicePort; 

    @Value("${workers.kubernetes.targetPort:8000}")
    private int k8sTargetPort;   
    
    private CoreV1Api k8sApi;
    private boolean isKubernetes = false;

    public WorkerHealthService(WebClient.Builder webClientBuilder) {
        this.webClient = webClientBuilder.build();
    }

    @PostConstruct
    public void init() {
        try {
            // Try to initialize Kubernetes client
            ApiClient client = Config.defaultClient();
            Configuration.setDefaultApiClient(client);
            k8sApi = new CoreV1Api();
            isKubernetes = true;
            log.info("Running in Kubernetes v2, will use service discovery");
        } catch (Exception e) {
            log.info("Not running in Kubernetes, will use static worker list");
            // Load static workers from config
            workerRegistry.put("localhost:8000", 
                new WorkerInfo("localhost", 8000, true, 0));
        }
        
        // Initial discovery
        discoverWorkers();
    }

    /**
     * Discover workers from Kubernetes Endpoints or static config.
     * Runs every 30 seconds to pick up new pods.
     */
    @Scheduled(fixedRate = 30000)
    public void discoverWorkers() {
        if (isKubernetes) {
            discoverWorkersFromKubernetes();
        }
        // Static workers are already loaded in init()
    }

    /**
     * Discover workers from Kubernetes Endpoints API.
     * This gives us the actual pod IPs that are ready.
     */
    private void discoverWorkersFromKubernetes() {
        try {
            V1Endpoints endpoints = k8sApi.readNamespacedEndpoints(
                k8sService, k8sNamespace, null);
            
            List<WorkerInfo> discovered = new ArrayList<>();
            
            if (endpoints.getSubsets() != null) {
                endpoints.getSubsets().forEach(subset -> {
                    if (subset.getAddresses() != null) {
                        subset.getAddresses().forEach(address -> {
                            String host = address.getIp();
                            WorkerInfo worker = new WorkerInfo(host, k8sTargetPort, true, 0);
                            discovered.add(worker);
                        });
                    }
                });
            }
            
            log.debug("Discovered {} workers from Kubernetes", discovered.size());
            
            // Update registry
            ConcurrentMap<String, WorkerInfo> newRegistry = new ConcurrentHashMap<>();
            discovered.forEach(worker -> {
                newRegistry.put(worker.getId(), worker);
            });
            workerRegistry.clear();
            workerRegistry.putAll(newRegistry);
            
        } catch (ApiException e) {
            log.error("Failed to discover workers from Kubernetes: {}", e.getMessage());
        }
    }

    /**
     * Health check all workers.
     * Runs every 10 seconds.
     */
    @Scheduled(fixedRate = 10000)
    public void healthCheckWorkers() {
        log.info("Healthcheck workers triggered");
    log.debug("Running health checks on {} workers", workerRegistry.size());
        workerRegistry.values().forEach(worker -> {
            log.debug("Checking health of worker: {}", worker.getId());
            checkWorkerHealth(worker)
            .subscribe(
                healthy -> {
                    worker.setHealthy(healthy);
                    log.info("Worker {} health: {}", worker.getId(), healthy);
                },
                error -> {
                    log.warn("Health check failed for {}: {}", worker.getId(), error.getMessage());
                    worker.setHealthy(false);
                }
            );
        });
    }

    /**
     * Check if a single worker is healthy by calling its /health endpoint.
     */
    private Mono<Boolean> checkWorkerHealth(WorkerInfo worker) {
        String healthUrl = worker.getBaseUrl() + "/health";
        log.debug("Checking health of worker {} at {}", worker.getId(), healthUrl);

        return webClient.get()
            .uri(worker.getBaseUrl() + "/health")
            .retrieve()
            .bodyToMono(String.class)
            .map(response ->{
                log.debug("Received health response from worker {}: {}", worker.getId(), response);
                return true;
            })
            .onErrorReturn(false)
            .timeout(java.time.Duration.ofSeconds(2))
            .doOnError(error -> log.debug("Health check failed for {}: {}", 
                worker.getId(), error.getMessage()));
    }

    /**
     * Get all healthy workers.
     */
    public Flux<WorkerInfo> getHealthyWorkers() {
        return Flux.fromIterable(workerRegistry.values())
            .filter(WorkerInfo::isHealthy);
    }

    /**
     * Get a specific worker by ID.
     */
    public Mono<WorkerInfo> getWorkerById(String workerId) {
        WorkerInfo worker = workerRegistry.get(workerId);
        return worker != null ? Mono.just(worker) : Mono.empty();
    }
}