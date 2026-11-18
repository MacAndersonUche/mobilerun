package ai.mobilerun.selfhosted

import android.Manifest
import android.accessibilityservice.AccessibilityServiceInfo
import android.content.ComponentName
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
 * Minimal permission surface for the executor APK.
 *
 * Required for agent work: Accessibility (manual).
 * Auto-prompted once: POST_NOTIFICATIONS, battery unrestricted.
 * Not in onboarding: overlay, MediaProjection (live-view only, on demand),
 * QUERY_ALL_PACKAGES (install-time), foreground service (started by app).
 */
object PermissionStatus {
    data class Snapshot(
        val accessibility: Boolean,
        val accessibilityBound: Boolean,
        val accessibilityStuckBinding: Boolean,
        val notifications: Boolean,
        val mediaProjection: Boolean,
        val batteryOptimization: Boolean,
        val overlay: Boolean,
        val queryPackages: Boolean,
        val foregroundService: Boolean,
    ) {
        fun toMap(mediaGranted: Boolean = mediaProjection): Map<String, Any?> = mapOf(
            "accessibility" to accessibility,
            "accessibility_bound" to accessibilityBound,
            "accessibility_stuck_binding" to accessibilityStuckBinding,
            "notifications" to notifications,
            "media_projection" to mediaGranted,
            "battery_optimization" to batteryOptimization,
            // Kept in wire format for older portal rows; always optional now
            "overlay" to overlay,
            "query_packages" to queryPackages,
            "foreground_service" to foregroundService,
            "updated_at" to System.currentTimeMillis(),
        )

        /** Ready for automation tasks (live view is optional). */
        val readyForAgent: Boolean
            get() = accessibility && accessibilityBound && !accessibilityStuckBinding

        val needsAutoGrant: Boolean
            get() = !notifications || !batteryOptimization
    }

    fun snapshot(context: Context, mediaProjectionGranted: Boolean = false): Snapshot {
        val enabledInSettings = isAccessibilityEnabledInSettings(context)
        val bound = isAccessibilityBound()
        return Snapshot(
            accessibility = enabledInSettings || bound,
            accessibilityBound = bound,
            accessibilityStuckBinding = enabledInSettings && !bound,
            notifications = hasNotifications(context),
            mediaProjection = mediaProjectionGranted ||
                context.getSharedPreferences("mobilerun", Context.MODE_PRIVATE)
                    .getBoolean("media_projection_granted", false),
            batteryOptimization = isIgnoringBatteryOptimizations(context),
            overlay = false, // no longer requested; report false so portal does not nag
            queryPackages = canQueryPackages(context),
            foregroundService = true,
        )
    }

    fun isAccessibilityBound(): Boolean = MobilerunAccessibilityService.instance != null

    fun isAccessibilityEnabledInSettings(context: Context): Boolean {
        val am = context.getSystemService(Context.ACCESSIBILITY_SERVICE) as AccessibilityManager
        val enabled = am.getEnabledAccessibilityServiceList(AccessibilityServiceInfo.FEEDBACK_ALL_MASK)
        val pkg = context.packageName
        return enabled.any { it.resolveInfo?.serviceInfo?.packageName == pkg }
    }

    fun isAccessibilityEnabled(context: Context): Boolean {
        return isAccessibilityEnabledInSettings(context) || isAccessibilityBound()
    }

    /**
     * Best-effort recover when Settings shows the service Enabled but it is stuck
     * in Binding (instance == null). Requires WRITE_SECURE_SETTINGS (adb grant /
     * device-owner). Falls back to opening Accessibility settings.
     */
    fun tryRecoverAccessibilityBinding(context: Context): Boolean {
        if (isAccessibilityBound()) return true
        val cn = ComponentName(context, MobilerunAccessibilityService::class.java)
            .flattenToString()
        return try {
            val cr = context.contentResolver
            // Toggle off then on to force a fresh bind
            Settings.Secure.putString(cr, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES, "")
            Settings.Secure.putInt(cr, Settings.Secure.ACCESSIBILITY_ENABLED, 0)
            Thread.sleep(250)
            Settings.Secure.putString(cr, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES, cn)
            Settings.Secure.putInt(cr, Settings.Secure.ACCESSIBILITY_ENABLED, 1)
            Thread.sleep(400)
            isAccessibilityBound()
        } catch (_: SecurityException) {
            false
        } catch (_: Exception) {
            false
        }
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

    fun canQueryPackages(context: Context): Boolean {
        return try {
            val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
            context.packageManager.queryIntentActivities(intent, 0).isNotEmpty()
        } catch (_: Exception) {
            false
        }
    }

    /** Deep-link to this app's AccessibilityService details when possible. */
    fun openAccessibilitySettings(context: Context) {
        val cn = ComponentName(context, MobilerunAccessibilityService::class.java)
        // String constant — Settings.ACTION_ACCESSIBILITY_DETAILS_SETTINGS is API 31+
        // and may be missing from older compileSdk stubs.
        val detailsAction = "android.settings.ACCESSIBILITY_DETAILS_SETTINGS"
        if (Build.VERSION.SDK_INT >= 31) {
            try {
                context.startActivity(
                    Intent(detailsAction).apply {
                        putExtra(Intent.EXTRA_COMPONENT_NAME, cn)
                        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    },
                )
                return
            } catch (_: Exception) {
            }
            try {
                context.startActivity(
                    Intent(detailsAction).apply {
                        data = Uri.fromParts("package", context.packageName, null)
                        putExtra(Intent.EXTRA_COMPONENT_NAME, cn)
                        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    },
                )
                return
            } catch (_: Exception) {
            }
        }
        // Fallback: general Accessibility list (user picks MobileRun)
        context.startActivity(
            Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        )
    }

    /** Android 13+ sideload: Apps → MobileRun → ⋮ → Allow restricted settings */
    fun openAppDetails(context: Context) {
        val intent = Intent(
            Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
            Uri.fromParts("package", context.packageName, null),
        ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
    }

    fun batteryExemptionIntent(context: Context): Intent {
        return try {
            Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
                data = Uri.parse("package:${context.packageName}")
            }
        } catch (_: Exception) {
            Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)
        }
    }

    fun openBatterySettings(context: Context) {
        try {
            context.startActivity(
                batteryExemptionIntent(context).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            )
        } catch (_: Exception) {
            context.startActivity(
                Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            )
        }
    }

    fun restrictedSettingsNeeded(context: Context): Boolean {
        return Build.VERSION.SDK_INT >= 33 && !isAccessibilityEnabled(context)
    }
}
