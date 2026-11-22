package ai.mobilerun.selfhosted

import android.app.AppOpsManager
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import android.os.Build
import android.os.Process
import android.util.Log

/**
 * Resolve the real foreground app when Accessibility's rootInActiveWindow is
 * stuck on the launcher (FLAG_SECURE / Compose / delayed window attach).
 *
 * Order: UsageStats recent MOVE_TO_FOREGROUND → lastOpenedPackage (fresh) → null.
 */
object ForegroundResolver {
    private const val TAG = "FgResolver"
    /** Trust lastOpenedPackage for this long after open_app. */
    const val LAST_OPEN_TRUST_MS: Long = 20_000L

    fun hasUsageAccess(context: Context): Boolean {
        return try {
            val appOps = context.getSystemService(Context.APP_OPS_SERVICE) as AppOpsManager
            val mode = if (Build.VERSION.SDK_INT >= 29) {
                appOps.unsafeCheckOpNoThrow(
                    AppOpsManager.OPSTR_GET_USAGE_STATS,
                    Process.myUid(),
                    context.packageName,
                )
            } else {
                @Suppress("DEPRECATION")
                appOps.checkOpNoThrow(
                    AppOpsManager.OPSTR_GET_USAGE_STATS,
                    Process.myUid(),
                    context.packageName,
                )
            }
            mode == AppOpsManager.MODE_ALLOWED
        } catch (e: Exception) {
            Log.w(TAG, "hasUsageAccess: ${e.message}")
            false
        }
    }

    /**
     * Most recent app that moved to foreground in [lookbackMs], excluding
     * [selfPkg] / launcher / SystemUI when possible.
     */
    fun usageForegroundPackage(
        context: Context,
        preferHint: String? = null,
        selfPkg: String,
        lookbackMs: Long = 15_000L,
    ): String? {
        if (!hasUsageAccess(context)) return null
        return try {
            val usm = context.getSystemService(Context.USAGE_STATS_SERVICE) as? UsageStatsManager
                ?: return null
            val end = System.currentTimeMillis()
            val begin = end - lookbackMs
            val events = usm.queryEvents(begin, end) ?: return null
            val event = UsageEvents.Event()
            var lastAny: String? = null
            var lastHint: String? = null
            while (events.hasNextEvent()) {
                events.getNextEvent(event)
                if (event.eventType != UsageEvents.Event.MOVE_TO_FOREGROUND &&
                    event.eventType != UsageEvents.Event.ACTIVITY_RESUMED
                ) {
                    continue
                }
                val pkg = event.packageName ?: continue
                if (pkg == selfPkg) continue
                val low = pkg.lowercase()
                if (low.contains("systemui") || low.contains("launcher")) {
                    // Keep scanning — may still see target later
                    continue
                }
                lastAny = pkg
                if (!preferHint.isNullOrBlank() &&
                    PreferredPackagePolicy.packageMatchesHint(pkg, preferHint)
                ) {
                    lastHint = pkg
                }
            }
            lastHint ?: lastAny
        } catch (e: SecurityException) {
            Log.w(TAG, "usageForegroundPackage denied: ${e.message}")
            null
        } catch (e: Exception) {
            Log.w(TAG, "usageForegroundPackage: ${e.message}")
            null
        }
    }

    fun isLauncherOrChrome(pkg: String?): Boolean {
        val low = (pkg ?: "").lowercase()
        if (low.isBlank()) return true
        return low.contains("launcher") ||
            low.contains("systemui") ||
            low.contains("mobilerun.selfhosted") ||
            low.endsWith(".selfhosted") ||
            low.contains("spay") ||
            low.contains("samsungpay")
    }

    /**
     * When a11y FG is launcher/chrome but we just opened [lastOpened] (or UsageStats
     * shows the hint), return the inferred foreground package.
     */
    fun resolveReportedPackage(
        context: Context,
        a11yPackage: String?,
        preferHint: String?,
        lastOpened: String?,
        lastOpenedAtMs: Long,
        selfPkg: String,
        nowMs: Long = System.currentTimeMillis(),
    ): Pair<String, String> {
        val a11y = (a11yPackage ?: "").trim()
        if (a11y.isNotBlank() && !isLauncherOrChrome(a11y)) {
            if (preferHint.isNullOrBlank() ||
                PreferredPackagePolicy.packageMatchesHint(a11y, preferHint)
            ) {
                return a11y to "a11y"
            }
            // Wrong FG but real app — still report a11y (overlay_dismiss handles)
            return a11y to "a11y_other"
        }
        val usage = usageForegroundPackage(
            context,
            preferHint = preferHint,
            selfPkg = selfPkg,
        )
        if (!usage.isNullOrBlank() && !isLauncherOrChrome(usage)) {
            Log.i(TAG, "FG from UsageStats=$usage (a11y was ${a11y.ifBlank { "-" }})")
            return usage to "usage_stats"
        }
        val opened = (lastOpened ?: "").trim()
        val fresh = opened.isNotBlank() &&
            lastOpenedAtMs > 0L &&
            (nowMs - lastOpenedAtMs) in 0..LAST_OPEN_TRUST_MS
        if (fresh && !isLauncherOrChrome(opened)) {
            if (preferHint.isNullOrBlank() ||
                PreferredPackagePolicy.packageMatchesHint(opened, preferHint)
            ) {
                Log.i(
                    TAG,
                    "FG from lastOpened=$opened age=${nowMs - lastOpenedAtMs}ms " +
                        "(a11y was ${a11y.ifBlank { "-" }})",
                )
                return opened to "last_opened"
            }
        }
        return a11y to "a11y_launcher"
    }
}
