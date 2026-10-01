# Stage 1 — build (uses JDK, thrown away after)
FROM eclipse-temurin:21-jdk-alpine AS builder
WORKDIR /app
COPY target/*.jar app.jar

# Extract layers for better caching
RUN java -Djarmode=layertools -jar app.jar extract

# Stage 2 — runtime (uses JRE only)
FROM eclipse-temurin:21-jre-alpine
WORKDIR /app

# Copy extracted layers (most stable layers first)
COPY --from=builder /app/dependencies/ ./
COPY --from=builder /app/spring-boot-loader/ ./
COPY --from=builder /app/snapshot-dependencies/ ./
COPY --from=builder /app/application/ ./

ENTRYPOINT ["java", "org.springframework.boot.loader.launch.JarLauncher"]
EXPOSE 8085
