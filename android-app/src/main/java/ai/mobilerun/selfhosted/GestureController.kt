package ai.mobilerun.selfhosted

import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.util.Log

/**
 * Portal-compatible gesture helpers: dispatch tap/swipe and return immediately
 * based on whether [AccessibilityService.dispatchGesture] accepted the gesture.
 * (Original Mobilerun Portal GestureController — 50ms sync tap, no callback wait.)
 */
object GestureController {
    private const val TAG = "GestureController"
    private const val TAP_DURATION_MS = 50L
    private const val DEFAULT_SWIPE_DURATION_MS = 300
    private const val MIN_SWIPE_DURATION_MS = 10
    private const val MAX_SWIPE_DURATION_MS = 5000

    fun tap(x: Int, y: Int, humanize: Boolean = false): Boolean {
        val service = MobilerunAccessibilityService.instance ?: return false
        return try {
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
            val pressMs = if (humanize) {
                java.util.concurrent.ThreadLocalRandom.current().nextLong(45, 85)
            } else {
                TAP_DURATION_MS
            }
            val path = Path().apply { moveTo(jx.toFloat(), jy.toFloat()) }
            val stroke = GestureDescription.StrokeDescription(path, 0, pressMs)
            val gesture = GestureDescription.Builder().addStroke(stroke).build()
            val result = service.dispatchGesture(gesture, null, null)
            Log.d(TAG, "Tap at ($jx, $jy) dispatched: $result")
            result
        } catch (e: Exception) {
            Log.e(TAG, "Tap error", e)
            false
        }
    }

    fun swipe(
        startX: Int,
        startY: Int,
        endX: Int,
        endY: Int,
        durationMs: Int = DEFAULT_SWIPE_DURATION_MS,
    ): Boolean {
        val service = MobilerunAccessibilityService.instance ?: return false
        return try {
            val path = Path().apply {
                moveTo(startX.toFloat(), startY.toFloat())
                lineTo(endX.toFloat(), endY.toFloat())
            }
            val dur = durationMs.coerceIn(MIN_SWIPE_DURATION_MS, MAX_SWIPE_DURATION_MS)
            val stroke = GestureDescription.StrokeDescription(path, 0, dur.toLong())
            val gesture = GestureDescription.Builder().addStroke(stroke).build()
            val result = service.dispatchGesture(gesture, null, null)
            Log.d(TAG, "Swipe ($startX,$startY)->($endX,$endY) dispatched: $result")
            result
        } catch (e: Exception) {
            Log.e(TAG, "Swipe error", e)
            false
        }
    }
}
