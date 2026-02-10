package com.thrift.gateway.model;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Represents a worker instance in the cluster.
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class WorkerInfo {
    private String host;
    private int port;
    private boolean healthy;
    private int loadedModels;
    
    public String getBaseUrl() {
        return String.format("http://%s:%d", host, port);
    }
    
    public String getId() {
        return String.format("%s:%d", host, port);
    }
}