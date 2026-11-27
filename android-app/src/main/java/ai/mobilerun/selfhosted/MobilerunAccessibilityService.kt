package ai.mobilerun.selfhosted

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.AccessibilityServiceInfo
import android.accessibilityservice.GestureDescription
import android.graphics.Bitmap
import android.graphics.Path
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.Looper
import android.os.SystemClock
import android.util.Base64
import android.util.Log
import android.view.Display
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import kotlinx.coroutines.suspendCancellableCoroutine
import java.io.ByteArrayOutputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference
import java.util.zip.GZIPOutputStream
import kotlin.coroutines.resume

/**
 * Accessibility control surface for MobileRun.
 *
 * UI trees are built on a dedicated [HandlerThread] (never the main / WS thread),
 * with a soft deadline that returns a partial compact dump rather than hanging.
 * Content-change events bump a generation so unchanged screens are served from cache.
 */
class MobilerunAccessibilityService : AccessibilityService() {

    companion object {
        private const val TAG = "MobilerunA11y"
        // Compact dumps — rich enough for Social/Dating apps (content-desc /
        // clickable parents, Compose-ish rows) while staying under WS limits.
        private const val MAX_NODES = 220
        private const val MAX_DEPTH = 18
        private const val MAX_TREE_CHARS = 28_000
        // Soft budget for the main-looper walk itself (partial tree > empty).
        // Hard await must absorb main-thread scheduling delay on slow/ANR-busy
        // devices so we never return before a late non-empty walk.
        private const val SOFT_DEADLINE_MS = 2_400L
        // Caller await: main scheduling + soft walk + gzip. Keep > soft+1s.
        private const val HARD_AWAIT_MS = 5_500L
        // If compact dump is too thin for the FG app, re-walk without filters.
        private const val MIN_USEFUL_NODES = 15
        // Serve unchanged content from cache aggressively
        private const val CACHE_TTL_MS = 4_000L
        // Keep a slightly older non-empty dump to avoid feeding empty trees after drops
        private const val STALE_NONEMPTY_TTL_MS = 12_000L

        @Volatile
        var instance: MobilerunAccessibilityService? = null

        /** Portal MobilerunAccessibilityService.calculateInputText — single SET_TEXT payload. */
        fun calculateInputText(
            currentText: String?,
            hintText: String?,
            newText: String,
            clear: Boolean,
            selectionStart: Int? = null,
            selectionEnd: Int? = null,
        ): String {
            if (clear) return newText
            val safeCurrentText = currentText.orEmpty()
            if (hintText != null && safeCurrentText == hintText) return newText
            val length = safeCurrentText.length
            val rawStart = selectionStart ?: length
            val rawEnd = selectionEnd ?: rawStart
            val start = rawStart.coerceIn(0, length)
            val end = rawEnd.coerceIn(0, length)
            val replaceStart = minOf(start, end)
            val replaceEnd = maxOf(start, end)
            val before = safeCurrentText.take(replaceStart)
            val after = safeCurrentText.substring(replaceEnd)
            return before + newText + after
        }
    }

    data class TreeResult(
        val tree: String,
        val packageName: String,
        val empty: Boolean,
        val chars: Int,
        val nodes: Int,
        val partial: Boolean,
        val cached: Boolean,
        val buildMs: Long,
        val bytes: Int,
        val treeGzB64: String?,
        val anrDismissed: Boolean,
        /** App-window nodes excluding SystemUI / nav bars (for MIN_USEFUL). */
        val appNodes: Int = 0,
        /** Nodes with non-empty text/content-desc — 0 ⇒ screenshot+vision. */
        val textNodes: Int = 0,
        /** True when dump has no labels (Compose/Flutter deck) — force vision. */
        val needsVision: Boolean = false,
    )

    private val screenshotExecutor = Executors.newSingleThreadExecutor { r ->
        Thread(r, "mr-screenshot").also { it.isDaemon = true }
    }

    // Dedicated dump thread — orchestrates cache/gzip; never used for a11y IPC.
    // AccessibilityNodeInfo / windows() binder calls hang or return empty when
    // invoked off the service main looper (S21+ and emulator both hit this).
    private val dumpThread = HandlerThread("mr-a11y-dump").also { it.start() }
    private val dumpHandler = Handler(dumpThread.looper)
    private val mainHandler = Handler(Looper.getMainLooper())

    private val contentGeneration = AtomicLong(0)
    private val cacheLock = Any()
    @Volatile private var cachedGeneration: Long = -1
    @Volatile private var cachedAtMs: Long = 0
    @Volatile private var cachedResult: TreeResult? = null
    @Volatile private var lastNonEmptyResult: TreeResult? = null
    @Volatile private var lastNonEmptyAtMs: Long = 0
    /**
     * Hint from open_app / get_ui_tree — prefer this package's window.
     * Private field + explicit setters avoid JVM clash with setPreferredPackageHint().
     */
    @Volatile private var preferredPkgHint: String? = null
    @Volatile private var preferredPackageHintSetAtMs: Long = 0L
    @Volatile private var lastScreenshotAtMs: Long = 0L

    /** Read-only view of the current preferred-package hint. */
    fun preferredPackageHint(): String? = preferredPkgHint

    /** Clear sticky hint (job end / timeout / explicit). Prefer is never a hard filter. */
    fun clearPreferredPackageHint(reason: String = "clear") {
        if (preferredPkgHint != null) {
            Log.i(TAG, "clear preferredPackageHint was=$preferredPkgHint reason=$reason")
        }
        preferredPkgHint = null
        preferredPackageHintSetAtMs = 0L
    }

    fun setPreferredPackageHint(pkg: String?) {
        val trimmed = pkg?.trim()?.takeIf { it.isNotEmpty() }
        preferredPkgHint = trimmed
        preferredPackageHintSetAtMs =
            if (trimmed != null) SystemClock.elapsedRealtime() else 0L
        if (trimmed != null) {
            Log.i(TAG, "set preferredPackageHint=$trimmed")
        }
    }

    private fun refreshPreferredPackageHint() {
        val hint = preferredPkgHint
        if (hint.isNullOrBlank()) return
        if (
            PreferredPackagePolicy.hintExpired(
                SystemClock.elapsedRealtime(),
                preferredPackageHintSetAtMs,
            )
        ) {
            clearPreferredPackageHint("ttl_expired")
        }
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        ensureInteractiveServiceFlags("onServiceConnected")
    }

    /**
     * Mirror uiautomator / UiAutomation: interactive windows + not-important
     * views. Must call setServiceInfo — assigning flags alone (or only once
     * at connect) can leave getWindows() empty while rootInActiveWindow stays
     * stale (Taimi: uiautomator 195 nodes, our dump nodes=0).
     */
    private fun ensureInteractiveServiceFlags(why: String) {
        try {
            val info = serviceInfo ?: AccessibilityServiceInfo()
            val before = info.flags
            info.flags = info.flags or
                AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS or
                AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS or
                AccessibilityServiceInfo.FLAG_INCLUDE_NOT_IMPORTANT_VIEWS
            // typeAllMask equivalent — match accessibility_service_config.xml
            info.eventTypes = AccessibilityEvent.TYPES_ALL_MASK
            info.feedbackType = AccessibilityServiceInfo.FEEDBACK_GENERIC
            info.notificationTimeout = 100
            setServiceInfo(info)
            Log.i(
                TAG,
                "setServiceInfo($why) flags $before→${serviceInfo?.flags}",
            )
        } catch (e: Exception) {
            Log.w(TAG, "setServiceInfo($why) failed: ${e.message}")
        }
    }

