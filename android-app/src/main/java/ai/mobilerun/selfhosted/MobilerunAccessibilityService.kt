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

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        serviceInfo = serviceInfo?.apply {
            // INCLUDE_NOT_IMPORTANT_VIEWS is required for Compose / custom-view UIs
            // (IG, TikTok, dating apps) — without it rows and icon buttons vanish.
            flags = flags or
                AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS or
                AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS or
                AccessibilityServiceInfo.FLAG_INCLUDE_NOT_IMPORTANT_VIEWS
            // Content changes only — not TYPES_ALL_MASK (cheaper event delivery)
            eventTypes = AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED or
                AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED or
                AccessibilityEvent.TYPE_WINDOWS_CHANGED or
                AccessibilityEvent.TYPE_VIEW_FOCUSED or
                AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED
            feedbackType = AccessibilityServiceInfo.FEEDBACK_GENERIC
            notificationTimeout = 100
        } ?: serviceInfo
        Log.d(TAG, "Accessibility service connected flags=${serviceInfo?.flags}")
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

    /** Fire-and-forget tap — used when the cloud ACKs immediately. */
    fun tapFireAndForget(x: Int, y: Int, humanize: Boolean = true) {
        tap(x, y, humanize) { /* async verify is the cloud's job */ }
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
        swipe(x1, y1, x2, y2, durationMs) { }
    }

    fun pressBack(): Boolean = performGlobalAction(GLOBAL_ACTION_BACK)

    fun pressHome(): Boolean = performGlobalAction(GLOBAL_ACTION_HOME)

    fun pressRecents(): Boolean = performGlobalAction(GLOBAL_ACTION_RECENTS)

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
        rootInActiveWindow?.packageName?.toString()?.let { return it }
        windows?.firstOrNull { it.type == AccessibilityWindowInfo.TYPE_APPLICATION }
            ?.root?.packageName?.toString()?.let { return it }
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
            // Permission / consent popups — prefer the least-restrictive positive action
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

    /** Back-compat string dump used by older callers. */
    fun getUITree(): String = getUITreeDetailed(allowCache = true).tree

    /**
     * Build (or serve cached) compact UI tree.
     *
     * Orchestration + gzip run on [dumpThread] so WS / commandExecutor never walk
     * the tree. AccessibilityNodeInfo IPC runs on the service main looper (required —
     * off-main dumps hang ~5s and return empty on real devices and emulators).
     * Soft deadline returns a partial tree within ~3s rather than nothing.
     */
    fun getUITreeDetailed(allowCache: Boolean = true): TreeResult {
        val gen = contentGeneration.get()
        if (allowCache) {
            synchronized(cacheLock) {
                val hit = cachedResult
                if (
                    hit != null &&
                    cachedGeneration == gen &&
                    SystemClock.elapsedRealtime() - cachedAtMs < CACHE_TTL_MS
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

    private fun dumpUITreeCompact(deadlineMs: Long): TreeResult {
        // First pass: compact (interactive / text / desc). If too thin for the
        // foreground app, immediately re-walk in full mode (no interesting filter).
        val compact = dumpUITreeWalk(deadlineMs, fullMode = false)
        if (compact.nodes >= MIN_USEFUL_NODES || compact.empty) {
            return compact
        }
        val remaining = deadlineMs - SystemClock.elapsedRealtime()
        if (remaining < 400) {
            Log.w(TAG, "thin tree nodes=${compact.nodes}; no budget left for full re-dump")
            return compact.copy(partial = true)
        }
        Log.i(TAG, "thin tree nodes=${compact.nodes}; re-dumping uncompacted")
        val full = dumpUITreeWalk(deadlineMs, fullMode = true)
        return if (full.nodes >= compact.nodes) full.copy(partial = true) else compact.copy(partial = true)
    }

    private fun dumpUITreeWalk(deadlineMs: Long, fullMode: Boolean): TreeResult {
        val sb = StringBuilder(8192)
        val counter = intArrayOf(0)
        val pkgs = linkedSetOf<String>()
        var windowCount = 0
        var partial = false

        fun pastDeadline(): Boolean {
            if (SystemClock.elapsedRealtime() >= deadlineMs) {
                partial = true
                return true
            }
            return false
        }

        fun emitWindow(id: String, type: String, focused: Int, root: AccessibilityNodeInfo) {
            windowCount++
            val pkg = root.packageName?.toString().orEmpty()
            if (pkg.isNotEmpty()) pkgs.add(pkg)
            sb.append("<w id=\"$id\" t=\"$type\" p=\"${xmlEsc(pkg)}\" f=\"$focused\">\n")
            buildCompactNodes(
                root, " ", sb, counter, 0, deadlineMs, fullMode,
            ) { partial = true }
            sb.append("</w>\n")
        }

        // Prefer active root first
        var activeEmitted = false
        val active = try {
            rootInActiveWindow
        } catch (e: Exception) {
            Log.w(TAG, "rootInActiveWindow failed: ${e.message}")
            null
        }
        if (active != null && !pastDeadline()) {
            emitWindow("active", "active", 1, active)
            activeEmitted = true
            try {
                active.recycle()
            } catch (_: Exception) {
            }
        }

        // Always walk interactive windows — WhatsApp often parks the list /
        // compose field in a non-active application window on One UI / S21+.
        if (!pastDeadline()) {
            val winList = try {
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
                    // Skip the active window we already emitted as "active"
                    if (window.isActive && activeEmitted) continue
                    // Prefer application + IME; skip pure wallpaper/split décor
                    if (
                        window.type != AccessibilityWindowInfo.TYPE_APPLICATION &&
                        window.type != AccessibilityWindowInfo.TYPE_INPUT_METHOD &&
                        window.type != AccessibilityWindowInfo.TYPE_SYSTEM
                    ) {
                        continue
                    }
                    val root = try {
                        window.root
                    } catch (_: Exception) {
                        null
                    } ?: continue
                    val title = try {
                        window.title?.toString().orEmpty()
                    } catch (_: Exception) {
                        ""
                    }
                    val typeLabel = "${window.type}" + if (title.isNotEmpty()) ":${title.take(24)}" else ""
                    emitWindow(
                        id = "${window.id}",
                        type = typeLabel,
                        focused = if (window.isFocused) 1 else 0,
                        root = root,
                    )
                    try {
                        root.recycle()
                    } catch (_: Exception) {
                    }
                }
            }
        }

        val body = sb.toString()
        if (body.isBlank()) {
            return TreeResult(
                tree = """<hierarchy windows="0" nodes="0" empty="true"/>""",
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
            )
        }
        val truncated = body.length >= MAX_TREE_CHARS || counter[0] >= MAX_NODES || partial
        val clipped = if (body.length > MAX_TREE_CHARS) {
            body.take(MAX_TREE_CHARS) + "\n<!-- trunc -->\n"
        } else {
            body
        }
        val primaryPkg = pkgs.firstOrNull().orEmpty()
        val nodeCount = counter[0]
        val isEmpty = nodeCount == 0
        val mode = if (fullMode) "full" else "compact"
        val tree = buildString {
            append("<hierarchy windows=\"$windowCount\" nodes=\"$nodeCount\" ")
            append("partial=\"$truncated\" empty=\"$isEmpty\" mode=\"$mode\" ")
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
     * xy=center, b=bounds. Never drop EditText or clickable=true.
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
        val viewId = node.viewIdResourceName.orEmpty().let { id ->
            if (id.contains('/')) id.substringAfterLast('/') else id.takeLast(40)
        }
        val visible = try {
            node.isVisibleToUser
        } catch (_: Exception) {
            true
        }
        // Keep clickable/editable even if isVisibleToUser is flaky on OEM skins
        val mustKeep = node.isClickable || node.isEditable || node.isCheckable ||
            node.isLongClickable
        if (!visible && !mustKeep) return

        val interactive = mustKeep || node.isScrollable
        val hasLabel = text.isNotEmpty() || contentDesc.isNotEmpty() || hint.isNotEmpty()
        val interesting = interactive || hasLabel || fullMode

        // Skip inert wrappers; still recurse into visible children
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
                    child, indent, sb, counter, depth + 1, deadlineMs, fullMode, markPartial,
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
        val bounds = android.graphics.Rect()
        node.getBoundsInScreen(bounds)
        val cx = (bounds.left + bounds.right) / 2
        val cy = (bounds.top + bounds.bottom) / 2

        sb.append(indent).append("<n")
        if (text.isNotEmpty()) sb.append(" t=\"${xmlEsc(text)}\"")
        if (contentDesc.isNotEmpty()) sb.append(" d=\"${xmlEsc(contentDesc)}\"")
        if (hint.isNotEmpty()) sb.append(" h=\"${xmlEsc(hint)}\"")
        if (viewId.isNotEmpty()) sb.append(" i=\"${xmlEsc(viewId)}\"")
        if (node.isClickable) sb.append(" c=\"1\"")
        if (node.isEditable) sb.append(" e=\"1\"")
        if (node.isCheckable) sb.append(" k=\"${if (node.isChecked) 1 else 0}\"")
        if (node.isScrollable) sb.append(" s=\"1\"")
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
                child, indent, sb, counter, depth + 1, deadlineMs, fullMode, markPartial,
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

    fun takeScreenshotJpegBase64(maxWidth: Int = 720, quality: Int = 45): String? {
        if (Build.VERSION.SDK_INT < 30) {
            Log.w(TAG, "takeScreenshot requires API 30+")
            return null
        }
        val latch = CountDownLatch(1)
        val result = AtomicReference<String?>(null)
        try {
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
                                latch.countDown()
                                return
                            }
                            val software = bitmap.copy(Bitmap.Config.ARGB_8888, false)
                            bitmap.recycle()
                            val scaled = scaleBitmap(software, maxWidth)
                            if (scaled !== software) software.recycle()
                            val baos = ByteArrayOutputStream()
                            scaled.compress(Bitmap.CompressFormat.JPEG, quality, baos)
                            scaled.recycle()
                            result.set(Base64.encodeToString(baos.toByteArray(), Base64.NO_WRAP))
                        } catch (e: Exception) {
                            Log.e(TAG, "screenshot encode failed", e)
                        } finally {
                            latch.countDown()
                        }
                    }

                    override fun onFailure(errorCode: Int) {
                        Log.w(TAG, "takeScreenshot failed code=$errorCode")
                        latch.countDown()
                    }
                },
            )
        } catch (e: Exception) {
            Log.e(TAG, "takeScreenshot threw", e)
            return null
        }
        latch.await(6, TimeUnit.SECONDS)
        return result.get()
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

    fun inputText(
        text: String,
        clear: Boolean = false,
        humanize: Boolean = true,
    ): Boolean {
        val root = rootInActiveWindow ?: return false
        var target = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
        if (target == null || !target.isEditable) {
            target = findEditable(root)
        }
        val edit = target
        if (edit == null) {
            try {
                root.recycle()
            } catch (_: Exception) {
            }
            return false
        }
        fun setText(value: String): Boolean {
            val args = android.os.Bundle()
            args.putCharSequence(
                AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
                value,
            )
            return edit.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
        }
        if (clear) {
            setText("")
        }
        val existing = if (clear) "" else (edit.text?.toString() ?: "")
        // Human-like: type in small chunks with variance — not one instant paste
        val ok = if (!humanize || text.length <= 2) {
            setText(existing + text)
        } else {
            val rng = java.util.concurrent.ThreadLocalRandom.current()
            var built = existing
            var i = 0
            var success = true
            while (i < text.length) {
                val chunk = rng.nextInt(2, 5).coerceAtMost(text.length - i)
                built += text.substring(i, i + chunk)
                if (!setText(built)) {
                    success = false
                    break
                }
                i += chunk
                if (i < text.length) {
                    // ~30–110ms between chunks; occasional brief pause
                    val pause = if (rng.nextDouble() < 0.12) {
                        rng.nextLong(120, 280)
                    } else {
                        rng.nextLong(30, 110)
                    }
                    try {
                        Thread.sleep(pause)
                    } catch (_: InterruptedException) {
                    }
                }
            }
            success
        }
        try {
            edit.recycle()
        } catch (_: Exception) {
        }
        try {
            root.recycle()
        } catch (_: Exception) {
        }
        return ok
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
}
