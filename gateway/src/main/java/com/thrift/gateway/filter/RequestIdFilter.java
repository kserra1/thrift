package com.thrift.gateway.filter;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.http.HttpHeaders;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.util.UUID;

/**
 * Ensures every request has an X-Request-ID and propagates it downstream.
 */
@Component
public class RequestIdFilter implements GlobalFilter, Ordered {

    private static final Logger log = LoggerFactory.getLogger(RequestIdFilter.class);
    private static final String HEADER = "X-Request-ID";

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, org.springframework.cloud.gateway.filter.GatewayFilterChain chain) {
        String requestId = exchange.getRequest().getHeaders().getFirst(HEADER);
        if (requestId == null || requestId.isBlank()) {
            requestId = UUID.randomUUID().toString();
        }

        String finalRequestId = requestId;
        ServerWebExchange mutated = exchange.mutate()
            .request(r -> r.headers(headers -> {
                headers.remove(HEADER);
                headers.add(HEADER, finalRequestId);
            }))
            .build();

        mutated.getResponse().getHeaders().set(HEADER, finalRequestId);
        log.debug("RequestId assigned: {}", finalRequestId);

        return chain.filter(mutated);
    }

    @Override
    public int getOrder() {
        return -1;
    }
}
