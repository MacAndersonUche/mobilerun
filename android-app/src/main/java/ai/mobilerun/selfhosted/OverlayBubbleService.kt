package ai.mobilerun.selfhosted

import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.IBinder
import android.provider.Settings
import android.util.Log
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.FrameLayout
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * Small TYPE_APPLICATION_OVERLAY bubble shown only while the executor is Connected.
 * Tap → bring [MainActivity] to the front.
 */
class OverlayBubbleService : Service() {
    companion object {
        const val ACTION_START = "ai.mobilerun.selfhosted.OVERLAY_START"
        const val ACTION_STOP = "ai.mobilerun.selfhosted.OVERLAY_STOP"
        private const val TAG = "OverlayBubble"

        fun isConnectedStatus(status: String): Boolean =
            status.contains("connected", ignoreCase = true)

        /** Start when Connected + overlay permission; stop otherwise. */
        fun sync(context: Context, status: String) {
            val app = context.applicationContext
            if (isConnectedStatus(status) && Settings.canDrawOverlays(app)) {
                start(app)
            } else {
                stop(app)
            }
        }

        fun start(context: Context) {
            if (!Settings.canDrawOverlays(context)) {
                Log.d(TAG, "start skipped — no overlay permission")
                return
            }
            val intent = Intent(context, OverlayBubbleService::class.java).setAction(ACTION_START)
            try {
                context.startService(intent)
            } catch (e: Exception) {
                Log.w(TAG, "start failed: ${e.message}")
            }
        }

        fun stop(context: Context) {
            try {
                context.startService(
                    Intent(context, OverlayBubbleService::class.java).setAction(ACTION_STOP),
                )
            } catch (_: Exception) {
                try {
                    context.stopService(Intent(context, OverlayBubbleService::class.java))
                } catch (_: Exception) {
                }
            }
        }
    }

    private var windowManager: WindowManager? = null
    private var bubbleView: View? = null
    private var layoutParams: WindowManager.LayoutParams? = null
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var statusJob: Job? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                removeBubble()
                stopSelf()
                return START_NOT_STICKY
            }
            else -> {
                if (!Settings.canDrawOverlays(this)) {
                    stopSelf()
                    return START_NOT_STICKY
                }
                val status = MobilerunApp.client()?.statusFlow?.value.orEmpty()
                if (!isConnectedStatus(status)) {
                    removeBubble()
                    stopSelf()
                    return START_NOT_STICKY
                }
                showBubble()
                observeStatus()
            }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        statusJob?.cancel()
        scope.cancel()
        removeBubble()
        super.onDestroy()
    }

    private fun observeStatus() {
        if (statusJob?.isActive == true) return
        val client = MobilerunApp.client() ?: return
        statusJob = scope.launch {
            client.statusFlow.collect { status ->
                if (!isConnectedStatus(status)) {
                    removeBubble()
                    stopSelf()
                } else if (Settings.canDrawOverlays(this@OverlayBubbleService)) {
                    showBubble()
                } else {
                    removeBubble()
                    stopSelf()
                }
            }
        }
    }

    private fun showBubble() {
        if (bubbleView != null) return
        if (!Settings.canDrawOverlays(this)) return

        val wm = getSystemService(WINDOW_SERVICE) as WindowManager
        windowManager = wm

        val sizePx = TypedValue.applyDimension(
            TypedValue.COMPLEX_UNIT_DIP,
            56f,
            resources.displayMetrics,
        ).toInt()

        val circle = GradientDrawable().apply {
            shape = GradientDrawable.OVAL
            setColor(0xFF3B82F6.toInt())
        }

        val view = FrameLayout(this).apply {
            background = circle
            contentDescription = getString(R.string.app_name)
            isClickable = true
            isFocusable = true
            elevation = TypedValue.applyDimension(
                TypedValue.COMPLEX_UNIT_DIP,
                6f,
                resources.displayMetrics,
            )
        }

        val params = WindowManager.LayoutParams(
            sizePx,
            sizePx,
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            } else {
                @Suppress("DEPRECATION")
                WindowManager.LayoutParams.TYPE_PHONE
            },
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.END
            x = TypedValue.applyDimension(
                TypedValue.COMPLEX_UNIT_DIP,
                12f,
                resources.displayMetrics,
            ).toInt()
            y = TypedValue.applyDimension(
                TypedValue.COMPLEX_UNIT_DIP,
                120f,
                resources.displayMetrics,
            ).toInt()
        }

        var downX = 0f
        var downY = 0f
        var startX = 0
        var startY = 0
        var moved = false
        view.setOnTouchListener { _, event ->
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    downX = event.rawX
                    downY = event.rawY
                    startX = params.x
                    startY = params.y
                    moved = false
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = (event.rawX - downX).toInt()
                    val dy = (event.rawY - downY).toInt()
                    if (kotlin.math.abs(dx) > 8 || kotlin.math.abs(dy) > 8) moved = true
                    // gravity END → x increases toward the left
                    params.x = (startX - dx).coerceAtLeast(0)
                    params.y = (startY + dy).coerceAtLeast(0)
                    try {
                        wm.updateViewLayout(view, params)
                    } catch (_: Exception) {
                    }
                    true
                }
                MotionEvent.ACTION_UP -> {
                    if (!moved) openMainActivity()
                    true
                }
                else -> false
            }
        }

        try {
            wm.addView(view, params)
            bubbleView = view
            layoutParams = params
            Log.i(TAG, "overlay bubble shown")
        } catch (e: Exception) {
            Log.w(TAG, "addView failed: ${e.message}")
            bubbleView = null
            layoutParams = null
        }
    }

    private fun removeBubble() {
        val view = bubbleView ?: return
        try {
            windowManager?.removeView(view)
        } catch (_: Exception) {
        }
        bubbleView = null
        layoutParams = null
        windowManager = null
        Log.i(TAG, "overlay bubble removed")
    }

    private fun openMainActivity() {
        val open = Intent(this, MainActivity::class.java).apply {
            addFlags(
                Intent.FLAG_ACTIVITY_NEW_TASK or
                    Intent.FLAG_ACTIVITY_SINGLE_TOP or
                    Intent.FLAG_ACTIVITY_REORDER_TO_FRONT,
            )
        }
        try {
            startActivity(open)
        } catch (e: Exception) {
            Log.w(TAG, "open MainActivity: ${e.message}")
        }
    }
}
