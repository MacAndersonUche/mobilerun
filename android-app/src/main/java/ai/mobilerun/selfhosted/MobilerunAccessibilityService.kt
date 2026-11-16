package ai.mobilerun.selfhosted

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Context
import android.graphics.Path
import android.graphics.PixelFormat
import android.os.Build
import android.util.Log
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

class MobilerunAccessibilityService : AccessibilityService() {
    
    companion object {
        private const val TAG = "MobilerunA11y"
        @Volatile
        var instance: MobilerunAccessibilityService? = null
    }
    
    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        Log.d(TAG, "Accessibility service connected")
    }
    
    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        // Handle accessibility events if needed
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
        val path = Path().apply {
            moveTo(x.toFloat(), y.toFloat())
        }
        
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, 50))
            .build()
        
        dispatchGesture(gesture, object : GestureResultCallback() {
            override fun onCompleted(gestureDescription: GestureDescription?) {
                callback(true)
            }
            
            override fun onCancelled(gestureDescription: GestureDescription?) {
                callback(false)
            }
        }, null)
    }
    
    fun swipe(x1: Int, y1: Int, x2: Int, y2: Int, durationMs: Long, callback: (Boolean) -> Unit) {
        val path = Path().apply {
            moveTo(x1.toFloat(), y1.toFloat())
            lineTo(x2.toFloat(), y2.toFloat())
        }
        
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, durationMs))
            .build()
        
        dispatchGesture(gesture, object : GestureResultCallback() {
            override fun onCompleted(gestureDescription: GestureDescription?) {
                callback(true)
            }
            
            override fun onCancelled(gestureDescription: GestureDescription?) {
                callback(false)
            }
        }, null)
    }
    
    fun pressBack(): Boolean {
        return performGlobalAction(GLOBAL_ACTION_BACK)
    }
    
    fun pressHome(): Boolean {
        return performGlobalAction(GLOBAL_ACTION_HOME)
    }
    
    fun pressRecents(): Boolean {
        return performGlobalAction(GLOBAL_ACTION_RECENTS)
    }
    
    fun getUITree(): String {
        val rootNode = rootInActiveWindow ?: return ""
        return buildUITreeXml(rootNode)
    }
    
    private fun buildUITreeXml(node: AccessibilityNodeInfo?, indent: String = ""): String {
        if (node == null) return ""
        
        val sb = StringBuilder()
        val className = node.className?.toString() ?: "unknown"
        val text = node.text?.toString() ?: ""
        val contentDesc = node.contentDescription?.toString() ?: ""
        val bounds = android.graphics.Rect()
        node.getBoundsInScreen(bounds)
        
        sb.append(indent).append("<node ")
        sb.append("class=\"$className\" ")
        if (text.isNotEmpty()) sb.append("text=\"$text\" ")
        if (contentDesc.isNotEmpty()) sb.append("content-desc=\"$contentDesc\" ")
        sb.append("bounds=\"[${bounds.left},${bounds.top}][${bounds.right},${bounds.bottom}]\" ")
        sb.append("clickable=\"${node.isClickable}\" ")
        sb.append("focusable=\"${node.isFocusable}\"")
        
        if (node.childCount == 0) {
            sb.append(" />\n")
        } else {
            sb.append(">\n")
            for (i in 0 until node.childCount) {
                val child = node.getChild(i)
                sb.append(buildUITreeXml(child, indent + "  "))
                child?.recycle()
            }
            sb.append(indent).append("</node>\n")
        }
        
        return sb.toString()
    }
    
    suspend fun tapAsync(x: Int, y: Int): Boolean = suspendCancellableCoroutine { cont ->
        tap(x, y) { success ->
            if (cont.isActive) {
                cont.resume(success)
            }
        }
    }
    
    suspend fun swipeAsync(x1: Int, y1: Int, x2: Int, y2: Int, durationMs: Long): Boolean =
        suspendCancellableCoroutine { cont ->
            swipe(x1, y1, x2, y2, durationMs) { success ->
                if (cont.isActive) {
                    cont.resume(success)
                }
            }
        }
}