    /** UiAutomator refreshes roots before dump — Compose/RN often need this. */
    private fun refreshRoot(root: AccessibilityNodeInfo): Int {
        return try {
            root.refresh()
            root.childCount
        } catch (_: Exception) {
            try {
                root.childCount
            } catch (_: Exception) {
                0
            }
        }
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event == null) return
        when (event.eventType) {
            AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED,
            AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED,
            AccessibilityEvent.TYPE_WINDOWS_CHANGED,
            -> {
                contentGeneration.incrementAndGet()
            }
        }
    }

    override fun onInterrupt() {
        Log.d(TAG, "Service interrupted")
    }

    override fun onDestroy() {
        instance = null
        try {
            dumpThread.quitSafely()
        } catch (_: Exception) {
        }
        super.onDestroy()
    }

    // === Device Control Methods ===

    fun tap(
        x: Int,
        y: Int,
        humanize: Boolean = true,
        callback: (Boolean) -> Unit,
    ) {
        // Slight jitter so taps are not pixel-perfect robotic
        val jx: Int
        val jy: Int
        if (humanize) {
            val r = java.util.concurrent.ThreadLocalRandom.current()
            jx = x + r.nextInt(-10, 11)
            jy = y + r.nextInt(-10, 11)
        } else {
            jx = x
            jy = y
        }
        val path = Path().apply { moveTo(jx.toFloat(), jy.toFloat()) }
        val pressMs = if (humanize) {
            java.util.concurrent.ThreadLocalRandom.current().nextLong(45, 85)
        } else {
            50L
        }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, pressMs))
            .build()
        val ok = dispatchGesture(
            gesture,
            object : GestureResultCallback() {
                override fun onCompleted(gestureDescription: GestureDescription?) = callback(true)
                override fun onCancelled(gestureDescription: GestureDescription?) = callback(false)
            },
            null,
        )
        if (!ok) callback(false)
    }

    /** Fire-and-forget tap — Portal GestureController (dispatch only, no callback wait). */
    fun tapFireAndForget(x: Int, y: Int, humanize: Boolean = true) {
        GestureController.tap(x, y, humanize = humanize)
    }

    fun swipe(x1: Int, y1: Int, x2: Int, y2: Int, durationMs: Long, callback: (Boolean) -> Unit) {
        val path = Path().apply {
            moveTo(x1.toFloat(), y1.toFloat())
            lineTo(x2.toFloat(), y2.toFloat())
        }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, durationMs))
            .build()
        val ok = dispatchGesture(
            gesture,
            object : GestureResultCallback() {
                override fun onCompleted(gestureDescription: GestureDescription?) = callback(true)
                override fun onCancelled(gestureDescription: GestureDescription?) = callback(false)
            },
            null,
        )
        if (!ok) callback(false)
    }

    fun swipeFireAndForget(x1: Int, y1: Int, x2: Int, y2: Int, durationMs: Long) {
        GestureController.swipe(x1, y1, x2, y2, durationMs.toInt())
    }

    fun pressBack(): Boolean = performGlobalAction(GLOBAL_ACTION_BACK)

    fun pressHome(): Boolean = performGlobalAction(GLOBAL_ACTION_HOME)

    fun pressRecents(): Boolean = performGlobalAction(GLOBAL_ACTION_RECENTS)

    /** IME Enter / editor action on the focused input (API 30+). */
    fun pressEnter(): Boolean {
        // ACTION_IME_ENTER = 0x100 — not always visible on older compile stubs
        val actionImeEnter = 0x00000100
        val root = rootInActiveWindow ?: return false
        val focused =
            root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
                ?: root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)
        if (focused != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            val ok = focused.performAction(actionImeEnter)
            focused.recycle()
            if (ok) return true
        } else {
            focused?.recycle()
        }
        // Fallback: KEYCODE_ENTER via shell (best-effort)
        return try {
            Runtime.getRuntime().exec(arrayOf("input", "keyevent", "66")).waitFor() == 0
        } catch (_: Exception) {
            false
        }
    }

    fun activePackageName(): String? {
        if (Looper.myLooper() == Looper.getMainLooper()) {
            return activePackageNameOnMain()
        }
        val ref = AtomicReference<String?>(null)
        val latch = CountDownLatch(1)
        mainHandler.post {
            try {
                ref.set(activePackageNameOnMain())
            } finally {
                latch.countDown()
            }
        }
        // Short timeout — never stall open_app / heartbeats on a11y IPC
        latch.await(400, TimeUnit.MILLISECONDS)
        return ref.get()
    }

    private fun activePackageNameOnMain(): String? {
        val self = packageName
        val hint = preferredPkgHint
        val active = rootInActiveWindow?.packageName?.toString()
        if (!active.isNullOrBlank() && !isIgnoredOverlayPackage(active)) {
            if (hint.isNullOrBlank() || packageMatchesHint(active, hint)) return active
        }
        // Prefer target APPLICATION window; never report spay/systemui as FG
        val apps = windows
            ?.filter { it.type == AccessibilityWindowInfo.TYPE_APPLICATION }
            ?.sortedByDescending {
                (if (it.isFocused) 2 else 0) + (if (it.isActive) 1 else 0)
            }
            .orEmpty()
        if (!hint.isNullOrBlank()) {
            for (w in apps) {
                val pkg = try {
                    w.root?.packageName?.toString()
                } catch (_: Exception) {
                    null
                } ?: continue
                if (packageMatchesHint(pkg, hint) && !isIgnoredOverlayPackage(pkg)) {
                    return pkg
                }
            }
        }
        for (w in apps) {
            val pkg = try {
                w.root?.packageName?.toString()
            } catch (_: Exception) {
                null
            } ?: continue
            if (!isIgnoredOverlayPackage(pkg) && pkg != self) return pkg
        }
        // a11y stuck on launcher — UsageStats may still see the target FG
        // (Taimi/Hinge FLAG_SECURE / delayed window attach).
        val usage = ForegroundResolver.usageForegroundPackage(
            this,
            preferHint = hint,
            selfPkg = self,
        )
        if (!usage.isNullOrBlank() && !ForegroundResolver.isLauncherOrChrome(usage)) {
            Log.i(TAG, "activePackageName UsageStats fallback=$usage")
            return usage
        }
        return null
    }

    /**
     * Detect System UI ANR / "isn't responding" dialogs and tap Wait or Close app.
     * Returns true if a dialog action was dispatched.
     */
    fun dismissSystemAnrIfPresent(): Boolean = dismissBlockingDialogs(anrOnly = true)

    /**
     * Auto-dismiss ANRs and common permission / runtime popups so tasks recover
     * instead of stalling ("Allow", "While using the app", "OK", …).
     */
    fun dismissBlockingDialogs(anrOnly: Boolean = false): Boolean {
        val root = rootInActiveWindow ?: return false
        try {
            val pkg = root.packageName?.toString().orEmpty()
            val blob = StringBuilder()
            collectTextSample(root, blob, 0, AtomicInteger(0))
            val low = blob.toString().lowercase()
            val isAnr = "isn't responding" in low ||
                "isnt responding" in low ||
                "not responding" in low ||
                ("close app" in low && "wait" in low)
            if (isAnr) {
                val wait = findNodeByText(root, listOf("Wait", "wait"))
                if (wait != null) {
                    val tapped = wait.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                    Log.i(TAG, "ANR dialog: tapped Wait ok=$tapped")
                    return tapped
                }
                val close = findNodeByText(root, listOf("Close app", "Close App", "close app"))
                if (close != null) {
                    val tapped = close.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                    Log.i(TAG, "ANR dialog: tapped Close app ok=$tapped")
                    return tapped
                }
            }
            if (anrOnly) return false
            // Foreign overlay (Samsung Pay / SystemUI / Edge) while a dating
            // job has a preferred package — Back / Close, never payment CTAs.
            val hint = preferredPkgHint
            if (!hint.isNullOrBlank() && isIgnoredOverlayPackage(pkg) &&
                !packageMatchesHint(pkg, hint)
            ) {
                val safeClose = findNodeByText(
                    root,
                    listOf(
                        "Close", "Not now", "No thanks", "Maybe later",
                        "Dismiss", "Cancel", "Got it", "Got it!", "OK", "Okay",
                    ),
                )
                if (safeClose != null) {
                    val label = safeClose.text?.toString()
                        ?: safeClose.contentDescription?.toString()
                    val low = (label ?: "").lowercase()
                    val payment = listOf(
                        "pay", "boost", "buy", "purchase", "card", "premium",
                    ).any { it in low }
                    if (!payment) {
                        val tapped = safeClose.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                        Log.i(
                            TAG,
                            "foreign overlay dismiss: tapped '$label' ok=$tapped " +
                                "pkg=$pkg hint=$hint",
                        )
                        return tapped
                    }
                }
                val backed = performGlobalAction(GLOBAL_ACTION_BACK)
                Log.i(
                    TAG,
                    "foreign overlay dismiss: BACK ok=$backed pkg=$pkg hint=$hint",
                )
                return backed
            }
            // Permission / consent popups — prefer the least-restrictive positive action
            // Never "Allow payment" / Pay / Boost / Buy.
            val positives = listOf(
                "While using the app",
                "Only this time",
                "Allow all the time",
                "Allow",
                "ALLOW",
                "OK",
                "Okay",
                "Got it",
                "Continue",
                "Accept",
                "I agree",
                "Agree",
            )
            val node = findNodeByText(root, positives)
            if (node != null) {
                val label = node.text?.toString() ?: node.contentDescription?.toString()
                val low = (label ?: "").lowercase()
                if (
                    "payment" in low || "pay " in low || low == "pay" ||
                    "boost" in low || "buy" in low || "purchase" in low
                ) {
                    Log.w(TAG, "popup dismiss: refusing payment/paid label='$label'")
                    return false
                }
                val tapped = node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                Log.i(TAG, "popup dismiss: tapped '$label' ok=$tapped pkg=$pkg")
                return tapped
            }
            return false
        } finally {
            try {
                root.recycle()
            } catch (_: Exception) {
            }
        }
    }

    private fun collectTextSample(
        node: AccessibilityNodeInfo?,
        out: StringBuilder,
        depth: Int,
        count: AtomicInteger,
    ) {
        if (node == null || depth > 8 || count.get() > 40 || out.length > 800) return
        count.incrementAndGet()
        val t = node.text?.toString().orEmpty()
        val d = node.contentDescription?.toString().orEmpty()
        if (t.isNotEmpty()) out.append(t).append(' ')
        if (d.isNotEmpty()) out.append(d).append(' ')
        for (i in 0 until node.childCount) {
            val child = try {
                node.getChild(i)
            } catch (_: Exception) {
                null
            }
            collectTextSample(child, out, depth + 1, count)
            try {
                child?.recycle()
            } catch (_: Exception) {
            }
        }
    }

    private fun findNodeByText(
        node: AccessibilityNodeInfo?,
        labels: List<String>,
    ): AccessibilityNodeInfo? {
        if (node == null) return null
        val t = node.text?.toString().orEmpty()
        val d = node.contentDescription?.toString().orEmpty()
        if (labels.any { it.equals(t, ignoreCase = true) || it.equals(d, ignoreCase = true) }) {
            return AccessibilityNodeInfo.obtain(node)
        }
        for (i in 0 until node.childCount) {
            val child = try {
                node.getChild(i)
            } catch (_: Exception) {
                null
            } ?: continue
            val found = findNodeByText(child, labels)
            try {
                child.recycle()
            } catch (_: Exception) {
            }
            if (found != null) return found
        }
        return null
    }

    /**
     * Tap a visible node whose text/contentDescription equals (or contains, if
     * [fuzzy]) [label]. Used for Secure Folder app icons and similar grids.
     */
    fun tapByVisibleText(label: String, fuzzy: Boolean = true): Boolean {
        val want = label.trim()
        if (want.isEmpty()) return false
        val root = rootInActiveWindow ?: return false
        return try {
            val exact = findNodeByText(root, listOf(want))
            val node = exact ?: if (fuzzy) findNodeContainingText(root, want) else null
            if (node == null) return false
            val bounds = android.graphics.Rect()
            try {
                node.getBoundsInScreen(bounds)
            } catch (_: Exception) {
            }
            val tapped = try {
                val clickOk = if (node.isClickable) {
                    node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                } else {
                    var p: AccessibilityNodeInfo? = node.parent
                    var ok = false
                    while (p != null) {
                        if (p.isClickable) {
                            ok = p.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                            break
                        }
                        val next = p.parent
                        try {
                            p.recycle()
                        } catch (_: Exception) {
                        }
                        p = next
                    }
                    ok
                }
                // Portal fallback: coordinate gesture when ACTION_CLICK fails
                if (clickOk) {
                    true
                } else if (!bounds.isEmpty) {
                    GestureController.tap(
                        (bounds.left + bounds.right) / 2,
                        (bounds.top + bounds.bottom) / 2,
                        humanize = false,
                    )
                } else {
                    false
                }
            } finally {
                try {
                    node.recycle()
                } catch (_: Exception) {
                }
            }
            Log.i(TAG, "tapByVisibleText('$want') ok=$tapped")
            tapped
        } catch (e: Exception) {
            Log.w(TAG, "tapByVisibleText failed: ${e.message}")
            false
        }
    }

    private fun findNodeContainingText(
        node: AccessibilityNodeInfo?,
        needle: String,
    ): AccessibilityNodeInfo? {
        if (node == null) return null
        val n = needle.lowercase()
        val t = node.text?.toString().orEmpty()
        val d = node.contentDescription?.toString().orEmpty()
        if (t.lowercase().contains(n) || d.lowercase().contains(n)) {
            return AccessibilityNodeInfo.obtain(node)
        }
        for (i in 0 until node.childCount) {
            val child = try {
                node.getChild(i)
            } catch (_: Exception) {
                null
            } ?: continue
            val found = findNodeContainingText(child, needle)
            try {
                child.recycle()
            } catch (_: Exception) {
            }
            if (found != null) return found
        }
        return null
    }

    /** Back-compat string dump used by older callers. */
    @Volatile
    private var forceFullModeHint: Boolean = false

    fun getUITree(): String = getUITreeDetailed(allowCache = true).tree

    /**
     * Build (or serve cached) compact UI tree.
     *
     * Orchestration + gzip run on [dumpThread] so WS / commandExecutor never walk
     * the tree. AccessibilityNodeInfo IPC runs on the service main looper (required —
     * off-main dumps hang ~5s and return empty on real devices and emulators).
     * Soft deadline returns a partial tree within ~3s rather than nothing.
     */
    fun getUITreeDetailed(
        allowCache: Boolean = true,
        preferredPackage: String? = null,
        forceFullMode: Boolean = false,
    ): TreeResult {
        refreshPreferredPackageHint()
        if (!preferredPackage.isNullOrBlank()) {
            setPreferredPackageHint(preferredPackage.trim())
        }
        if (forceFullMode) {
            forceFullModeHint = true
        }
        val hint = preferredPkgHint
        val gen = contentGeneration.get()
        // r70: a forced full walk must not reuse a cached empty compact dump.
        if (allowCache && !forceFullMode) {
            synchronized(cacheLock) {
                val hit = cachedResult
                if (
                    hit != null &&
                    cachedGeneration == gen &&
                    SystemClock.elapsedRealtime() - cachedAtMs < CACHE_TTL_MS &&
                    // Prefer matching cache; never require empty when hint mismatches
                    (
                        hint.isNullOrBlank() ||
                            packageMatchesHint(hit.packageName, hint) ||
                            !hit.empty
                        )
                ) {
                    return hit.copy(cached = true, buildMs = 0)
                }
            }
        }

        // Already on dump thread — build directly
        if (Looper.myLooper() == dumpThread.looper) {
            return dumpAndCache(gen)
        }
        // Already on main — walk here, gzip inline (fast path for tests)
        if (Looper.myLooper() == Looper.getMainLooper()) {
            return dumpAndCache(gen)
        }

        val latch = CountDownLatch(1)
        val result = AtomicReference<TreeResult?>(null)
        dumpHandler.post {
            try {
                result.set(dumpAndCache(gen))
            } catch (e: Exception) {
                Log.w(TAG, "dump failed: ${e.message}")
                result.set(emptyTreeResult(reason = "dump_error", buildMs = 0))
            } finally {
                latch.countDown()
            }
        }
        val ok = latch.await(HARD_AWAIT_MS, TimeUnit.MILLISECONDS)
        if (!ok) {
            // Soft-deadline walk may still finish and populate cache for the next call
            Log.w(TAG, "getUITreeDetailed hard await timed out after ${HARD_AWAIT_MS}ms")
            synchronized(cacheLock) {
                val late = cachedResult
                if (late != null && cachedGeneration == gen && !late.empty) {
                    return late.copy(cached = true, partial = true, buildMs = HARD_AWAIT_MS)
                }
            }
            return preferStaleNonEmpty(
                emptyTreeResult(reason = "dump_timeout", buildMs = HARD_AWAIT_MS),
            )
        }
        val got = result.get() ?: emptyTreeResult(reason = "dump_null", buildMs = 0)
        return if (got.empty) preferStaleNonEmpty(got) else got
    }

    /** Never hand the cloud an empty tree when a recent non-empty dump exists. */
    private fun preferStaleNonEmpty(fallback: TreeResult): TreeResult {
        synchronized(cacheLock) {
            val stale = lastNonEmptyResult
            if (
                stale != null &&
                !stale.empty &&
                SystemClock.elapsedRealtime() - lastNonEmptyAtMs < STALE_NONEMPTY_TTL_MS
            ) {
                Log.i(TAG, "serving stale non-empty tree chars=${stale.chars}")
                return stale.copy(
                    cached = true,
                    partial = true,
                    buildMs = fallback.buildMs,
                )
            }
        }
        return fallback
    }

    private fun emptyTreeResult(reason: String, buildMs: Long): TreeResult =
        TreeResult(
            tree = """<hierarchy windows="0" nodes="0" empty="true" reason="$reason" soft="$SOFT_DEADLINE_MS"/>""",
            packageName = "",
            empty = true,
            chars = 0,
            nodes = 0,
            partial = true,
            cached = false,
            buildMs = buildMs,
            bytes = 0,
            treeGzB64 = null,
            anrDismissed = false,
        )

    /**
     * Walk a11y tree on main looper; gzip + cache on the calling (dump) thread.
     *
     * Soft deadline starts when the main-looper walk begins — not when the dump
     * thread schedules the post — otherwise a busy main looper burns the whole
     * budget before rootInActiveWindow runs and we return an empty tree.
     */
    private fun dumpAndCache(gen: Long): TreeResult {
        val t0 = SystemClock.elapsedRealtime()
        val walkRef = AtomicReference<TreeResult?>(null)

        fun walkOnMain() {
            val walkStart = SystemClock.elapsedRealtime()
            val deadlineMs = walkStart + SOFT_DEADLINE_MS
            val anr = try {
                dismissSystemAnrIfPresent()
            } catch (e: Exception) {
                Log.w(TAG, "ANR dismiss failed: ${e.message}")
                false
            }
            val built = dumpUITreeCompact(deadlineMs = deadlineMs)
            walkRef.set(built.copy(anrDismissed = anr))
        }

        if (Looper.myLooper() == Looper.getMainLooper()) {
            walkOnMain()
        } else {
            val latch = CountDownLatch(1)
            mainHandler.post {
                try {
                    walkOnMain()
                } catch (e: Exception) {
                    Log.w(TAG, "main dump failed: ${e.message}")
                    walkRef.set(emptyTreeResult(reason = "main_dump_error", buildMs = 0))
                } finally {
                    latch.countDown()
                }
            }
            // Wait for the main walk; soft deadline lives inside dumpUITreeCompact.
            // Poll briefly after the first wait so a late non-empty result is not dropped.
            if (!latch.await(SOFT_DEADLINE_MS + 400, TimeUnit.MILLISECONDS)) {
                Log.w(TAG, "main dump still running after soft+slack; polling for late result")
                val hardDeadline = t0 + HARD_AWAIT_MS - 100
                while (walkRef.get() == null && SystemClock.elapsedRealtime() < hardDeadline) {
                    try {
                        Thread.sleep(40)
                    } catch (_: InterruptedException) {
                        break
                    }
                }
                if (walkRef.get() == null) {
                    return emptyTreeResult(
                        reason = "soft_deadline",
                        buildMs = SystemClock.elapsedRealtime() - t0,
                    )
                }
            }
        }

        val built = walkRef.get() ?: emptyTreeResult(
            reason = "walk_null",
            buildMs = SystemClock.elapsedRealtime() - t0,
        )
        // Gzip on dump/background thread — never on the a11y callback path
        val gz = gzipB64(built.tree)
        val buildMs = SystemClock.elapsedRealtime() - t0
        val result = built.copy(
            buildMs = buildMs,
            bytes = built.tree.toByteArray(Charsets.UTF_8).size,
            treeGzB64 = gz,
            cached = false,
        )
        synchronized(cacheLock) {
            cachedResult = result
            cachedGeneration = gen
            cachedAtMs = SystemClock.elapsedRealtime()
            if (!result.empty && result.nodes > 0) {
                lastNonEmptyResult = result
                lastNonEmptyAtMs = SystemClock.elapsedRealtime()
            }
        }
        Log.i(
            TAG,
            "tree buildMs=$buildMs nodes=${result.nodes} chars=${result.chars} " +
                "bytes=${result.bytes} partial=${result.partial} gz=${gz?.length ?: 0} " +
                "anr=${result.anrDismissed} empty=${result.empty}",
        )
        return if (result.empty) preferStaleNonEmpty(result) else result
    }

    /** True for home-screen launchers — real UI with icons, NOT system chrome. */
    private fun isLauncherPackage(pkg: String): Boolean {
        val p = pkg.lowercase()
        if (p.isEmpty()) return false
        return p.contains("android.launcher") ||
            p.endsWith(".launcher") ||
            p.contains("nexuslauncher") ||
            p.contains("launcher3") ||
            p == "com.miui.home" ||
            p.contains("com.sec.android.app.launcher")
    }

    /**
     * SystemUI / IME / edge panels — never count as dating *or* home content.
     * Launchers are intentionally excluded (APK 540: home had 38 nodes but
     * app_nodes=0 empty=true because `.launcher` was treated as chrome).
     */
    private fun isSystemChromePackage(pkg: String): Boolean {
        val p = pkg.lowercase()
        if (p.isEmpty()) return false
        if (isLauncherPackage(p)) return false
        return p.contains("systemui") ||
            p.contains("permissioncontroller") ||
            p.contains("inputmethod") ||
            p.contains("navigationbar") ||
            p.contains("edgepanels") ||
            p.contains("samsung.android.app.cocktailbarservice")
    }

    /** Overlays / quick-access that must never be treated as the dating FG tree. */
    private fun isIgnoredOverlayPackage(pkg: String): Boolean {
        val p = pkg.lowercase()
        if (p.isEmpty()) return true
        // Launcher is a real home screen — emit + count nodes (not an overlay)
        if (isLauncherPackage(p)) return false
        if (isSystemChromePackage(p)) return true
        if (p == packageName || p.contains("mobilerun.selfhosted")) return true
        return p.contains("spay") ||
            p.contains("samsung.android.spay") ||
            p.contains("samsungpay") ||
            p.contains("bixby") ||
            p.contains("smartcapture") ||
            p.contains("easyaccess") ||
            p.contains("com.samsung.android.app.routines") ||
            p.contains("com.samsung.android.honeyboard") ||
            p.contains("com.google.android.apps.accessibility")
    }

    private fun packageMatchesHint(pkg: String, hint: String?): Boolean =
        PreferredPackagePolicy.packageMatchesHint(pkg, hint)

    private fun dumpUITreeCompact(deadlineMs: Long): TreeResult {
        // First pass: compact (interactive / text / desc). If too thin for the
        // *app* window (exclude SystemUI bars), re-walk in full mode.
        val forceFull = forceFullModeHint
        forceFullModeHint = false
        if (forceFull) {
            Log.i(TAG, "forced fullMode UI tree walk")
            return dumpUITreeWalk(deadlineMs, fullMode = true)
        }
        val compact = dumpUITreeWalk(deadlineMs, fullMode = false)
        val appUseful = compact.appNodes
        // r70: compact.empty used to return immediately, which skipped the
        // fullMode re-walk that finds ~200 Taimi nodes. Keep the empty
        // short-circuit for other screens (avoids a 6-7s hang on a true
        // empty root), but retry unfiltered when Taimi is the hinted app
        // or compact is only thin, not empty.
        val retryEmpty = preferredPkgHint.orEmpty().contains("takimi", ignoreCase = true)
        if (appUseful >= MIN_USEFUL_NODES || (compact.empty && !retryEmpty)) {
            return compact
        }
        val remaining = deadlineMs - SystemClock.elapsedRealtime()
        if (remaining < 400) {
            Log.w(
                TAG,
                "thin app tree appNodes=$appUseful total=${compact.nodes}; " +
                    "no budget left for full re-dump",
            )
            return compact.copy(partial = true)
        }
        Log.i(
            TAG,
            "thin app tree appNodes=$appUseful total=${compact.nodes}; re-dumping uncompacted",
        )
        val full = dumpUITreeWalk(deadlineMs, fullMode = true)
        return if (full.appNodes >= compact.appNodes) {
            full.copy(partial = true)
        } else {
            compact.copy(partial = true)
        }
    }

    private fun dumpUITreeWalk(deadlineMs: Long, fullMode: Boolean): TreeResult {
        // Re-apply flags every dump — rebind/toggle can drop interactive-windows
        ensureInteractiveServiceFlags("dumpUITreeWalk")
        val sb = StringBuilder(8192)
        val counter = intArrayOf(0)
        val appCounter = intArrayOf(0)
        val textCounter = intArrayOf(0)
        val pkgs = linkedSetOf<String>()
        var windowCount = 0
        var partial = false
        // On-device diag: type/pkg/kids per window (Mac: Taimi nodes=0 vs uiautomator)
        val winDiag = mutableListOf<String>()

        fun pastDeadline(): Boolean {
            if (SystemClock.elapsedRealtime() >= deadlineMs) {
                partial = true
                return true
            }
            return false
        }

        fun emitWindow(id: String, type: String, focused: Int, root: AccessibilityNodeInfo): Int {
            val kidsBefore = refreshRoot(root)
            windowCount++
            val pkg = root.packageName?.toString().orEmpty()
            if (pkg.isNotEmpty()) pkgs.add(pkg)
            val countApp = !isSystemChromePackage(pkg)
            val nodesBefore = counter[0]
            sb.append("<w id=\"$id\" t=\"$type\" p=\"${xmlEsc(pkg)}\" f=\"$focused\" kids=\"$kidsBefore\">\n")
            buildCompactNodes(
                root, " ", sb, counter, 0, deadlineMs, fullMode,
                markPartial = { partial = true },
                appCounter = if (countApp) appCounter else null,
                textCounter = textCounter,
            )
            sb.append("</w>\n")
            val emitted = counter[0] - nodesBefore
            winDiag.add("$type:$pkg:kids=$kidsBefore:nodes=$emitted")
            Log.i(
                TAG,
                "emitWindow id=$id type=$type pkg=$pkg kids=$kidsBefore nodes=$emitted",
            )
            return emitted
        }

        // Prefer TYPE_APPLICATION window whose package == target (hint from
        // open_app / get_ui_tree). Hint is a SCORE BOOST only — never refuse a
        // live window (sticky hint + launcher → empty tree was the APK 532 bug).
        val selfPkg = packageName
        val hint = preferredPkgHint
        var activeEmitted = false
        var preferredActiveRoot: AccessibilityNodeInfo? = null
        var preferredActivePkg = ""
        var preferredActiveFromWindows = false
        val emittedPkgs = mutableSetOf<String>()

        data class WinCand(
            val window: AccessibilityWindowInfo?,
            val root: AccessibilityNodeInfo,
            val pkg: String,
            val score: Int,
            val childCount: Int,
            val isIgnoredOverlay: Boolean = false,
        )

        fun scoreWindow(
            w: AccessibilityWindowInfo?,
            pkg: String,
            fromRootInActive: Boolean,
            childCount: Int,
        ): Int {
            var s = PreferredPackagePolicy.scoreWindow(
                pkg = pkg,
                hint = hint,
                fromRootInActive = fromRootInActive,
                focused = w?.isFocused == true,
                active = w?.isActive == true,
                isApplication = w == null || w.type == AccessibilityWindowInfo.TYPE_APPLICATION,
            )
            // Prefer richer roots — rootInActiveWindow is often empty/stale for
            // Compose / FLAG_SECURE while getWindows() TYPE_APPLICATION has nodes
            // (Taimi: uiautomator 214 nodes, our dump nodes=0 via empty rootInActive).
            if (w != null && w.type == AccessibilityWindowInfo.TYPE_APPLICATION) {
                s += 30
            }
            if (childCount > 0) s += 40 + minOf(childCount, 20)
            return s
        }

        fun safeChildCount(root: AccessibilityNodeInfo): Int = try {
            root.childCount
        } catch (_: Exception) {
            0
        }

        val candidates = mutableListOf<WinCand>()
        // Keep launcher/system root aside for empty-tree fallback only
        var fallbackRoot: AccessibilityNodeInfo? = null
        var fallbackPkg = ""

        // Prefer getWindows() TYPE_APPLICATION first (uiautomator-style), then
        // rootInActiveWindow as a fallback candidate — never the other way around
        // when both exist for the same package with unequal richness.
        // Probe ALL window types for diag (Mac: compare vs uiautomator).
        val winListProbe = try {
            windows?.toList()
        } catch (e: Exception) {
            Log.w(TAG, "windows() failed: ${e.message}")
            null
        }
        if (!winListProbe.isNullOrEmpty()) {
            for (w in winListProbe) {
                val probeRoot = try {
                    w.root
                } catch (_: Exception) {
                    null
                }
                val probePkg = probeRoot?.packageName?.toString().orEmpty()
                val probeKids = if (probeRoot != null) refreshRoot(probeRoot) else -1
                winDiag.add(
                    "probe:t=${w.type}:pkg=$probePkg:kids=$probeKids:" +
                        "f=${if (w.isFocused) 1 else 0}:a=${if (w.isActive) 1 else 0}",
                )
                if (probeRoot != null && w.type != AccessibilityWindowInfo.TYPE_APPLICATION) {
                    try {
                        probeRoot.recycle()
                    } catch (_: Exception) {
                    }
                    continue
                }
                if (w.type != AccessibilityWindowInfo.TYPE_APPLICATION) continue
                val root = probeRoot ?: continue
                val pkg = probePkg
                if (isIgnoredOverlayPackage(pkg)) {
                    try {
                        root.recycle()
                    } catch (_: Exception) {
                    }
                    continue
                }
                val kids = probeKids.coerceAtLeast(0)
                val existingIdx = candidates.indexOfFirst { it.pkg == pkg }
                if (existingIdx >= 0) {
                    val existing = candidates[existingIdx]
                    if (kids > existing.childCount) {
                        try {
                            existing.root.recycle()
                        } catch (_: Exception) {
                        }
                        candidates[existingIdx] = WinCand(
                            window = w,
                            root = root,
                            pkg = pkg,
                            score = scoreWindow(w, pkg, fromRootInActive = false, kids),
                            childCount = kids,
                        )
                    } else {
                        try {
                            root.recycle()
                        } catch (_: Exception) {
                        }
                    }
                    continue
                }
                candidates.add(
                    WinCand(
                        window = w,
                        root = root,
                        pkg = pkg,
                        score = scoreWindow(w, pkg, fromRootInActive = false, kids),
                        childCount = kids,
                    ),
                )
            }
        }
        val rawActive = try {
            rootInActiveWindow
        } catch (e: Exception) {
            Log.w(TAG, "rootInActiveWindow failed: ${e.message}")
            null
        }
        if (rawActive != null) {
            val pkg = rawActive.packageName?.toString().orEmpty()
            if (!isIgnoredOverlayPackage(pkg)) {
                val kids = refreshRoot(rawActive)
                winDiag.add("rootInActive:pkg=$pkg:kids=$kids")
                val existingIdx = candidates.indexOfFirst { it.pkg == pkg }
                if (existingIdx >= 0) {
                    val existing = candidates[existingIdx]
                    // Keep windows() root when it is richer or equal — rootInActive
                    // for Taimi/Hinge often reports the package with 0 children.
                    if (kids > existing.childCount) {
                        try {
                            existing.root.recycle()
                        } catch (_: Exception) {
                        }
                        candidates[existingIdx] = WinCand(
                            window = null,
                            root = rawActive,
                            pkg = pkg,
                            score = scoreWindow(null, pkg, fromRootInActive = true, kids),
                            childCount = kids,
                        )
                    } else {
                        Log.i(
                            TAG,
                            "prefer windows() root pkg=$pkg kids=${existing.childCount} " +
                                "over rootInActive kids=$kids",
                        )
                        try {
                            rawActive.recycle()
                        } catch (_: Exception) {
                        }
                    }
                } else {
                    candidates.add(
                        WinCand(
                            window = null,
                            root = rawActive,
                            pkg = pkg,
                            score = scoreWindow(null, pkg, fromRootInActive = true, kids),
                            childCount = kids,
                        ),
                    )
                }
            } else {
                // Spay/SystemUI: never preferred. Launcher: keep as last-resort
                // fallback so home dumps are never windows=0.
                val isSpayOrUi = pkg.lowercase().let {
                    it.contains("spay") || it.contains("systemui") ||
                        it.contains("mobilerun.selfhosted") || it == selfPkg
                }
                if (!isSpayOrUi && PreferredPackagePolicy.fallbackRoot(pkg, true)) {
                    fallbackRoot = rawActive
                    fallbackPkg = pkg
                    Log.i(TAG, "keep rootInActiveWindow pkg=$pkg as empty-tree fallback")
                } else {
                    Log.i(TAG, "skip rootInActiveWindow pkg=$pkg (overlay/system)")
                    try {
                        rawActive.recycle()
                    } catch (_: Exception) {
                    }
                }
            }
        }
        // Prefer hint via score; NEVER filter away a non-matching best.
        val policyCands = candidates.map {
            PreferredPackagePolicy.Cand(
                pkg = it.pkg,
                score = it.score,
                fromRootInActive = it.window == null,
                isIgnoredOverlay = it.isIgnoredOverlay,
            )
        }
        val selectedPkg = PreferredPackagePolicy.selectPreferred(policyCands, hint)?.pkg
        val best = candidates.firstOrNull { it.pkg == selectedPkg }
            ?: candidates.maxByOrNull { it.score }
        if (best != null) {
            preferredActiveRoot = best.root
            preferredActivePkg = best.pkg
            preferredActiveFromWindows = best.window != null
            if (!hint.isNullOrBlank() && !packageMatchesHint(best.pkg, hint)) {
                Log.i(
                    TAG,
                    "hint=$hint unmatched; emitting live window pkg=${best.pkg} " +
                        "(prefer-not-filter)",
                )
            }
            for (c in candidates) {
                if (c.root !== best.root) {
                    try {
                        c.root.recycle()
                    } catch (_: Exception) {
                    }
                }
            }
            // Drop unused fallback
            if (fallbackRoot != null && fallbackRoot !== best.root) {
                try {
                    fallbackRoot.recycle()
                } catch (_: Exception) {
                }
                fallbackRoot = null
            }
        } else if (fallbackRoot != null) {
            // Launcher-only / chrome-only: still emit so tree is never empty
            preferredActiveRoot = fallbackRoot
            preferredActivePkg = fallbackPkg
            preferredActiveFromWindows = false
            Log.i(
                TAG,
                "no app window for hint=${hint ?: "-"}; " +
                    "fallback rootInActiveWindow pkg=$fallbackPkg",
            )
            fallbackRoot = null
        }
        if (preferredActiveRoot != null && !pastDeadline()) {
            Log.i(
                TAG,
                "active window pkg=$preferredActivePkg hint=${hint ?: "-"} " +
                    "fromWindows=$preferredActiveFromWindows",
            )
            val n = emitWindow("active", "active", 1, preferredActiveRoot)
            // Only skip re-walk of same pkg when we actually emitted nodes —
            // Taimi/Compose often returns kids=0 until a second getWindows root.
            if (n > 0 && preferredActivePkg.isNotBlank()) {
                emittedPkgs.add(preferredActivePkg)
            }
            activeEmitted = true
            try {
                preferredActiveRoot.recycle()
            } catch (_: Exception) {
            }
        }

        // Always walk interactive windows — WhatsApp often parks the list /
        // compose field in a non-active application window on One UI / S21+.
        if (!pastDeadline()) {
            val winList = winListProbe ?: try {
                windows?.toList()
            } catch (e: Exception) {
                Log.w(TAG, "windows() failed: ${e.message}")
                null
            }
            if (!winList.isNullOrEmpty()) {
                val ordered = winList.sortedByDescending { w ->
                    when (w.type) {
                        AccessibilityWindowInfo.TYPE_APPLICATION -> 4
                        AccessibilityWindowInfo.TYPE_INPUT_METHOD -> 3
                        AccessibilityWindowInfo.TYPE_SYSTEM -> 2
                        else -> 1
                    } + (if (w.isFocused) 1 else 0) + (if (w.isActive) 1 else 0)
                }
                for (window in ordered) {
                    if (pastDeadline() || counter[0] >= MAX_NODES || sb.length >= MAX_TREE_CHARS) break
                    if (
                        window.type != AccessibilityWindowInfo.TYPE_APPLICATION &&
                        window.type != AccessibilityWindowInfo.TYPE_INPUT_METHOD
                    ) {
                        // Skip SYSTEM chrome — never dump as app content
                        continue
                    }
                    val root = try {
                        window.root
                    } catch (_: Exception) {
                        null
                    } ?: continue
                    val pkg = root.packageName?.toString().orEmpty()
                    if (isIgnoredOverlayPackage(pkg) &&
                        window.type != AccessibilityWindowInfo.TYPE_INPUT_METHOD
                    ) {
                        try {
                            root.recycle()
                        } catch (_: Exception) {
                        }
                        continue
                    }
                    if (pkg.isNotBlank() && pkg in emittedPkgs) {
                        try {
                            root.recycle()
                        } catch (_: Exception) {
                        }
                        continue
                    }
                    val title = try {
                        window.title?.toString().orEmpty()
                    } catch (_: Exception) {
                        ""
                    }
                    val typeLabel = "${window.type}" + if (title.isNotEmpty()) ":${title.take(24)}" else ""
                    val n = emitWindow(
                        id = "${window.id}",
                        type = typeLabel,
                        focused = if (window.isFocused) 1 else 0,
                        root = root,
                    )
                    if (n > 0 && pkg.isNotBlank()) emittedPkgs.add(pkg)
                    try {
                        root.recycle()
                    } catch (_: Exception) {
                    }
                }
            }
        }

        val body = sb.toString()
        val diagAttr = xmlEsc(winDiag.take(24).joinToString("|"))
        Log.i(TAG, "win_diag=$diagAttr nodes=${counter[0]} text=${textCounter[0]}")
        if (body.isBlank()) {
            return TreeResult(
                tree = """<hierarchy windows="0" nodes="0" empty="true" text_nodes="0" needs_vision="true" win_diag="$diagAttr"/>""",
                packageName = "",
                empty = true,
                chars = 0,
                nodes = 0,
                partial = partial,
                cached = false,
                buildMs = 0,
                bytes = 0,
                treeGzB64 = null,
                anrDismissed = false,
                appNodes = 0,
                textNodes = 0,
                needsVision = true,
            )
        }
        val truncated = body.length >= MAX_TREE_CHARS || counter[0] >= MAX_NODES || partial
        val clipped = if (body.length > MAX_TREE_CHARS) {
            body.take(MAX_TREE_CHARS) + "\n<!-- trunc -->\n"
        } else {
            body
        }
        // Prefer target hint, else first non-overlay app package
        val hintPkg = preferredPkgHint
        val primaryPkg = pkgs.firstOrNull { packageMatchesHint(it, hintPkg) }
            ?: pkgs.firstOrNull { !isIgnoredOverlayPackage(it) }
            ?: pkgs.firstOrNull().orEmpty()
        val nodeCount = counter[0]
        val appNodeCount = appCounter[0]
        val textNodeCount = textCounter[0]
        // Launcher nodes count as app_nodes (home is not SystemUI chrome).
        val effectiveAppNodes = if (
            appNodeCount == 0 && nodeCount > 0 && pkgs.any { isLauncherPackage(it) }
        ) {
            nodeCount
        } else {
            appNodeCount
        }
        // Empty only when nothing useful — SystemUI-only dumps stay empty;
        // launcher home with icons is NOT empty.
        // Hinge: containers with 0 text still count as non-empty → vision path.
        val isEmpty = nodeCount == 0 || effectiveAppNodes == 0
        val needsVision = isEmpty || textNodeCount == 0
        val mode = if (fullMode) "full" else "compact"
        val tree = buildString {
            append("<hierarchy windows=\"$windowCount\" nodes=\"$nodeCount\" ")
            append("app_nodes=\"$effectiveAppNodes\" text_nodes=\"$textNodeCount\" ")
            append("needs_vision=\"$needsVision\" ")
            append("partial=\"$truncated\" empty=\"$isEmpty\" mode=\"$mode\" ")
            append("win_diag=\"$diagAttr\" ")
            append("packages=\"${xmlEsc(pkgs.joinToString(","))}\">\n")
            append(clipped)
            append("</hierarchy>")
        }
        return TreeResult(
            tree = tree,
            packageName = primaryPkg,
            empty = isEmpty,
            chars = tree.length,
            nodes = nodeCount,
            partial = truncated,
            cached = false,
            buildMs = 0,
            bytes = tree.toByteArray(Charsets.UTF_8).size,
            treeGzB64 = null,
            anrDismissed = false,
            appNodes = effectiveAppNodes,
            textNodes = textNodeCount,
            needsVision = needsVision,
        )
    }

    /**
     * Collect shallow descendant text/desc so clickable parents (WhatsApp row
     * containers) carry the label even when the TextView is a child.
     */
    private fun mergeChildLabels(node: AccessibilityNodeInfo, maxDepth: Int = 2): Pair<String, String> {
        val texts = linkedSetOf<String>()
        val descs = linkedSetOf<String>()
        fun walk(n: AccessibilityNodeInfo?, depth: Int) {
            if (n == null || depth > maxDepth) return
            n.text?.toString()?.trim()?.takeIf { it.isNotEmpty() }?.let { texts.add(it.take(60)) }
            n.contentDescription?.toString()?.trim()?.takeIf { it.isNotEmpty() }?.let {
                descs.add(it.take(60))
            }
            if (Build.VERSION.SDK_INT >= 26) {
                try {
                    n.hintText?.toString()?.trim()?.takeIf { it.isNotEmpty() }?.let {
                        texts.add(it.take(60))
                    }
                } catch (_: Exception) {
                }
            }
            if (depth == maxDepth) return
            for (i in 0 until n.childCount.coerceAtMost(12)) {
                val child = try {
                    n.getChild(i)
                } catch (_: Exception) {
                    null
                } ?: continue
                walk(child, depth + 1)
                try {
                    child.recycle()
                } catch (_: Exception) {
                }
            }
        }
        walk(node, 0)
        return texts.joinToString(" · ").take(120) to descs.joinToString(" · ").take(80)
    }

    /**
     * Emit interactive / text-bearing nodes with short keys:
     * t=text, d=desc, h=hint, i=id, c=clickable, e=editable, s=scrollable,
     * v=0 when not visibleToUser, xy=center, b=bounds.
     * Never prune subtrees on isVisibleToUser=false (Hinge/Taimi OEM quirk).
     */
    private fun buildCompactNodes(
        node: AccessibilityNodeInfo?,
        indent: String,
        sb: StringBuilder,
        counter: IntArray,
        depth: Int,
        deadlineMs: Long,
        fullMode: Boolean,
        markPartial: () -> Unit,
        appCounter: IntArray? = null,
        textCounter: IntArray? = null,
    ) {
        if (node == null || counter[0] >= MAX_NODES || depth > MAX_DEPTH) return
        if (sb.length >= MAX_TREE_CHARS) return
        if (SystemClock.elapsedRealtime() >= deadlineMs) {
            markPartial()
            return
        }

        var text = node.text?.toString().orEmpty().take(80)
        var contentDesc = node.contentDescription?.toString().orEmpty().take(60)
        val hint = if (Build.VERSION.SDK_INT >= 26) {
            try {
                node.hintText?.toString().orEmpty().take(60)
            } catch (_: Exception) {
                ""
            }
        } else {
            ""
        }
        // Portal-compatible: keep full resource-id (com.whatsapp:id/entry)
        val viewId = node.viewIdResourceName.orEmpty().take(96)
        val className = node.className?.toString().orEmpty().let { cn ->
            when {
                cn.endsWith("EditText") -> "EditText"
                cn.endsWith("TextView") -> "TextView"
                cn.endsWith("Button") -> "Button"
                cn.endsWith("ImageButton") -> "ImageButton"
                cn.endsWith("ImageView") -> "ImageView"
                cn.endsWith("RecyclerView") -> "RecyclerView"
                cn.endsWith("ListView") -> "ListView"
                cn.contains('.') -> cn.substringAfterLast('.').take(32)
                else -> cn.take(32)
            }
        }
        val inputType = try {
            if (node.isEditable) node.inputType else 0
        } catch (_: Exception) {
            0
        }
        val visible = try {
            node.isVisibleToUser
        } catch (_: Exception) {
            true
        }
        // Keep clickable/editable even if isVisibleToUser is flaky on OEM skins.
        // IMPORTANT: do NOT return early on !visible — still walk children
        // (Hinge Discover / Taimi park useful nodes under invisible parents).
        val mustKeep = node.isClickable || node.isEditable || node.isCheckable ||
            node.isLongClickable

        val interactive = mustKeep || node.isScrollable
        val hasLabel = text.isNotEmpty() || contentDesc.isNotEmpty() || hint.isNotEmpty()
        // Invisible alone is not enough to emit — but we still recurse children below
        val interesting = interactive || hasLabel || fullMode

        // Skip inert wrappers; always recurse into children (even if parent invisible)
        if (!interesting) {
            val childCount = node.childCount
            for (i in 0 until childCount) {
                if (counter[0] >= MAX_NODES || sb.length >= MAX_TREE_CHARS) break
                if (SystemClock.elapsedRealtime() >= deadlineMs) {
                    markPartial()
                    break
                }
                val child = try {
                    node.getChild(i)
                } catch (_: Exception) {
                    null
                }
                buildCompactNodes(
                    child, indent, sb, counter, depth + 1, deadlineMs, fullMode,
                    markPartial, appCounter, textCounter,
                )
                try {
                    child?.recycle()
                } catch (_: Exception) {
                }
            }
            return
        }

        // Merge child labels into clickable/editable parents (WhatsApp rows)
        if (interactive && text.isEmpty() && contentDesc.isEmpty()) {
            val merged = mergeChildLabels(node)
            if (text.isEmpty()) text = merged.first
            if (contentDesc.isEmpty()) contentDesc = merged.second
        }

        counter[0]++
        appCounter?.let { it[0]++ }
        if (text.isNotEmpty() || contentDesc.isNotEmpty() || hint.isNotEmpty()) {
            textCounter?.let { it[0]++ }
        }
        val bounds = android.graphics.Rect()
        node.getBoundsInScreen(bounds)
        val cx = (bounds.left + bounds.right) / 2
        val cy = (bounds.top + bounds.bottom) / 2

        sb.append(indent).append("<n")
        if (text.isNotEmpty()) sb.append(" t=\"${xmlEsc(text)}\"")
        if (contentDesc.isNotEmpty()) sb.append(" d=\"${xmlEsc(contentDesc)}\"")
        if (hint.isNotEmpty()) sb.append(" h=\"${xmlEsc(hint)}\"")
        if (viewId.isNotEmpty()) sb.append(" i=\"${xmlEsc(viewId)}\"")
        if (className.isNotEmpty()) sb.append(" cls=\"${xmlEsc(className)}\"")
        if (inputType != 0) sb.append(" it=\"$inputType\"")
        if (node.isClickable) sb.append(" c=\"1\"")
        if (node.isEditable) sb.append(" e=\"1\"")
        if (node.isFocused) sb.append(" f=\"1\"")
        if (node.isCheckable) sb.append(" k=\"${if (node.isChecked) 1 else 0}\"")
        if (node.isScrollable) sb.append(" s=\"1\"")
        if (!visible) sb.append(" v=\"0\"")
        sb.append(" xy=\"$cx,$cy\"")
        sb.append(" b=\"${bounds.left},${bounds.top},${bounds.right},${bounds.bottom}\"")
        sb.append("/>\n")

        // Still walk children of interesting containers (lists etc.)
        val childCount = node.childCount
        for (i in 0 until childCount) {
            if (counter[0] >= MAX_NODES || sb.length >= MAX_TREE_CHARS) break
            if (SystemClock.elapsedRealtime() >= deadlineMs) {
                markPartial()
                break
            }
            val child = try {
                node.getChild(i)
            } catch (_: Exception) {
                null
            }
            buildCompactNodes(
                child, indent, sb, counter, depth + 1, deadlineMs, fullMode,
                markPartial, appCounter, textCounter,
            )
            try {
                child?.recycle()
            } catch (_: Exception) {
            }
        }
    }

    private fun gzipB64(plain: String): String? {
        if (plain.length < 512) return null
        return try {
            val baos = ByteArrayOutputStream()
            GZIPOutputStream(baos).use { gz ->
                gz.write(plain.toByteArray(Charsets.UTF_8))
            }
            Base64.encodeToString(baos.toByteArray(), Base64.NO_WRAP)
        } catch (e: Exception) {
            Log.w(TAG, "gzip failed: ${e.message}")
            null
        }
    }

    private fun xmlEsc(s: String): String =
        s.replace("&", "&amp;")
            .replace("\"", "&quot;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", " ")
            .take(120)

    /**
     * Capture JPEG base64 via AccessibilityService.takeScreenshot (API 30+).
     * Requires android:canTakeScreenshot="true" in accessibility_service_config.xml
     * and a rebound service after install. Never hangs past the latch; returns
     * null with logged error codes (incl. INTERVAL_TIME_SHORT / FLAG_SECURE black).
     */
    fun takeScreenshotJpegBase64(maxWidth: Int = 720, quality: Int = 45): String? {
        val detail = takeScreenshotJpegBase64Detailed(maxWidth, quality)
        return detail["data"] as? String
    }

    fun takeScreenshotJpegBase64Detailed(
        maxWidth: Int = 720,
        quality: Int = 45,
    ): Map<String, Any?> {
        val detail = takeScreenshotJpegDetailed(maxWidth, quality)
        val jpeg = detail["jpeg"] as? ByteArray
        if (jpeg != null && jpeg.isNotEmpty()) {
            val b64 = Base64.encodeToString(jpeg, Base64.NO_WRAP)
            return detail.filterKeys { it != "jpeg" } + mapOf(
                "ok" to true,
                "data" to b64,
                "bytes" to jpeg.size,
                "b64_chars" to b64.length,
            )
        }
        return detail.filterKeys { it != "jpeg" }
    }

    /**
     * Capture JPEG bytes for S3 upload (avoid WS base64 blowing 32KB frames).
     * Returns map with ``jpeg`` ByteArray on success + ``source`` / ``bytes``.
     */
    fun takeScreenshotJpegDetailed(
        maxWidth: Int = 720,
        quality: Int = 45,
    ): Map<String, Any?> {
        // 1) AccessibilityService.takeScreenshot (API 30+) — short latch so the
        //    RPC never sits past the cloud timeout when Samsung stalls.
        if (Build.VERSION.SDK_INT >= 30) {
            // Respect Android's ~1/sec rate limit before calling again
            val since = SystemClock.elapsedRealtime() - lastScreenshotAtMs
            if (lastScreenshotAtMs > 0L && since < 1100L) {
                try {
                    Thread.sleep(1100L - since)
                } catch (_: InterruptedException) {
                }
            }
            var attempt = 0
            while (attempt < 2) {
                attempt++
                val latch = CountDownLatch(1)
                val jpegRef = AtomicReference<ByteArray?>(null)
                val err = AtomicReference<String?>(null)
                val errCode = AtomicReference<Int?>(null)
                try {
                    // Callback must run on a live executor — never block the main
                    // looper; screenshotExecutor is a dedicated daemon thread.
                    takeScreenshot(
                        Display.DEFAULT_DISPLAY,
                        screenshotExecutor,
                        object : TakeScreenshotCallback {
                            override fun onSuccess(screenshot: ScreenshotResult) {
                                try {
                                    val hw = screenshot.hardwareBuffer
                                    val colorSpace = screenshot.colorSpace
                                    val bitmap = Bitmap.wrapHardwareBuffer(hw, colorSpace)
                                    hw.close()
                                    if (bitmap == null) {
                                        err.set("wrapHardwareBuffer_null")
                                        return
                                    }
                                    val software = bitmap.copy(Bitmap.Config.ARGB_8888, false)
                                    bitmap.recycle()
                                    if (software == null) {
                                        err.set("copy_software_null")
                                        return
                                    }
                                    // FLAG_SECURE (Badoo chat etc.) → mostly black
                                    if (isMostlyBlackBitmap(software)) {
                                        err.set("secure_window_or_black")
                                        software.recycle()
                                        Log.w(
                                            TAG,
                                            "takeScreenshot black/FLAG_SECURE frame — skip",
                                        )
                                        return
                                    }
                                    val scaled = scaleBitmap(software, maxWidth)
                                    if (scaled !== software) software.recycle()
                                    val baos = ByteArrayOutputStream()
                                    scaled.compress(Bitmap.CompressFormat.JPEG, quality, baos)
                                    scaled.recycle()
                                    jpegRef.set(baos.toByteArray())
                                } catch (e: Exception) {
                                    Log.e(TAG, "screenshot encode failed", e)
                                    err.set(e.message)
                                } finally {
                                    latch.countDown()
                                }
                            }

                            override fun onFailure(errorCode: Int) {
                                val name = screenshotErrorName(errorCode)
                                Log.w(
                                    TAG,
                                    "takeScreenshot failed code=$errorCode ($name)",
                                )
                                errCode.set(errorCode)
                                err.set("code_${errorCode}_$name")
                                latch.countDown()
                            }
                        },
                    )
                    lastScreenshotAtMs = SystemClock.elapsedRealtime()
                    val ok = latch.await(3, TimeUnit.SECONDS)
                    if (!ok) {
                        Log.w(TAG, "takeScreenshot latch timeout 3s — returning error")
                        err.set(err.get() ?: "latch_timeout_3s")
                    }
                    val jpeg = jpegRef.get()
                    if (jpeg != null && jpeg.isNotEmpty()) {
                        Log.i(
                            TAG,
                            "takeScreenshot ok source=a11y bytes=${jpeg.size} " +
                                "maxWidth=$maxWidth quality=$quality",
                        )
                        return mapOf(
                            "ok" to true,
                            "jpeg" to jpeg,
                            "bytes" to jpeg.size,
                            "source" to "a11y",
                        )
                    }
                    val code = errCode.get()
                    // ERROR_TAKE_SCREENSHOT_INTERVAL_TIME_SHORT = 3 — wait + retry
                    if (code == 3 && attempt < 2) {
                        Log.i(TAG, "takeScreenshot rate-limited; sleep 1100ms + retry")
                        try {
                            Thread.sleep(1100L)
                        } catch (_: InterruptedException) {
                        }
                        continue
                    }
                    Log.w(TAG, "takeScreenshot empty err=${err.get()}")
                    // Fall through to MediaProjection; keep error for response
                    val a11yErr = err.get()
                    val mp = ScreenCaptureService.lastJpegBase64()?.let {
                        Base64.decode(it, Base64.DEFAULT)
                    }
                    if (mp != null && mp.isNotEmpty()) {
                        Log.i(
                            TAG,
                            "screenshot fallback MediaProjection bytes=${mp.size}",
                        )
                        return mapOf(
                            "ok" to true,
                            "jpeg" to mp,
                            "bytes" to mp.size,
                            "source" to "media_projection",
                            "a11y_error" to a11yErr,
                        )
                    }
                    return mapOf(
                        "ok" to false,
                        "error" to (a11yErr ?: "screenshot unavailable"),
                        "error_code" to code,
                        "a11y" to true,
                        "media_projection" to ScreenCaptureService.isStreaming(),
                    )
                } catch (e: Exception) {
                    Log.e(TAG, "takeScreenshot threw", e)
                    err.set(e.message)
                }
            }
        } else {
            Log.w(TAG, "takeScreenshot requires API 30+")
        }
        // 2) MediaProjection live-view last frame (no new consent)
        val mp = ScreenCaptureService.lastJpegBase64()?.let {
            Base64.decode(it, Base64.DEFAULT)
        }
        if (mp != null && mp.isNotEmpty()) {
            Log.i(TAG, "screenshot fallback MediaProjection bytes=${mp.size}")
            return mapOf(
                "ok" to true,
                "jpeg" to mp,
                "bytes" to mp.size,
                "source" to "media_projection",
            )
        }
        Log.w(TAG, "screenshot unavailable (a11y+MediaProjection)")
        return mapOf(
            "ok" to false,
            "error" to "screenshot unavailable",
            "a11y" to (Build.VERSION.SDK_INT >= 30),
            "media_projection" to ScreenCaptureService.isStreaming(),
        )
    }

    private fun screenshotErrorName(code: Int): String = when (code) {
        1 -> "INTERNAL_ERROR"
        2 -> "NO_ACCESSIBILITY_ACCESS"
        3 -> "INTERVAL_TIME_SHORT"
        4 -> "INVALID_DISPLAY"
        5 -> "INVALID_WINDOW"
        else -> "UNKNOWN"
    }

    /** FLAG_SECURE / black frames — sample grid; >92% near-black → treat as unusable. */
    private fun isMostlyBlackBitmap(bmp: Bitmap): Boolean {
        val w = bmp.width
        val h = bmp.height
        if (w < 2 || h < 2) return true
        var dark = 0
        var total = 0
        val stepX = (w / 8).coerceAtLeast(1)
        val stepY = (h / 8).coerceAtLeast(1)
        var y = 0
        while (y < h) {
            var x = 0
            while (x < w) {
                val c = bmp.getPixel(x, y)
                val r = (c shr 16) and 0xff
                val g = (c shr 8) and 0xff
                val b = c and 0xff
                if (r < 18 && g < 18 && b < 18) dark++
                total++
                x += stepX
            }
            y += stepY
        }
        return total > 0 && dark * 100 / total >= 92
    }

    private fun scaleBitmap(src: Bitmap, maxWidth: Int): Bitmap {
        if (src.width <= maxWidth) return src
        val ratio = maxWidth.toFloat() / src.width
        val h = (src.height * ratio).toInt().coerceAtLeast(1)
        return Bitmap.createScaledBitmap(src, maxWidth, h, true)
    }

    suspend fun tapAsync(x: Int, y: Int): Boolean = suspendCancellableCoroutine { cont ->
        tap(x, y) { success ->
            if (cont.isActive) cont.resume(success)
        }
    }

    suspend fun swipeAsync(x1: Int, y1: Int, x2: Int, y2: Int, durationMs: Long): Boolean =
        suspendCancellableCoroutine { cont ->
            swipe(x1, y1, x2, y2, durationMs) { success ->
                if (cont.isActive) cont.resume(success)
            }
        }

    /**
     * Portal-compatible text input: single ACTION_SET_TEXT with calculateInputText
     * (append vs clear + selection). Our additions kept on top:
     * prefer WhatsApp compose entry, ACTION_CLICK focus, clipboard paste fallback.
     * [humanize] is retained for API compat but no longer chunk-sleeps (timeouts).
     */
    fun inputText(
        text: String,
        clear: Boolean = false,
        humanize: Boolean = true,
    ): Boolean {
        @Suppress("UNUSED_PARAMETER")
        val _humanize = humanize
        val root = rootInActiveWindow ?: return false
        // The field the app has focused is the typing target: use it before
        // any tree-order scan. Facebook keeps off-screen feed editables in
        // the tree, and the old tree-order pick could type into a field the
        // user never sees while the visible box stayed empty.
        var targetNode = findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
        if (targetNode != null && !targetNode.isEditable) {
            try {
                targetNode.recycle()
            } catch (_: Exception) {
            }
            targetNode = null
        }
        // Prefer chat compose (WhatsApp entry / Message hint) over search EditTexts
        if (targetNode == null) {
            targetNode = findComposeEditable(root)
        }
        if (targetNode == null) {
            targetNode = findEditable(root)
        }
        if (targetNode == null) {
            try {
                root.recycle()
            } catch (_: Exception) {
            }
            return false
        }
        try {
            try {
                targetNode.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
                targetNode.performAction(AccessibilityNodeInfo.ACTION_CLICK)
            } catch (_: Exception) {
            }

            val currentText = targetNode.text?.toString()
            val hintText = try {
                targetNode.hintText?.toString()
            } catch (_: Exception) {
                null
            }
            val effectiveCurrent =
                if (!hintText.isNullOrEmpty() && currentText == hintText) ""
                else currentText.orEmpty()
            val currentLength = effectiveCurrent.length
            val rawStart = try {
                targetNode.textSelectionStart
            } catch (_: Exception) {
                -1
            }
            val rawEnd = try {
                targetNode.textSelectionEnd
            } catch (_: Exception) {
                -1
            }
            val selectionStart =
                if (rawStart >= 0) rawStart.coerceIn(0, currentLength) else currentLength
            val selectionEnd =
                if (rawEnd >= 0) rawEnd.coerceIn(0, currentLength) else selectionStart

            val finalText = calculateInputText(
                currentText = currentText,
                hintText = hintText,
                newText = text,
                clear = clear,
                selectionStart = selectionStart,
                selectionEnd = selectionEnd,
            )

            val arguments = android.os.Bundle()
            arguments.putCharSequence(
                AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
                finalText,
            )
            val setTextSuccess =
                targetNode.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, arguments)
            if (setTextSuccess) {
                return verifyTextLanded(targetNode, finalText, effectiveCurrent)
            }
            // Clipboard paste fallback (OEM / Secure Folder windows that reject SET_TEXT)
            if (pasteViaClipboard(targetNode, finalText)) {
                return verifyTextLanded(targetNode, finalText, effectiveCurrent)
            }
            return false
        } catch (e: Exception) {
            Log.e(TAG, "Error setting text via accessibility: ${e.message}")
            return false
        } finally {
            try {
                if (targetNode !== root) targetNode.recycle()
            } catch (_: Exception) {
            }
            try {
                root.recycle()
            } catch (_: Exception) {
            }
        }
    }

    /**
     * Read the field back after typing: ACTION_SET_TEXT can report success
     * on a stale or wrong node while the visible box stays empty. Only
     * fail when the node can be re-read and shows nothing landed (empty,
     * or still the old text) — a field that holds the new text, or one
     * that cannot be re-read, keeps the old behaviour.
     */
    private fun verifyTextLanded(
        node: AccessibilityNodeInfo,
        expected: String,
        previousText: String,
    ): Boolean {
        if (expected.isEmpty()) return true
        return try {
            if (!node.refresh()) return true
            val actual = node.text?.toString().orEmpty()
            if (actual.isEmpty()) return false
            if (actual == previousText && actual != expected) return false
            actual == expected || actual.contains(expected)
        } catch (_: Exception) {
            true
        }
    }

    private fun pasteViaClipboard(edit: AccessibilityNodeInfo, value: String): Boolean {
        return try {
            val cm = getSystemService(CLIPBOARD_SERVICE) as android.content.ClipboardManager
            cm.setPrimaryClip(android.content.ClipData.newPlainText("mobilerun", value))
            edit.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
            edit.performAction(AccessibilityNodeInfo.ACTION_PASTE)
        } catch (e: Exception) {
            Log.w(TAG, "clipboard paste failed: ${e.message}")
            false
        }
    }

    /**
     * Prefer WhatsApp/IG/etc compose boxes over search fields.
     * Matches resource-id `…:id/entry` and hints like "Message".
     */
    private fun findComposeEditable(node: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        if (node == null) return null
        val preferred = ArrayList<AccessibilityNodeInfo>()
        val searchy = ArrayList<AccessibilityNodeInfo>()
        collectEditables(node, preferred, searchy)
        // Focused first, then visible, then tree order: an off-screen feed
        // editable must never win over the field the user is looking at.
        val ordered = preferred.sortedWith(
            compareByDescending<AccessibilityNodeInfo> { it.isFocused }
                .thenByDescending { it.isVisibleToUser },
        )
        val hit = ordered.firstOrNull() ?: searchy.firstOrNull()
        // Recycle losers
        for (n in preferred) {
            if (n !== hit) {
                try {
                    n.recycle()
                } catch (_: Exception) {
                }
            }
        }
        for (n in searchy) {
            if (n !== hit) {
                try {
                    n.recycle()
                } catch (_: Exception) {
                }
            }
        }
        return hit
    }

    private fun collectEditables(
        node: AccessibilityNodeInfo,
        preferred: MutableList<AccessibilityNodeInfo>,
        searchy: MutableList<AccessibilityNodeInfo>,
    ) {
        if (node.isEditable) {
            val id = node.viewIdResourceName.orEmpty().lowercase()
            val hint = (node.hintText?.toString() ?: "").lowercase()
            val desc = (node.contentDescription?.toString() ?: "").lowercase()
            val text = (node.text?.toString() ?: "").lowercase()
            val blob = "$id $hint $desc $text"
            val isSearch = blob.contains("search") || id.endsWith("/search") ||
                id.contains("search_input") || id.contains("search_src")
            val isCompose = id.endsWith("/entry") || id.endsWith(":id/entry") ||
                id.contains("entry") || id.contains("compose") ||
                hint.contains("message") || desc == "message" ||
                hint.contains("type a message") || hint.contains("write a message")
            val copy = AccessibilityNodeInfo.obtain(node)
            if (isCompose && !isSearch) {
                preferred.add(copy)
            } else if (isSearch) {
                searchy.add(copy)
            } else {
                // Neutral editable — treat as weak preferred (bottom compose often lacks hint)
                preferred.add(copy)
            }
        }
        for (i in 0 until node.childCount) {
            val child = try {
                node.getChild(i)
            } catch (_: Exception) {
                null
            } ?: continue
            collectEditables(child, preferred, searchy)
            try {
                child.recycle()
            } catch (_: Exception) {
            }
        }
    }

    private fun findEditable(node: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        if (node == null) return null
        if (node.isEditable) return AccessibilityNodeInfo.obtain(node)
        for (i in 0 until node.childCount) {
            val child = try {
                node.getChild(i)
            } catch (_: Exception) {
                null
            } ?: continue
            val found = findEditable(child)
            try {
                child.recycle()
            } catch (_: Exception) {
            }
            if (found != null) return found
        }
        return null
    }

    /**
     * Portal-style focused editable metadata for IME / cloud: package, viewId,
     * hint, inputType, className, text — used to tell search vs compose.
     */
    fun focusedEditableMeta(): Map<String, Any?> {
        val root = rootInActiveWindow
        var target: AccessibilityNodeInfo? = null
        try {
            target = findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
            if (target == null || !target.isEditable) {
                try {
                    target?.recycle()
                } catch (_: Exception) {
                }
                target = findComposeEditable(root) ?: findEditable(root)
            }
            if (target == null) {
                return mapOf("ok" to false)
            }
            val hint = try {
                if (Build.VERSION.SDK_INT >= 26) target.hintText?.toString() else null
            } catch (_: Exception) {
                null
            }
            return mapOf(
                "ok" to true,
                "packageName" to target.packageName?.toString(),
                "viewId" to target.viewIdResourceName,
                "hint" to hint,
                "inputType" to try {
                    target.inputType
                } catch (_: Exception) {
                    0
                },
                "className" to target.className?.toString(),
                "text" to target.text?.toString(),
                "editable" to target.isEditable,
                "focused" to target.isFocused,
            )
        } catch (e: Exception) {
            Log.w(TAG, "focusedEditableMeta: ${e.message}")
            return mapOf("ok" to false, "error" to (e.message ?: "error"))
        } finally {
            try {
                target?.recycle()
            } catch (_: Exception) {
            }
            try {
                root?.recycle()
            } catch (_: Exception) {
            }
        }
    }
}
