package com.codesage.intellij.report

import com.codesage.intellij.parity.ParityFixtures
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The parity gate: every fixture is rendered by the IntelliJ renderer and
 * compared byte-for-byte with the HTML produced by the real VS Code renderer
 * (`vscode-extension/src/render.ts`, goldens in `src/test/resources/parity`).
 *
 * Regenerate the goldens with `node scripts/parity/emit-golden.mjs`.
 */
class RendererParityTest {

    @Test
    fun `report html is byte-identical to the VS Code renderer`() {
        val fixtures = ParityFixtures.fixtures()
        assertTrue("expected the full fixture set", fixtures.size >= 11)
        for ((name, state) in fixtures) {
            assertEquals(name, ParityFixtures.golden(name), Renderer.renderReportHtml(state))
        }
    }
}
