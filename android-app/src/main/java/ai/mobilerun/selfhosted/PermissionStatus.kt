package ai.mobilerun.selfhosted

import android.Manifest
import android.accessibilityservice.AccessibilityServiceInfo
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import android.view.accessibility.AccessibilityManager
import androidx.core.content.ContextCompat

/**
 * First-run / resume permission checklist for the executor APK.
 * Reports status to the hosted UI over WebSocket.
 */
object PermissionStatus {
    data class Snapshot(
        val accessibility: Boolean,
        val notifications: Boolean,
        val mediaProjection: Boolean,
        val batteryOptimization: Boolean,
        val overlay: Boolean,
        val queryPackages: Boolean,
        val foregroundService: Boolean,
    ) {
        fun toMap(mediaGranted: Boolean = mediaProjection): Map<String, Any?> = mapOf(
            "accessibility" to accessibility,
            "notifications" to notifications,
            "media_projection" to mediaGranted,
            "battery_optimization" to batteryOptimization,
            "overlay" to overlay,
            "query_packages" to queryPackages,
            "foreground_service" to foregroundService,
            "updated_at" to System.currentTimeMillis(),
        )

        val allCritical: Boolean
            get() = accessibility && notifications && batteryOptimization && foregroundService
    }

    fun snapshot(context: Context, mediaProjectionGranted: Boolean = false): Snapshot {
        return Snapshot(
            accessibility = isAccessibilityEnabled(context),
            notifications = hasNotifications(context),
            mediaProjection = mediaProjectionGranted,
            batteryOptimization = isIgnoringBatteryOptimizations(context),
            overlay = canDrawOverlays(context),
            queryPackages = canQueryPackages(context),
            foregroundService = true, // declared; ConnectionService starts after login
        )
    }

    fun isAccessibilityEnabled(context: Context): Boolean {
        val am = context.getSystemService(Context.ACCESSIBILITY_SERVICE) as AccessibilityManager
        val enabled = am.getEnabledAccessibilityServiceList(AccessibilityServiceInfo.FEEDBACK_ALL_MASK)
        val pkg = context.packageName
        return enabled.any { it.resolveInfo?.serviceInfo?.packageName == pkg }
            || MobilerunAccessibilityService.instance != null
    }

    fun hasNotifications(context: Context): Boolean {
        if (Build.VERSION.SDK_INT < 33) return true
        return ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.POST_NOTIFICATIONS,
        ) == PackageManager.PERMISSION_GRANTED
    }

    fun isIgnoringBatteryOptimizations(context: Context): Boolean {
        val pm = context.getSystemService(Context.POWER_SERVICE) as PowerManager
        return pm.isIgnoringBatteryOptimizations(context.packageName)
    }

    fun canDrawOverlays(context: Context): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            Settings.canDrawOverlays(context)
        } else true
    }

    fun canQueryPackages(context: Context): Boolean {
        // QUERY_ALL_PACKAGES is install-time; verify we can resolve a known launcher
        return try {
            val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
            context.packageManager.queryIntentActivities(intent, 0).isNotEmpty()
        } catch (_: Exception) {
            false
        }
    }

    fun openAccessibilitySettings(context: Context) {
        context.startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    /** Android 13+ sideload: Apps → MobileRun → ⋮ → Allow restricted settings */
    fun openAppDetails(context: Context) {
        val intent = Intent(
            Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
            Uri.fromParts("package", context.packageName, null),
        ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
    }

    fun openBatterySettings(context: Context) {
        try {
            val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
                data = Uri.parse("package:${context.packageName}")
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(intent)
        } catch (_: Exception) {
            context.startActivity(
                Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            )
        }
    }

    fun openOverlaySettings(context: Context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            context.startActivity(
                Intent(
                    Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:${context.packageName}"),
                ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            )
        }
    }

    fun restrictedSettingsNeeded(context: Context): Boolean {
        // Heuristic: accessibility off on API 33+ for sideloaded apps often needs restricted settings
        return Build.VERSION.SDK_INT >= 33 && !isAccessibilityEnabled(context)
    }
}
