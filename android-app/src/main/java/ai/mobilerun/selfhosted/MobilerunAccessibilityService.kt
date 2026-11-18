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
        // Compact dumps — target ≪ 20KB so API Gateway WS stays healthy
        private const val MAX_NODES = 140
        private const val MAX_DEPTH = 16
        private const val MAX_TREE_CHARS = 18_000
        private const val SOFT_DEADLINE_MS = 3_000L
        private const val HARD_AWAIT_MS = 3_500L
        private const val CACHE_TTL_MS = 2_500L

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

    // Dedicated dump thread — never block main or OkHttp/WS callbacks
    private val dumpThread = HandlerThread("mr-a11y-dump").also { it.start() }
    private val dumpHandler = Handler(dumpThread.looper)

    private val contentGeneration = AtomicLong(0)
    private val cacheLock = Any()
    @Volatile private var cachedGeneration: Long = -1
    @Volatile private var cachedAtMs: Long = 0
    @Volatile private var cachedResult: TreeResult? = null

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        serviceInfo = serviceInfo?.apply {
            flags = flags or
                AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS or
                AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS or
                AccessibilityServiceInfo.FLAG_INCLUDE_NOT_IMPORTANT_VIEWS
            eventTypes = AccessibilityEvent.TYPES_ALL_MASK
            feedbackType = AccessibilityServiceInfo.FEEDBACK_GENERIC
            notificationTimeout = 50
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
     * Build (or serve cached) compact UI tree off the main thread with a soft deadline.
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

        // Prefer dump thread; never run a deep walk on the caller's WS/main thread
        if (Looper.myLooper() == dumpThread.looper) {
            return dumpAndCache(gen)
        }
        val latch = CountDownLatch(1)
        val result = AtomicReference<TreeResult?>(null)
        dumpHandler.post {
            try {
                result.set(dumpAndCache(gen))
            } catch (e: Exception) {
                Log.w(TAG, "dump failed: ${e.message}")
                result.set(
                    TreeResult(
                        tree = """<hierarchy windows="0" nodes="0" empty="true" reason="dump_error"/>""",
                        packageName = "",
                        empty = true,
                        chars = 0,
                        nodes = 0,
                        partial = true,
                        cached = false,
                        buildMs = 0,
                        bytes = 0,
                        treeGzB64 = null,
                        anrDismissed = false,
                    ),
                )
            } finally {
                latch.countDown()
            }
        }
        val ok = latch.await(HARD_AWAIT_MS, TimeUnit.MILLISECONDS)
        if (!ok) {
            Log.w(TAG, "getUITreeDetailed hard await timed out after ${HARD_AWAIT_MS}ms")
            return TreeResult(
                tree = """<hierarchy windows="0" nodes="0" empty="true" reason="dump_timeout" soft="${SOFT_DEADLINE_MS}"/>""",
                packageName = "",
                empty = true,
                chars = 0,
                nodes = 0,
                partial = true,
                cached = false,
                buildMs = HARD_AWAIT_MS,
                bytes = 0,
                treeGzB64 = null,
                anrDismissed = false,
            )
        }
        return result.get() ?: TreeResult(
            tree = """<hierarchy windows="0" nodes="0" empty="true" reason="dump_null"/>""",
            packageName = "",
            empty = true,
            chars = 0,
            nodes = 0,
            partial = true,
            cached = false,
            buildMs = 0,
            bytes = 0,
            treeGzB64 = null,
            anrDismissed = false,
        )
    }

    private fun dumpAndCache(gen: Long): TreeResult {
        val t0 = SystemClock.elapsedRealtime()
        val anr = try {
            dismissSystemAnrIfPresent()
        } catch (e: Exception) {
            Log.w(TAG, "ANR dismiss failed: ${e.message}")
            false
        }
        val built = dumpUITreeCompact(deadlineMs = t0 + SOFT_DEADLINE_MS)
        val buildMs = SystemClock.elapsedRealtime() - t0
        val gz = gzipB64(built.tree)
        val result = built.copy(
            buildMs = buildMs,
            bytes = built.tree.toByteArray(Charsets.UTF_8).size,
            treeGzB64 = gz,
            anrDismissed = anr,
            cached = false,
        )
        synchronized(cacheLock) {
            cachedResult = result
            cachedGeneration = gen
            cachedAtMs = SystemClock.elapsedRealtime()
        }
        Log.i(
            TAG,
            "tree buildMs=$buildMs nodes=${result.nodes} chars=${result.chars} " +
                "bytes=${result.bytes} partial=${result.partial} gz=${gz?.length ?: 0} anr=$anr",
        )
        return result
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
                // Compact window header
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

        val active = rootInActiveWindow
        if (active != null && windowCount == 0 && !pastDeadline()) {
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
        } else if (active != null) {
            try {
                active.recycle()
            } catch (_: Exception) {
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
        val interesting = node.isClickable || node.isEditable || node.isCheckable ||
            node.isLongClickable || node.isScrollable ||
            text.isNotEmpty() || contentDesc.isNotEmpty()

        // Skip invisible / inert wrappers; still recurse into children
        val emit = visible && interesting
        if (!emit) {
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
