package ai.mobilerun.selfhosted

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.wifi.WifiManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat

/**
 * Sticky foreground service so the APK keeps the WebSocket alive in the background.
 * Holds a partial wake lock + wifi lock while running so Samsung Doze does not
 * freeze the socket mid-task.
 */
class ConnectionService : Service() {
    companion object {
        const val ACTION_START = "ai.mobilerun.selfhosted.CONN_START"
        const val ACTION_STOP = "ai.mobilerun.selfhosted.CONN_STOP"
        private const val CHANNEL_ID = "mobilerun_connection"
        private const val NOTIF_ID = 41

        fun start(context: Context) {
            val intent = Intent(context, ConnectionService::class.java).setAction(ACTION_START)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            context.startService(
                Intent(context, ConnectionService::class.java).setAction(ACTION_STOP),
            )
        }
    }

    private var wakeLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                releaseLocks()
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                return START_NOT_STICKY
            }
            else -> {
                createChannel()
                val notification = buildNotification()
                if (Build.VERSION.SDK_INT >= 34) {
                    startForeground(
                        NOTIF_ID,
                        notification,
                        ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,
                    )
                } else if (Build.VERSION.SDK_INT >= 29) {
                    startForeground(NOTIF_ID, notification)
                } else {
                    startForeground(NOTIF_ID, notification)
                }
                acquireLocks()
            }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        releaseLocks()
        super.onDestroy()
    }

    private fun acquireLocks() {
        try {
            if (wakeLock?.isHeld != true) {
                val pm = getSystemService(PowerManager::class.java)
                wakeLock = pm.newWakeLock(
                    PowerManager.PARTIAL_WAKE_LOCK,
                    "mobilerun:connection",
                ).also {
                    it.setReferenceCounted(false)
                    it.acquire(6 * 60 * 60 * 1000L) // 6h max; refreshed while service runs
                }
            }
        } catch (_: Exception) {
        }
        try {
            if (wifiLock?.isHeld != true) {
                @Suppress("DEPRECATION")
                val wm = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
                @Suppress("DEPRECATION")
                wifiLock = wm.createWifiLock(
                    WifiManager.WIFI_MODE_FULL_HIGH_PERF,
                    "mobilerun:wifi",
                ).also {
                    it.setReferenceCounted(false)
                    it.acquire()
                }
            }
        } catch (_: Exception) {
        }
    }

    private fun releaseLocks() {
        try {
            if (wakeLock?.isHeld == true) wakeLock?.release()
        } catch (_: Exception) {
        }
        wakeLock = null
        try {
            if (wifiLock?.isHeld == true) wifiLock?.release()
        } catch (_: Exception) {
        }
        wifiLock = null
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT < 26) return
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ID,
                "MobileRun connection",
                NotificationManager.IMPORTANCE_LOW,
            ),
        )
    }

    private fun buildNotification(): Notification {
        val open = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("MobileRun connected")
            .setContentText("Keeping the wireless executor online")
            .setSmallIcon(R.drawable.ic_stat_mobilerun)
            .setContentIntent(open)
            .setOngoing(true)
            .build()
    }
}
