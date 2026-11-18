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
        // Compact dumps — target ≪ 20KB; p95 tree build < 1.5s
        private const val MAX_NODES = 90
        private const val MAX_DEPTH = 10
        private const val MAX_TREE_CHARS = 12_000
        // Soft budget for the main-looper walk itself (partial tree > empty)
        // Target p95 < 1.5s wall including gzip/scheduling
        private const val SOFT_DEADLINE_MS = 1_100L
        // Caller await: soft walk + main-looper scheduling + gzip slack
        private const val HARD_AWAIT_MS = 1_450L
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
            // Skip INCLUDE_NOT_IMPORTANT_VIEWS — halves walk cost on Messages/OEM UIs
            flags = flags or
                AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS or
                AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
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

    fun tap(x: Int, y: Int, callback: (Boolean) -> Unit) {
        val path = Path().apply { moveTo(x.toFloat(), y.toFloat()) }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, 50))
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
    fun tapFireAndForget(x: Int, y: Int) {
        tap(x, y) { /* async verify is the cloud's job */ }
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
    fun dismissSystemAnrIfPresent(): Boolean {
        val root = rootInActiveWindow ?: return false
        try {
            // Cheap package gate — full text walk only for System UI dialogs
            val pkg = root.packageName?.toString().orEmpty()
            if (pkg.isNotEmpty() &&
                "systemui" !in pkg &&
                "android" != pkg &&
                !pkg.startsWith("com.android.systemui")
            ) {
                return false
            }
            val blob = StringBuilder()
            collectTextSample(root, blob, 0, AtomicInteger(0))
            val low = blob.toString().lowercase()
            val isAnr = "isn't responding" in low ||
                "isnt responding" in low ||
                "not responding" in low ||
                ("close app" in low && "wait" in low)
            if (!isAnr) return false
            // Prefer "Wait" to keep the session alive; fall back to Close app
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
        val sb = StringBuilder(4096)
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

        // Prefer active root first — cheapest reliable source; windows() can be slow
        val active = try {
            rootInActiveWindow
        } catch (e: Exception) {
            Log.w(TAG, "rootInActiveWindow failed: ${e.message}")
            null
        }
        if (active != null && !pastDeadline()) {
            windowCount = 1
            val pkg = active.packageName?.toString().orEmpty()
            if (pkg.isNotEmpty()) pkgs.add(pkg)
            sb.append("<w id=\"active\" t=\"active\" p=\"${xmlEsc(pkg)}\">\n")
            buildCompactNodes(active, " ", sb, counter, 0, deadlineMs) { partial = true }
            sb.append("</w>\n")
            try {
                active.recycle()
            } catch (_: Exception) {
            }
        }

        // Skip windows() enrichment by default — active root is enough for
        // messaging flows and windows() binder cost dominates p95 on OEM/emu.
        // Only scan other windows when the active dump was empty and budget remains.
        if (counter[0] == 0 && !pastDeadline()) {
            val winList = try {
                windows?.toList()
            } catch (e: Exception) {
                Log.w(TAG, "windows() failed: ${e.message}")
                null
            }
            if (!winList.isNullOrEmpty()) {
                val ordered = winList.sortedByDescending { w ->
                    when (w.type) {
                        AccessibilityWindowInfo.TYPE_APPLICATION -> 3
                        AccessibilityWindowInfo.TYPE_SYSTEM -> 2
                        else -> 1
                    }
                }
                for (window in ordered) {
                    if (pastDeadline() || counter[0] >= MAX_NODES || sb.length >= MAX_TREE_CHARS) break
                    if (window.isActive && windowCount > 0) continue
                    val root = try {
                        window.root
                    } catch (_: Exception) {
                        null
                    } ?: continue
                    windowCount++
                    val pkg = root.packageName?.toString().orEmpty()
                    if (pkg.isNotEmpty()) pkgs.add(pkg)
                    val title = try {
                        window.title?.toString().orEmpty()
                    } catch (_: Exception) {
                        ""
                    }
                    sb.append("<w id=\"${window.id}\" t=\"${window.type}\" ")
                    sb.append("p=\"${xmlEsc(pkg)}\" ")
                    if (title.isNotEmpty()) sb.append("title=\"${xmlEsc(title)}\" ")
                    sb.append("f=\"${if (window.isFocused) 1 else 0}\">\n")
                    buildCompactNodes(root, " ", sb, counter, 0, deadlineMs) { partial = true }
                    sb.append("</w>\n")
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
        val tree = buildString {
            append("<hierarchy windows=\"$windowCount\" nodes=\"${counter[0]}\" ")
            append("partial=\"$truncated\" ")
            append("packages=\"${xmlEsc(pkgs.joinToString(","))}\">\n")
            append(clipped)
            append("</hierarchy>")
        }
        return TreeResult(
            tree = tree,
            packageName = primaryPkg,
            empty = false,
            chars = tree.length,
            nodes = counter[0],
            partial = truncated,
            cached = false,
            buildMs = 0,
            bytes = tree.toByteArray(Charsets.UTF_8).size,
            treeGzB64 = null,
            anrDismissed = false,
        )
    }

    /**
     * Emit only visible interactive / text-bearing nodes with short keys:
     * t=text, d=desc, i=id, c=clickable, e=editable, xy=center, b=bounds
     */
    private fun buildCompactNodes(
        node: AccessibilityNodeInfo?,
        indent: String,
        sb: StringBuilder,
        counter: IntArray,
        depth: Int,
        deadlineMs: Long,
        markPartial: () -> Unit,
    ) {
        if (node == null || counter[0] >= MAX_NODES || depth > MAX_DEPTH) return
        if (sb.length >= MAX_TREE_CHARS) return
        if (SystemClock.elapsedRealtime() >= deadlineMs) {
            markPartial()
            return
        }

        val text = node.text?.toString().orEmpty().take(80)
        val contentDesc = node.contentDescription?.toString().orEmpty().take(60)
        val viewId = node.viewIdResourceName.orEmpty().let { id ->
            // short id: last segment only
            if (id.contains('/')) id.substringAfterLast('/') else id.takeLast(40)
        }
        val visible = try {
            node.isVisibleToUser
        } catch (_: Exception) {
            true
        }
        // Invisible subtrees are skipped entirely — biggest win for p95
        if (!visible) return

        val interesting = node.isClickable || node.isEditable || node.isCheckable ||
            node.isLongClickable || node.isScrollable ||
            text.isNotEmpty() || contentDesc.isNotEmpty()

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
                buildCompactNodes(child, indent, sb, counter, depth + 1, deadlineMs, markPartial)
                try {
                    child?.recycle()
                } catch (_: Exception) {
                }
            }
            return
        }

        counter[0]++
        val bounds = android.graphics.Rect()
        node.getBoundsInScreen(bounds)
        val cx = (bounds.left + bounds.right) / 2
        val cy = (bounds.top + bounds.bottom) / 2

        sb.append(indent).append("<n")
        if (text.isNotEmpty()) sb.append(" t=\"${xmlEsc(text)}\"")
        if (contentDesc.isNotEmpty()) sb.append(" d=\"${xmlEsc(contentDesc)}\"")
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
            buildCompactNodes(child, indent, sb, counter, depth + 1, deadlineMs, markPartial)
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

    fun inputText(text: String, clear: Boolean = false): Boolean {
        val root = rootInActiveWindow ?: return false
        var target = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
        if (target == null || !target.isEditable) {
            target = findEditable(root)
        }
        if (target == null) {
            try {
                root.recycle()
            } catch (_: Exception) {
            }
            return false
        }
        if (clear) {
            val args = android.os.Bundle()
            args.putCharSequence(
                AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
                "",
            )
            target.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
        }
        val args = android.os.Bundle()
        val existing = if (clear) "" else (target.text?.toString() ?: "")
        args.putCharSequence(
            AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
            existing + text,
        )
        val ok = target.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
        try {
            target.recycle()
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
