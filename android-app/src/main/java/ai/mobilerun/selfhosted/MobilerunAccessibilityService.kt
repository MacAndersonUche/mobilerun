package ai.mobilerun.selfhosted

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.AccessibilityServiceInfo
import android.accessibilityservice.GestureDescription
import android.graphics.Bitmap
import android.graphics.Path
import android.os.Build
import android.os.Handler
import android.os.Looper
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
import java.util.concurrent.atomic.AtomicReference
import kotlin.coroutines.resume

class MobilerunAccessibilityService : AccessibilityService() {

    companion object {
        private const val TAG = "MobilerunA11y"
        // Keep dumps small enough for API Gateway WS (~128KB) after JSON wrap
        private const val MAX_NODES = 220
        private const val MAX_DEPTH = 22
        private const val MAX_TREE_CHARS = 55_000
        private const val DUMP_TIMEOUT_MS = 8_000L

        @Volatile
        var instance: MobilerunAccessibilityService? = null
    }

    private val mainHandler = Handler(Looper.getMainLooper())
    private val screenshotExecutor = Executors.newSingleThreadExecutor()

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        // Reinforce flags for Samsung One UI / multi-window
        serviceInfo = serviceInfo?.apply {
            flags = flags or
                AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS or
                AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS or
                AccessibilityServiceInfo.FLAG_INCLUDE_NOT_IMPORTANT_VIEWS
            eventTypes = AccessibilityEvent.TYPES_ALL_MASK
            feedbackType = AccessibilityServiceInfo.FEEDBACK_GENERIC
        } ?: serviceInfo
        Log.d(TAG, "Accessibility service connected flags=${serviceInfo?.flags}")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        // Intentional no-op — we pull trees on demand
    }

    override fun onInterrupt() {
        Log.d(TAG, "Service interrupted")
    }

    override fun onDestroy() {
        instance = null
        super.onDestroy()
    }

    // === Device Control Methods ===

    fun tap(x: Int, y: Int, callback: (Boolean) -> Unit) {
        val path = Path().apply { moveTo(x.toFloat(), y.toFloat()) }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, 50))
            .build()
        dispatchGesture(
            gesture,
            object : GestureResultCallback() {
                override fun onCompleted(gestureDescription: GestureDescription?) = callback(true)
                override fun onCancelled(gestureDescription: GestureDescription?) = callback(false)
            },
            null,
        )
    }

    fun swipe(x1: Int, y1: Int, x2: Int, y2: Int, durationMs: Long, callback: (Boolean) -> Unit) {
        val path = Path().apply {
            moveTo(x1.toFloat(), y1.toFloat())
            lineTo(x2.toFloat(), y2.toFloat())
        }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, durationMs))
            .build()
        dispatchGesture(
            gesture,
            object : GestureResultCallback() {
                override fun onCompleted(gestureDescription: GestureDescription?) = callback(true)
                override fun onCancelled(gestureDescription: GestureDescription?) = callback(false)
            },
            null,
        )
    }

    fun pressBack(): Boolean = performGlobalAction(GLOBAL_ACTION_BACK)

    fun pressHome(): Boolean = performGlobalAction(GLOBAL_ACTION_HOME)

    fun pressRecents(): Boolean = performGlobalAction(GLOBAL_ACTION_RECENTS)

    /** Active window package if available (for verify-after-action). */
    fun activePackageName(): String? {
        rootInActiveWindow?.packageName?.toString()?.let { return it }
        windows?.firstOrNull { it.type == AccessibilityWindowInfo.TYPE_APPLICATION }
            ?.root?.packageName?.toString()?.let { return it }
        return null
    }

    /**
     * Dump UI across interactive windows (Samsung One UI often leaves
     * [rootInActiveWindow] empty/stale for the launcher or overlays).
     * Runs on the main thread with a hard timeout — OEM a11y walks off the
     * main thread hang for 15s+ and trip cloud RPC timeouts.
     */
    fun getUITree(): String {
        if (Looper.myLooper() == Looper.getMainLooper()) {
            return dumpUITreeOnMain()
        }
        val latch = CountDownLatch(1)
        val result = AtomicReference<String?>(null)
        val err = AtomicReference<Exception?>(null)
        mainHandler.post {
            try {
                result.set(dumpUITreeOnMain())
            } catch (e: Exception) {
                err.set(e)
            } finally {
                latch.countDown()
            }
        }
        val ok = latch.await(DUMP_TIMEOUT_MS, TimeUnit.MILLISECONDS)
        if (!ok) {
            Log.w(TAG, "getUITree main-thread dump timed out after ${DUMP_TIMEOUT_MS}ms")
            return """<hierarchy windows="0" nodes="0" empty="true" reason="dump_timeout"/>"""
        }
        err.get()?.let {
            Log.w(TAG, "getUITree failed: ${it.message}")
            return """<hierarchy windows="0" nodes="0" empty="true" reason="dump_error"/>"""
        }
        return result.get()
            ?: """<hierarchy windows="0" nodes="0" empty="true" reason="dump_null"/>"""
    }

    private fun dumpUITreeOnMain(): String {
        val sb = StringBuilder()
        val counter = intArrayOf(0)
        val pkgs = linkedSetOf<String>()
        var windowCount = 0

        val winList = try {
            windows?.toList()
        } catch (e: Exception) {
            Log.w(TAG, "windows() failed: ${e.message}")
            null
        }

        if (!winList.isNullOrEmpty()) {
            // Prefer application windows, then any with content
            val ordered = winList.sortedByDescending { w ->
                when (w.type) {
                    AccessibilityWindowInfo.TYPE_APPLICATION -> 3
                    AccessibilityWindowInfo.TYPE_ACCESSIBILITY_OVERLAY -> 1
                    else -> 2
                }
            }
            for (window in ordered) {
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
                sb.append("<window id=\"${window.id}\" type=\"${window.type}\" ")
                sb.append("pkg=\"${xmlEsc(pkg)}\" title=\"${xmlEsc(title)}\" ")
                sb.append("focused=\"${window.isFocused}\" active=\"${window.isActive}\">\n")
                buildUITreeXml(root, "  ", sb, counter, 0)
                sb.append("</window>\n")
                try {
                    root.recycle()
                } catch (_: Exception) {
                }
                if (counter[0] >= MAX_NODES || sb.length >= MAX_TREE_CHARS) break
            }
        }

        // Always also try active root (some OEMs only populate this)
        val active = rootInActiveWindow
        if (active != null && windowCount == 0) {
            windowCount = 1
            val pkg = active.packageName?.toString().orEmpty()
            if (pkg.isNotEmpty()) pkgs.add(pkg)
            sb.append("<window id=\"active\" type=\"active\" pkg=\"${xmlEsc(pkg)}\">\n")
            buildUITreeXml(active, "  ", sb, counter, 0)
            sb.append("</window>\n")
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
            Log.w(TAG, "getUITree empty windows=$windowCount rootNull=${rootInActiveWindow == null}")
            return "<hierarchy windows=\"0\" nodes=\"0\" empty=\"true\"/>"
        }
        val truncated = body.length >= MAX_TREE_CHARS || counter[0] >= MAX_NODES
        val clipped = if (body.length > MAX_TREE_CHARS) {
            body.take(MAX_TREE_CHARS) + "\n<!-- truncated -->\n"
        } else {
            body
        }
        return buildString {
            append("<hierarchy windows=\"$windowCount\" nodes=\"${counter[0]}\" ")
            append("truncated=\"$truncated\" ")
            append("packages=\"${xmlEsc(pkgs.joinToString(","))}\">\n")
            append(clipped)
            append("</hierarchy>")
        }
    }

    private fun buildUITreeXml(
        node: AccessibilityNodeInfo?,
        indent: String,
        sb: StringBuilder,
        counter: IntArray,
        depth: Int,
    ) {
        if (node == null || counter[0] >= MAX_NODES || depth > MAX_DEPTH) return
        if (sb.length >= MAX_TREE_CHARS) return
        counter[0]++

        val className = node.className?.toString() ?: "unknown"
        val text = node.text?.toString().orEmpty()
        val contentDesc = node.contentDescription?.toString().orEmpty()
        val viewId = node.viewIdResourceName.orEmpty()
        val pkg = node.packageName?.toString().orEmpty()
        val bounds = android.graphics.Rect()
        node.getBoundsInScreen(bounds)
        val cx = (bounds.left + bounds.right) / 2
        val cy = (bounds.top + bounds.bottom) / 2
        val interactive = node.isClickable || node.isEditable || node.isCheckable ||
            node.isScrollable || text.isNotEmpty() || contentDesc.isNotEmpty() ||
            viewId.isNotEmpty()
        // Skip inert layout wrappers once we are near the budget
        if (!interactive && depth > 4 && counter[0] > MAX_NODES / 2) {
            val childCountSkip = node.childCount
            for (i in 0 until childCountSkip) {
                if (counter[0] >= MAX_NODES || sb.length >= MAX_TREE_CHARS) break
                val child = try {
                    node.getChild(i)
                } catch (_: Exception) {
                    null
                }
                buildUITreeXml(child, indent, sb, counter, depth + 1)
                try {
                    child?.recycle()
                } catch (_: Exception) {
                }
            }
            return
        }

        sb.append(indent).append("<node ")
        sb.append("class=\"${xmlEsc(className)}\" ")
        if (pkg.isNotEmpty()) sb.append("package=\"${xmlEsc(pkg)}\" ")
        if (text.isNotEmpty()) sb.append("text=\"${xmlEsc(text)}\" ")
        if (contentDesc.isNotEmpty()) sb.append("content-desc=\"${xmlEsc(contentDesc)}\" ")
        if (viewId.isNotEmpty()) sb.append("resource-id=\"${xmlEsc(viewId)}\" ")
        sb.append("bounds=\"[${bounds.left},${bounds.top}][${bounds.right},${bounds.bottom}]\" ")
        sb.append("center=\"($cx,$cy)\" ")
        sb.append("clickable=\"${node.isClickable}\" ")
        if (node.isLongClickable) sb.append("long-clickable=\"true\" ")
        if (node.isScrollable) sb.append("scrollable=\"true\" ")
        if (node.isFocusable) sb.append("focusable=\"true\" ")
        sb.append("enabled=\"${node.isEnabled}\"")
        if (node.isCheckable) {
            sb.append(" checkable=\"true\" checked=\"${node.isChecked}\"")
        }

        val childCount = node.childCount
        if (childCount == 0) {
            sb.append(" />\n")
        } else {
            sb.append(">\n")
            for (i in 0 until childCount) {
                if (counter[0] >= MAX_NODES || sb.length >= MAX_TREE_CHARS) break
                val child = try {
                    node.getChild(i)
                } catch (_: Exception) {
                    null
                }
                buildUITreeXml(child, indent + "  ", sb, counter, depth + 1)
                try {
                    child?.recycle()
                } catch (_: Exception) {
                }
            }
            sb.append(indent).append("</node>\n")
        }
    }

    private fun xmlEsc(s: String): String =
        s.replace("&", "&amp;")
            .replace("\"", "&quot;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", " ")
            .take(200)

    /**
     * Capture a JPEG screenshot via AccessibilityService (API 30+).
     * Returns base64 (no data: prefix) or null.
     */
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
        latch.await(8, TimeUnit.SECONDS)
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
        if (target == null) return false
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
        return target.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
    }

    private fun findEditable(node: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        if (node == null) return null
        if (node.isEditable) return node
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            val found = findEditable(child)
            if (found != null) return found
            child.recycle()
        }
        return null
    }
}
