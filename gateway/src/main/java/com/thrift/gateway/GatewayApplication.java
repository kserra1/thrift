package com.thrift.gateway;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.boot.ApplicationRunner;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.info.BuildProperties;
import org.springframework.beans.factory.ObjectProvider;

/**
 * Main application class for the ML serving gateway.
 * 
 * This gateway intelligently routes ML inference requests to workers
 * based on which worker has the requested model loaded in memory.
 */
@SpringBootApplication
@EnableScheduling
@Slf4j
public class GatewayApplication {

    public static void main(String[] args) {
        SpringApplication.run(GatewayApplication.class, args);
    }

    @Bean
    public ApplicationRunner versionBanner(ObjectProvider<BuildProperties> buildPropertiesProvider) {
        return args -> {
            BuildProperties buildProperties = buildPropertiesProvider.getIfAvailable();
            String name = buildProperties != null ? buildProperties.getName() : "thrift-gateway";
            String version = buildProperties != null ? buildProperties.getVersion() : "unknown";
            String time = buildProperties != null && buildProperties.getTime() != null
                ? buildProperties.getTime().toString()
                : "unknown";
            String javaVersion = System.getProperty("java.version", "unknown");
            String pid = java.lang.management.ManagementFactory.getRuntimeMXBean().getName();

            log.info("=== Gateway Build Info ===");
            log.info("app={} version={} builtAt={} java={} pid={}", name, version, time, javaVersion, pid);
            log.info("==========================");
        };
    }
}
