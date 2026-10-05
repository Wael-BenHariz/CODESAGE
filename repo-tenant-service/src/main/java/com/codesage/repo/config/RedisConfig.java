package com.codesage.repo.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnBean;
import org.springframework.cache.Cache;
import org.springframework.cache.CacheManager;
import org.springframework.cache.annotation.CachingConfigurer;
import org.springframework.cache.annotation.EnableCaching;
import org.springframework.cache.interceptor.CacheErrorHandler;
import org.springframework.cache.interceptor.CacheResolver;
import org.springframework.cache.interceptor.KeyGenerator;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.cache.RedisCacheConfiguration;
import org.springframework.data.redis.cache.RedisCacheManager;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.data.redis.serializer.GenericJackson2JsonRedisSerializer;
import org.springframework.data.redis.serializer.RedisSerializationContext;
import org.springframework.data.redis.serializer.StringRedisSerializer;

import java.time.Duration;
import java.util.HashMap;
import java.util.Map;

/**
 * Redis-backed caching with a LENIENT error handler.
 *
 * WHY lenient: enabling/disabling a repo must never fail because Redis is
 * unreachable — a cache miss or a failed cache write degrades to "no cache"
 * (the method body still runs) instead of throwing into the request.
 */
@Configuration
@EnableCaching
@ConditionalOnBean(RedisConnectionFactory.class)
public class RedisConfig implements CachingConfigurer {

    @Value("${app.cache.ttl.repo-quota-seconds}")
    private long repoQuotaTtl;

    @Value("${app.cache.ttl.active-repo-namespaces-seconds}")
    private long activeRepoNamespacesTtl;

    @Value("${app.cache.ttl.default-seconds}")
    private long defaultTtl;

    @Bean
    public RedisCacheManager cacheManager(RedisConnectionFactory factory) {
        RedisCacheConfiguration base = buildConfig(Duration.ofSeconds(defaultTtl));

        Map<String, RedisCacheConfiguration> perCacheConfigs = new HashMap<>();
        perCacheConfigs.put("repoQuota", buildConfig(Duration.ofSeconds(repoQuotaTtl)));
        perCacheConfigs.put("activeRepoNamespaces", buildConfig(Duration.ofSeconds(activeRepoNamespacesTtl)));

        return RedisCacheManager.builder(factory)
                .cacheDefaults(base)
                .withInitialCacheConfigurations(perCacheConfigs)
                .build();
    }

    private RedisCacheConfiguration buildConfig(Duration ttl) {
        return RedisCacheConfiguration.defaultCacheConfig()
                .entryTtl(ttl)
                .serializeValuesWith(RedisSerializationContext.SerializationPair
                        .fromSerializer(new GenericJackson2JsonRedisSerializer()))
                .disableCachingNullValues();
    }

    @Bean
    public RedisTemplate<String, Object> redisTemplate(RedisConnectionFactory factory) {
        RedisTemplate<String, Object> template = new RedisTemplate<>();
        template.setConnectionFactory(factory);
        template.setKeySerializer(new StringRedisSerializer());
        template.setValueSerializer(new GenericJackson2JsonRedisSerializer());
        template.setHashKeySerializer(new StringRedisSerializer());
        template.setHashValueSerializer(new GenericJackson2JsonRedisSerializer());
        return template;
    }

    // ── CachingConfigurer — only the error handler is customized; null means
    //    "use the default / the CacheManager bean declared above". ──────────

    @Override
    public CacheManager cacheManager() {
        return null;
    }

    @Override
    public KeyGenerator keyGenerator() {
        return null;
    }

    @Override
    public CacheResolver cacheResolver() {
        return null;
    }

    /** Redis down = degraded caching, never a failed request. */
    @Override
    public CacheErrorHandler errorHandler() {
        return new CacheErrorHandler() {
            @Override
            public void handleCacheGetError(RuntimeException exception, Cache cache, Object key) {
                // treat as a cache miss — the method body executes normally
            }

            @Override
            public void handleCachePutError(RuntimeException exception, Cache cache,
                                            Object key, Object value) {
                // value simply is not cached
            }

            @Override
            public void handleCacheEvictError(RuntimeException exception, Cache cache, Object key) {
                // stale entry possible — acceptable: the next write re-syncs
            }

            @Override
            public void handleCacheClearError(RuntimeException exception, Cache cache) {
                // no-op
            }
        };
    }
}
