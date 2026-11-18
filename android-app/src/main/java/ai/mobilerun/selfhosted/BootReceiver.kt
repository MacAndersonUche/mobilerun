package ai.mobilerun.selfhosted

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.util.Log

/**
 * Restart the sticky connection foreground service after reboot / package replace,
 * and best-effort rebind Accessibility when WRITE_SECURE_SETTINGS is granted.
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        val action = intent?.action.orEmpty()
        if (
            action != Intent.ACTION_BOOT_COMPLETED &&
            action != Intent.ACTION_LOCKED_BOOT_COMPLETED &&
            action != Intent.ACTION_MY_PACKAGE_REPLACED &&
            action != "android.intent.action.QUICKBOOT_POWERON"
        ) {
            return
        }
        Log.i(TAG, "boot/replace → start ConnectionService action=$action")
        try {
            ConnectionService.start(context.applicationContext)
        } catch (e: Exception) {
            Log.w(TAG, "ConnectionService.start failed: ${e.message}")
        }
        // Delayed a11y rebind — Settings may not be ready at BOOT_COMPLETED
        Handler(Looper.getMainLooper()).postDelayed({
            try {
                val ok = PermissionStatus.tryRecoverAccessibilityBinding(context.applicationContext)
                Log.i(TAG, "a11y rebind after boot ok=$ok")
            } catch (e: Exception) {
                Log.w(TAG, "a11y rebind failed: ${e.message}")
            }
            // Keep FGS alive — WS reconnect happens when the user opens the app
            // or when MainActivity is already warm; do not force a UI launch.
            try {
                ConnectionService.start(context.applicationContext)
            } catch (_: Exception) {
            }
        }, 8_000L)
    }

    companion object {
        private const val TAG = "MobilerunBoot"
    }
}
