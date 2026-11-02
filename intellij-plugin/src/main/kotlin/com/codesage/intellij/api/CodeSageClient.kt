package com.codesage.intellij.api

import java.io.IOException
import com.codesage.intellij.auth.DevTokenAuthProvider
import com.codesage.intellij.model.LocalReviewRequest
import com.codesage.intellij.model.LocalReviewResult
import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import com.intellij.openapi.progress.ProcessCanceledException
import com.intellij.openapi.progress.ProgressIndicator
import java.net.URI
import java.net.Proxy
import java.net.ProxySelector
import java.net.SocketAddress
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.net.http.HttpTimeoutException
import java.time.Duration
import java.util.concurrent.CancellationException
import java.util.concurrent.CompletableFuture
import java.util.concurrent.ExecutionException
import java.util.concurrent.TimeUnit
import java.util.concurrent.TimeoutException

class ApiError(
    message: String,
    val status: Int?,
    val detail: Any? = null,
) : RuntimeException(message)

/**
 * Port of `vscode-extension/src/api.ts`.
 *
 * Differences that do not change behaviour: `java.net.http` instead of `fetch`,
 * and a cancellation poll against the platform `ProgressIndicator` instead of
 * `AbortController`.
 */
class CodeSageClient(
    baseUrl: String,
    private val auth: DevTokenAuthProvider,
    private val timeoutMs: Long,
) {
    private val gson: Gson = CodeSageGson
    private val apiBase = baseUrl.replace(Regex("/+$"), "") + "/api/v1"
    private val systemProxySelector = ProxySelector.getDefault()
    private val httpClient: HttpClient = HttpClient.newBuilder()
        .connectTimeout(Duration.ofMillis(timeoutMs))
        // Uvicorn's local review server speaks HTTP/1.1 and rejects JDK h2c upgrades.
        .version(HttpClient.Version.HTTP_1_1)
        .proxy(object : ProxySelector() {
            override fun select(uri: URI): List<Proxy> {
                if (isLoopbackHost(uri.host)) return listOf(Proxy.NO_PROXY)
                return systemProxySelector?.select(uri) ?: listOf(Proxy.NO_PROXY)
            }

            override fun connectFailed(uri: URI, address: SocketAddress, error: IOException) {
                systemProxySelector?.connectFailed(uri, address, error)
            }
        })
        .build()

    fun submitDevReview(request: LocalReviewRequest, indicator: ProgressIndicator? = null): LocalReviewResult {
        val body = gson.toJson(ApiMapping.toDto(request))
        val builder = HttpRequest.newBuilder(URI.create("$apiBase/local-reviews/dev"))
            .timeout(Duration.ofMillis(timeoutMs))
            .header("Content-Type", "application/json")
            .header("Accept", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(body, Charsets.UTF_8))
        for ((name, value) in auth.headers()) {
            builder.header(name, value)
        }

        return try {
            val response = await(httpClient.sendAsync(builder.build(), HttpResponse.BodyHandlers.ofString()), indicator)
            if (response.statusCode() !in 200..299) {
                val parsed = parseError(response.statusCode(), response.body())
                throw ApiError(parsed.first, response.statusCode(), parsed.second)
            }
            val dto = gson.fromJson(response.body(), ResultDto::class.java)
            ApiMapping.toModel(dto)
        } catch (error: ApiError) {
            throw error
        } catch (error: ProcessCanceledException) {
            throw error
        } catch (_: HttpTimeoutException) {
            throw ApiError("CodeSage review request timed out or was cancelled.", null)
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
            throw ApiError("CodeSage review request timed out or was cancelled.", null)
        } catch (_: Exception) {
            throw ApiError("Could not reach the CodeSage backend.", null)
        }
    }

    private fun await(
        future: CompletableFuture<HttpResponse<String>>,
        indicator: ProgressIndicator?,
    ): HttpResponse<String> {
        while (true) {
            if (indicator != null && indicator.isCanceled) {
                future.cancel(true)
                throw ProcessCanceledException()
            }
            try {
                return future.get(100, TimeUnit.MILLISECONDS)
            } catch (_: TimeoutException) {
                continue
            } catch (_: CancellationException) {
                throw ProcessCanceledException()
            } catch (error: ExecutionException) {
                val cause = error.cause
                if (cause is HttpTimeoutException) {
                    throw cause
                }
                throw cause ?: error
            }
        }
    }

    /** Port of `errorMessage`: string `detail`, FastAPI validation array, or a generic message. */
    private fun parseError(status: Int, body: String?): Pair<String, Any?> {
        val payload = try {
            JsonParser.parseString(body ?: "").asJsonObject
        } catch (_: Exception) {
            return "CodeSage request failed ($status)" to null
        }
        val detail = payload.get("detail") ?: return "CodeSage request failed ($status)" to payload
        if (detail.isJsonPrimitive && detail.asJsonPrimitive.isString) {
            return detail.asString to detail.asString
        }
        if (detail.isJsonArray) {
            val first = detail.asJsonArray.firstOrNull()
            if (first != null && first.isJsonObject) {
                val issue = first as JsonObject
                val message = issue.get("msg")
                if (message != null && message.isJsonPrimitive && message.asJsonPrimitive.isString) {
                    val location = issue.get("loc")
                        ?.takeIf { it.isJsonArray }
                        ?.asJsonArray
                        ?.joinToString(".") { value -> value.asString }
                        .orEmpty()
                    val path = if (location.isBlank()) "" else " ($location)"
                    return "Invalid review request$path: ${message.asString}" to detail
                }
            }
        }
        return "CodeSage request failed ($status)" to payload
    }

    private fun isLoopbackHost(host: String?): Boolean {
        val normalized = host?.removePrefix("[")?.removeSuffix("]")?.lowercase() ?: return false
        return normalized == "localhost" || normalized == "::1" || normalized.startsWith("127.")
    }
}
