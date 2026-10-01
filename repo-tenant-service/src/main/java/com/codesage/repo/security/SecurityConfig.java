package com.codesage.repo.security;

import com.codesage.repo.config.InternalSecurityProperties;
import lombok.NonNull;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.convert.converter.Converter;
import org.springframework.http.HttpMethod;
import org.springframework.security.authentication.AbstractAuthenticationToken;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.oauth2.core.DelegatingOAuth2TokenValidator;
import org.springframework.security.oauth2.core.OAuth2TokenValidator;
import org.springframework.security.oauth2.core.OAuth2TokenValidatorResult;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtIssuerValidator;
import org.springframework.security.oauth2.jwt.JwtTimestampValidator;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationConverter;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.web.cors.CorsConfigurationSource;

import java.util.List;

@Configuration
@EnableMethodSecurity
@RequiredArgsConstructor
public class SecurityConfig {

    private final CorsConfigurationSource corsConfigurationSource;

    private final InternalServiceFilter internalServiceFilter;

    @Bean
    public SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {

        http
                .cors(cors -> cors.configurationSource(corsConfigurationSource))

                .csrf(csrf -> csrf.disable())
                .sessionManagement(session ->
                        session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(auth -> auth
                        .requestMatchers(HttpMethod.OPTIONS, "/**").permitAll()
                        // Internal (service-to-service) endpoints: gated by the
                        // X-Service-Token filter below, not by a user JWT.
                        .requestMatchers("/api/v1/repos/internal/**").permitAll()
                        .requestMatchers("/actuator/health").permitAll()
                        .requestMatchers("/actuator/prometheus").permitAll()
                        .requestMatchers("/api/admin/**").hasRole("SUPER_ADMIN")
                        .anyRequest().authenticated()
                )
                .oauth2ResourceServer(oauth ->
                        oauth.jwt(jwt ->
                                jwt.jwtAuthenticationConverter(jwtAuthenticationConverter())
                        )
                )

                // Internal (X-Service-Token) endpoints are checked by this filter
                .addFilterBefore(internalServiceFilter,
                        org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter.class);

        return http.build();
    }

    @Bean
    public Converter<@NonNull Jwt, ? extends AbstractAuthenticationToken> jwtAuthenticationConverter() {
        JwtAuthenticationConverter converter = new JwtAuthenticationConverter();
        converter.setJwtGrantedAuthoritiesConverter(new KeycloakRealmRoleConverter());
        return converter;
    }

    /**
     * Nimbus decoder validating timestamps plus ANY issuer in the
     * keycloak.allowed-issuers list (external MetalLB address and in-cluster
     * service DNS both serve the same realm).
     */
    @Bean
    public JwtDecoder jwtDecoder(
            @Value("${spring.security.oauth2.resourceserver.jwt.jwk-set-uri}") String jwkSetUri,
            @Value("${keycloak.allowed-issuers}") List<String> allowedIssuers) {

        List<OAuth2TokenValidator<Jwt>> issuerValidators = allowedIssuers.stream()
                .map(JwtIssuerValidator::new)
                .map(v -> (OAuth2TokenValidator<Jwt>) v)
                .toList();

        // accept the token if ANY configured issuer matches
        OAuth2TokenValidator<Jwt> anyIssuer = jwt -> {
            OAuth2TokenValidatorResult firstError = null;
            for (OAuth2TokenValidator<Jwt> validator : issuerValidators) {
                OAuth2TokenValidatorResult result = validator.validate(jwt);
                if (!result.hasErrors()) {
                    return OAuth2TokenValidatorResult.success();
                }
                if (firstError == null) {
                    firstError = result;
                }
            }
            return firstError != null ? firstError : OAuth2TokenValidatorResult.success();
        };

        NimbusJwtDecoder decoder = NimbusJwtDecoder.withJwkSetUri(jwkSetUri).build();
        decoder.setJwtValidator(new DelegatingOAuth2TokenValidator<>(
                new JwtTimestampValidator(),
                anyIssuer
        ));
        return decoder;
    }
}
