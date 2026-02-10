package com.thrift.gateway.model;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Request to load a model on a worker.
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class ModelLoadRequest {
    private String modelName;
    private String version;
    private int batchSize = 32;
    private int batchWaitMs = 50;
}