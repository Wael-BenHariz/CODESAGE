package com.codesage.intellij.util

import org.junit.Assert.assertEquals
import org.junit.Test

class HtmlTest {

    @Test
    fun `escapes markup and quotes`() {
        assertEquals(
            "&lt;a href=&quot;x&quot;&gt;&amp;&#039;&lt;/a&gt;",
            Html.escape("<a href=\"x\">&'</a>"),
        )
    }

    @Test
    fun `encodes arguments as a JSON array`() {
        assertEquals(
            "command:codesage.openFinding?%5B%22finding-1%22%5D",
            Html.commandUri("codesage.openFinding", "finding-1"),
        )
    }

    @Test
    fun `encodes non-ascii and quotes like encodeURIComponent`() {
        assertEquals(
            "%C3%BC%20%5C%22%20%26%20%25%20%23",
            UriEncode.encode("\u00fc \\\" & % #"),
        )
    }

    @Test
    fun `round-trips encoded arguments`() {
        val value = "id with spaces & % # \"quotes\" 'single' /slash?query=1 \u00fcn\u00efcode"
        assertEquals(value, UriEncode.decode(UriEncode.encode(value)))
    }

    @Test
    fun `json string escaping matches JSON stringify`() {
        assertEquals(
            "\"a\\\"b\\\\c\\nd\\te\\u0001\"",
            Html.jsonString("a\"b\\c\nd\te\u0001"),
        )
    }
}
