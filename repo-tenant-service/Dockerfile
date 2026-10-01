# Stage 1 — build from source (self-contained: the host has no Java/Maven,
# so build-and-deploy.sh must be able to `docker build` this directory
# without a prior `mvn package`).
FROM maven:3.9.6-eclipse-temurin-21 AS build
WORKDIR /app

# Dependency layer first — re-runs only when pom.xml changes.
COPY pom.xml ./
RUN mvn -B -q -DskipTests dependency:go-offline

COPY src ./src
RUN mvn -B -q -DskipTests package

# Stage 2 — runtime (JRE only)
FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
COPY --from=build /app/target/*.jar app.jar

ENTRYPOINT ["java", "-jar", "app.jar"]
EXPOSE 8085
