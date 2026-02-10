# Multi-stage build for smaller image

# Stage 1: Build
FROM maven:3.9-eclipse-temurin-17 AS builder
WORKDIR /app

# Copy pom and download dependencies (cached layer)
COPY pom.xml .
RUN mvn dependency:go-offline -B

# Copy source and build
COPY src ./src
RUN mvn package -DskipTests -B

# Stage 2: Runtime
# Use a non-alpine Temurin runtime image. The alpine variant is not available for all platforms
# (especially on Apple Silicon / M1) which caused the build "no match for platform in manifest" error.
# Use the standard multi-arch Temurin runtime which works on amd64/arm64.
FROM eclipse-temurin:17-jre
WORKDIR /app

# Create non-root user
RUN set -eux; \
    # Prefer groupadd/useradd (Debian/Ubuntu based images). Fall back to addgroup/adduser when missing.
    if command -v groupadd >/dev/null 2>&1 && command -v useradd >/dev/null 2>&1; then \
        groupadd -r spring || true; \
        useradd -r -g spring -s /usr/sbin/nologin -M spring || true; \
    elif command -v addgroup >/dev/null 2>&1 && command -v adduser >/dev/null 2>&1; then \
        addgroup -S spring || true; \
        adduser -S spring -G spring || true; \
    else \
        echo "No user/group management commands found; continuing as root"; \
    fi
USER spring:spring

# Copy JAR from builder
COPY --from=builder /app/target/*.jar app.jar

# Expose port
EXPOSE 8080

# Install curl for the healthcheck and keep running as root for the install step
USER root:root
RUN set -eux; apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Health check (uses curl)
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8080/actuator/health || exit 1

# Switch to non-root user for runtime
USER spring:spring

# Run
ENTRYPOINT ["java", "-jar", "app.jar"]