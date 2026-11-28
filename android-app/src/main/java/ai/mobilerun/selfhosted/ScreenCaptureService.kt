package ai.mobilerun.selfhosted

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.util.Base64
import android.util.DisplayMetrics
import android.util.Log
import android.view.WindowManager
import androidx.core.app.NotificationCompat
import java.io.ByteArrayOutputStream
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

/**
 * MediaProjection-based screen capture for live UI streaming.
 * Encodes JPEG frames (~2–5 fps, adjustable quality) and posts them to [frameListener].
 */
class ScreenCaptureService : Service() {
    companion object {
        const val ACTION_START = "ai.mobilerun.selfhosted.CAPTURE_START"
        const val ACTION_STOP = "ai.mobilerun.selfhosted.CAPTURE_STOP"
        const val EXTRA_RESULT_CODE = "result_code"
        const val EXTRA_RESULT_DATA = "result_data"
        const val EXTRA_FPS = "fps"
        const val EXTRA_QUALITY = "quality"
        const val EXTRA_MAX_WIDTH = "max_width"

        private const val TAG = "ScreenCapture"
        private const val CHANNEL_ID = "mobilerun_capture"
        private const val NOTIF_ID = 42

        @Volatile
        var instance: ScreenCaptureService? = null
            private set

        @Volatile
        var frameListener: ((FramePayload) -> Unit)? = null

        data class FramePayload(
            val mime: String,
            val width: Int,
            val height: Int,
            val seq: Int,
            val ts: Long,
            val dataBase64: String,
        )

        /** True when MediaProjection virtual display is actively emitting frames. */
        fun isStreaming(): Boolean = instance?.streaming?.get() == true

        @Volatile
        private var lastFrameJpegB64: String? = null

        /** Latest live-view JPEG for agent screenshot fallback (no new consent). */
        fun lastJpegBase64(): String? = lastFrameJpegB64

        internal fun rememberFrame(b64: String) {
            lastFrameJpegB64 = b64
        }

        /** Adjust fps/quality without re-prompting MediaProjection consent. */
        fun updateParams(fps: Int, quality: Int) {
            instance?.let {
                it.fps = fps.coerceIn(1, 8)
                it.quality = quality.coerceIn(20, 85)
                Log.i(TAG, "capture params updated fps=${it.fps} q=${it.quality}")
            }
        }
    }

    private var mediaProjection: MediaProjection? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var imageReader: ImageReader? = null
    private var handlerThread: HandlerThread? = null
    private var handler: Handler? = null
    private val streaming = AtomicBoolean(false)
    private val seq = AtomicInteger(0)
    private var fps: Int = 3
    private var quality: Int = 45
    private var maxWidth: Int = 540
    private var lastEmitMs: Long = 0L

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        instance = this
        createChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> {
                val code = intent.getIntExtra(EXTRA_RESULT_CODE, 0)
                @Suppress("DEPRECATION")
                val data = intent.getParcelableExtra<Intent>(EXTRA_RESULT_DATA)
                fps = intent.getIntExtra(EXTRA_FPS, 3).coerceIn(1, 8)
                quality = intent.getIntExtra(EXTRA_QUALITY, 45).coerceIn(20, 85)
                maxWidth = intent.getIntExtra(EXTRA_MAX_WIDTH, 540).coerceIn(240, 1080)
                if (data != null) {
                    startForegroundCapture(code, data)
                }
            }
            ACTION_STOP -> stopCapture()
        }
        return START_STICKY
    }

    private fun startForegroundCapture(resultCode: Int, data: Intent) {
        val notification = buildNotification()
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(
                NOTIF_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION,
            )
        } else {
            startForeground(NOTIF_ID, notification)
        }

        val mgr = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        mediaProjection?.stop()
        mediaProjection = mgr.getMediaProjection(resultCode, data)
        mediaProjection?.registerCallback(object : MediaProjection.Callback() {
            override fun onStop() {
                stopCapture()
            }
        }, null)

        val metrics = DisplayMetrics()
        @Suppress("DEPRECATION")
        (getSystemService(Context.WINDOW_SERVICE) as WindowManager).defaultDisplay.getRealMetrics(metrics)
        val fullW = metrics.widthPixels
        val fullH = metrics.heightPixels
        val scale = maxWidth.toFloat() / fullW.toFloat()
        val w = maxWidth
        val h = (fullH * scale).toInt().coerceAtLeast(1)
        val density = metrics.densityDpi

        handlerThread = HandlerThread("mobilerun-capture").also { it.start() }
        handler = Handler(handlerThread!!.looper)

        imageReader = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 2)
        imageReader!!.setOnImageAvailableListener({ reader ->
            if (!streaming.get()) return@setOnImageAvailableListener
            val now = System.currentTimeMillis()
            val minGap = 1000L / fps
            if (now - lastEmitMs < minGap) {
                reader.acquireLatestImage()?.close()
                return@setOnImageAvailableListener
            }
            lastEmitMs = now
            val image = reader.acquireLatestImage() ?: return@setOnImageAvailableListener
            try {
                val plane = image.planes[0]
                val buffer = plane.buffer
                val pixelStride = plane.pixelStride
                val rowStride = plane.rowStride
                val rowPadding = rowStride - pixelStride * w
                val bitmap = Bitmap.createBitmap(
                    w + rowPadding / pixelStride,
                    h,
                    Bitmap.Config.ARGB_8888,
                )
                bitmap.copyPixelsFromBuffer(buffer)
                val cropped = Bitmap.createBitmap(bitmap, 0, 0, w, h)
                if (cropped !== bitmap) bitmap.recycle()
                val baos = ByteArrayOutputStream()
                cropped.compress(Bitmap.CompressFormat.JPEG, quality, baos)
                cropped.recycle()
                val bytes = baos.toByteArray()
                val b64 = Base64.encodeToString(bytes, Base64.NO_WRAP)
                rememberFrame(b64)
                frameListener?.invoke(
                    FramePayload(
                        mime = "image/jpeg",
                        width = w,
                        height = h,
                        seq = seq.incrementAndGet(),
                        ts = now,
                        dataBase64 = b64,
                    ),
                )
            } catch (e: Exception) {
                Log.e(TAG, "frame encode failed", e)
            } finally {
                image.close()
            }
        }, handler)

        virtualDisplay = mediaProjection?.createVirtualDisplay(
            "mobilerun",
            w,
            h,
            density,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            imageReader!!.surface,
            null,
            handler,
        )
        streaming.set(true)
        Log.i(TAG, "capture started ${w}x$h @ ${fps}fps q=$quality")
    }

    private fun stopCapture() {
        streaming.set(false)
        virtualDisplay?.release()
        virtualDisplay = null
        imageReader?.close()
        imageReader = null
        mediaProjection?.stop()
        mediaProjection = null
        handlerThread?.quitSafely()
        handlerThread = null
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
        Log.i(TAG, "capture stopped")
    }

    override fun onDestroy() {
        stopCapture()
        instance = null
        super.onDestroy()
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Screen streaming",
                NotificationManager.IMPORTANCE_LOW,
            )
            val nm = getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(channel)
        }
    }

    private fun buildNotification(): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("PhonePilot live view")
            .setContentText("Streaming screen to control UI")
            .setSmallIcon(R.drawable.ic_stat_mobilerun)
            .setOngoing(true)
            .build()
    }
}
