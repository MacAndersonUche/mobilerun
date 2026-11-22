package ai.mobilerun.selfhosted

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PreferredPackagePolicyTest {

    @Test
    fun selectPreferred_prefersHintMatchButNeverReturnsNullWhenWindowsExist() {
        val hint = "com.bumble.app"
        val cands = listOf(
            PreferredPackagePolicy.Cand(
                pkg = "com.sec.android.app.launcher",
                score = PreferredPackagePolicy.scoreWindow(
                    "com.sec.android.app.launcher",
                    hint,
                    fromRootInActive = true,
                    focused = false,
                    active = false,
                    isApplication = true,
                ),
                fromRootInActive = true,
            ),
            PreferredPackagePolicy.Cand(
                pkg = "com.bumble.app",
                score = PreferredPackagePolicy.scoreWindow(
                    "com.bumble.app",
                    hint,
                    fromRootInActive = false,
                    focused = false,
                    active = false,
                    isApplication = true,
                ),
            ),
        )
        val best = PreferredPackagePolicy.selectPreferred(cands, hint)
        assertNotNull(best)
        assertEquals("com.bumble.app", best!!.pkg)
    }

    @Test
    fun selectPreferred_launcherOnly_stillEmitsLauncherNotEmpty() {
        val hint = "com.bumble.app" // sticky leftover from prior job
        val cands = listOf(
            PreferredPackagePolicy.Cand(
                pkg = "com.sec.android.app.launcher",
                score = PreferredPackagePolicy.scoreWindow(
                    "com.sec.android.app.launcher",
                    hint,
                    fromRootInActive = true,
                    focused = true,
                    active = true,
                    isApplication = true,
                ),
                fromRootInActive = true,
                isIgnoredOverlay = true, // launcher is chrome — still must not empty
            ),
        )
        val best = PreferredPackagePolicy.selectPreferred(cands, hint)
        assertNotNull(best)
        assertEquals("com.sec.android.app.launcher", best!!.pkg)
        assertTrue(PreferredPackagePolicy.fallbackRoot("com.sec.android.app.launcher", true))
    }

    @Test
    fun selectPreferred_nonMatchingBest_stillSelectedNeverFilteredAway() {
        val hint = "com.takimi.android"
        val cands = listOf(
            PreferredPackagePolicy.Cand(
                pkg = "com.bumble.app",
                score = PreferredPackagePolicy.scoreWindow(
                    "com.bumble.app", hint,
                    fromRootInActive = true,
                    focused = true,
                    active = true,
                    isApplication = true,
                ),
                fromRootInActive = true,
            ),
        )
        val best = PreferredPackagePolicy.selectPreferred(cands, hint)
        assertNotNull(best)
        assertEquals("com.bumble.app", best!!.pkg)
        assertFalse(PreferredPackagePolicy.packageMatchesHint(best.pkg, hint))
    }

    @Test
    fun selectPreferred_emptyCandidates_returnsNull() {
        assertNull(PreferredPackagePolicy.selectPreferred(emptyList(), "com.bumble.app"))
    }

    @Test
    fun hintExpired_afterTtl() {
        val setAt = 1_000L
        assertFalse(PreferredPackagePolicy.hintExpired(1_000L + 60_000L, setAt))
        assertTrue(
            PreferredPackagePolicy.hintExpired(
                setAt + PreferredPackagePolicy.HINT_TTL_MS + 1,
                setAt,
            ),
        )
    }

    @Test
    fun packageMatchesHint_substringAndLastSegment() {
        assertTrue(
            PreferredPackagePolicy.packageMatchesHint(
                "com.bumble.app",
                "bumble",
            ),
        )
        assertTrue(
            PreferredPackagePolicy.packageMatchesHint(
                "com.badoo.mobile",
                "com.badoo.mobile",
            ),
        )
        assertFalse(
            PreferredPackagePolicy.packageMatchesHint(
                "com.sec.android.app.launcher",
                "com.bumble.app",
            ),
        )
    }
}
