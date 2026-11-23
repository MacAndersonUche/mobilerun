package ai.mobilerun.selfhosted

/**
 * Pure helpers for preferred-package window selection.
 *
 * Hint is a *preference* (score boost), never a hard filter that yields an
 * empty tree while windows still exist. Sticky hints caused home/launcher
 * dumps to return windows=0 on S21+ (APK 532 regression).
 */
object PreferredPackagePolicy {
    /** Auto-clear stale hints so a finished job cannot poison the next dump. */
    const val HINT_TTL_MS: Long = 120_000L

    data class Cand(
        val pkg: String,
        val score: Int,
        val fromRootInActive: Boolean = false,
        val isIgnoredOverlay: Boolean = false,
    )

    fun packageMatchesHint(pkg: String, hint: String?): Boolean {
        val p = pkg.lowercase()
        val h = (hint ?: "").lowercase().trim()
        if (h.isEmpty() || p.isEmpty()) return false
        return p == h || p.contains(h) || h.contains(p) ||
            h.split('.').lastOrNull()?.let { it.isNotEmpty() && p.contains(it) } == true
    }

    fun scoreWindow(
        pkg: String,
        hint: String?,
        fromRootInActive: Boolean,
        focused: Boolean,
        active: Boolean,
        isApplication: Boolean,
    ): Int {
        var s = 0
        if (packageMatchesHint(pkg, hint)) s += 1000
        if (fromRootInActive) s += 50
        if (focused) s += 20
        if (active) s += 10
        if (isApplication) s += 5
        return s
    }

    /**
     * Always return a candidate when any exist. Prefer hint match via score;
     * never refuse a non-matching best (empty-tree regression).
     */
    fun selectPreferred(candidates: List<Cand>, hint: String?): Cand? {
        if (candidates.isEmpty()) return null
        val usable = candidates.filter { !it.isIgnoredOverlay }
        val pool = if (usable.isNotEmpty()) usable else candidates
        return pool.maxByOrNull { it.score }
    }

    /**
     * When every APPLICATION candidate was filtered as overlay/chrome, still
     * emit rootInActiveWindow (incl. launcher) so dumps are never windows=0
     * while the system has a live root.
     */
    fun fallbackRoot(
        rootPkg: String?,
        candidatesEmpty: Boolean,
    ): Boolean {
        if (!candidatesEmpty) return false
        return !rootPkg.isNullOrBlank()
    }

    fun hintExpired(nowElapsedMs: Long, setAtElapsedMs: Long, ttlMs: Long = HINT_TTL_MS): Boolean {
        if (setAtElapsedMs <= 0L) return false
        return nowElapsedMs - setAtElapsedMs > ttlMs
    }
}
