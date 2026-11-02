package com.codesage.intellij.auth

import com.intellij.credentialStore.CredentialAttributes
import com.intellij.credentialStore.Credentials
import com.intellij.credentialStore.generateServiceName
import com.intellij.ide.passwordSafe.PasswordSafe

/**
 * Port of `vscode-extension/src/auth.ts`.
 *
 * VS Code stores the token in `SecretStorage` (user scoped), so this uses the
 * application-level [PasswordSafe] credential store and the same header name.
 */
class DevTokenAuthProvider {
    private val attributes = CredentialAttributes(generateServiceName(SERVICE_NAME, DEV_TOKEN_KEY))

    fun hasToken(): Boolean = readToken() != null

    fun readToken(): String? = PasswordSafe.instance.getPassword(attributes)

    fun storeToken(token: String?) {
        val value = token?.takeIf { it.isNotBlank() }
        PasswordSafe.instance.set(attributes, value?.let { Credentials(null, it) })
    }

    fun headers(): Map<String, String> {
        val token = readToken() ?: throw IllegalStateException(MISSING_TOKEN_MESSAGE)
        return mapOf(HEADER to token)
    }

    companion object {
        const val HEADER = "X-CodeSage-Dev-Token"
        const val DEV_TOKEN_KEY = "codesage.devToken"
        private const val SERVICE_NAME = "CodeSage"
        const val MISSING_TOKEN_MESSAGE =
            "Missing CodeSage development token. Run \"CodeSage: Set Development Token\" first."
    }
}
