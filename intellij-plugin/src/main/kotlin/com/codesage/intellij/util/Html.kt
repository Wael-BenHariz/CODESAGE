package com.codesage.intellij.util

/**
 * HTML escaping and `command:` URI construction.
 *
 * These are byte-for-byte ports of `escapeHtml` / `commandUri` in
 * `vscode-extension/src/render.ts`. The report goldens compare against the real
 * VS Code renderer, so any change here must keep that output identical.
 */
object Html {
    fun escape(value: String): String = value
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\"", "&quot;")
        .replace("'", "&#039;")

    /**
     * `command:<name>?<encodeURIComponent(JSON.stringify(args))>`.
     * Callers HTML-escape the result, exactly like the VS Code renderer does.
     */
    fun commandUri(command: String, vararg args: String): String =
        "command:$command?" + UriEncode.encode(jsonStringArray(args.asList()))

    /** `JSON.stringify` for a flat array of strings (no whitespace, non-ASCII kept). */
    fun jsonStringArray(values: List<String>): String =
        values.joinToString(prefix = "[", postfix = "]", separator = ",") { jsonString(it) }

    /** `JSON.stringify` for a single string. */
    fun jsonString(value: String): String {
        val out = StringBuilder(value.length + 2)
        out.append('"')
        for (ch in value) {
            when (ch) {
                '"' -> out.append("\\\"")
                '\\' -> out.append("\\\\")
                '\b' -> out.append("\\b")
                '\u000C' -> out.append("\\f")
                '\n' -> out.append("\\n")
                '\r' -> out.append("\\r")
                '\t' -> out.append("\\t")
                else ->
                    if (ch < ' ') {
                        out.append("\\u").append(String.format("%04x", ch.code))
                    } else {
                        out.append(ch)
                    }
            }
        }
        out.append('"')
        return out.toString()
    }
}

/**
 * JavaScript `encodeURIComponent` / `decodeURIComponent` equivalents.
 *
 * `java.net.URLEncoder` is *not* a substitute: it encodes spaces as `+` and
 * escapes a different character set, which would change every command link.
 */
object UriEncode {
    private const val UNRESERVED = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.!~*'()"
    private val HEX = "0123456789ABCDEF".toCharArray()

    fun encode(value: String): String {
        val out = StringBuilder(value.length)
        var index = 0
        while (index < value.length) {
            val codePoint = value.codePointAt(index)
            index += Character.charCount(codePoint)
            val text = String(Character.toChars(codePoint))
            var allUnreserved = true
            for (ch in text) {
                if (UNRESERVED.indexOf(ch) < 0) {
                    allUnreserved = false
                    break
                }
            }
            if (allUnreserved) {
                out.append(text)
            } else {
                for (byte in text.toByteArray(Charsets.UTF_8)) {
                    val value6 = byte.toInt() and 0xFF
                    out.append('%').append(HEX[value6 shr 4]).append(HEX[value6 and 0xF])
                }
            }
        }
        return out.toString()
    }

    fun decode(value: String): String {
        val bytes = java.io.ByteArrayOutputStream(value.length)
        var index = 0
        while (index < value.length) {
            val ch = value[index]
            if (ch == '%' && index + 2 < value.length) {
                val hex = value.substring(index + 1, index + 3)
                val parsed = hex.toIntOrNull(16)
                if (parsed != null) {
                    bytes.write(parsed)
                    index += 3
                    continue
                }
            }
            val codePoint = value.codePointAt(index)
            val text = String(Character.toChars(codePoint))
            bytes.write(text.toByteArray(Charsets.UTF_8))
            index += Character.charCount(codePoint)
        }
        return bytes.toString(Charsets.UTF_8.name())
    }
}
