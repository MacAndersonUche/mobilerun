package ai.mobilerun.selfhosted.input

import android.content.ComponentName
import android.content.Context
import android.provider.Settings
import android.util.Log
import android.view.inputmethod.InputMethodManager

/**
 * Switch to Mobilerun Keyboard for a task, then restore the user's IME.
 * Requires WRITE_SECURE_SETTINGS when changing the system default (adb grant /
 * device-owner). If we cannot switch, [ensureSelected] returns false and the
 * caller should fall back to a11y SET_TEXT while still reporting focus metadata.
 */
object ImeSessionController {
    private const val TAG = "ImeSession"
    private const val PREFS = "mobilerun_ime"
    private const val KEY_PREV = "previous_ime"
    private const val KEY_TASK_ACTIVE = "task_ime_active"

    fun componentId(context: Context): String =
        ComponentName(context, MobilerunKeyboardIME::class.java).flattenToShortString()

    fun currentDefault(context: Context): String? =
        Settings.Secure.getString(
            context.contentResolver,
            Settings.Secure.DEFAULT_INPUT_METHOD,
        )

    fun isOursSelected(context: Context): Boolean =
        currentDefault(context) == componentId(context)

    /** Enable + select Mobilerun Keyboard; remember previous IME for restore. */
    fun ensureSelected(context: Context): Map<String, Any?> {
        val ours = componentId(context)
        val current = currentDefault(context)
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        if (current == ours) {
            prefs.edit().putBoolean(KEY_TASK_ACTIVE, true).apply()
            return mapOf(
                "ok" to true,
                "selected" to true,
                "already" to true,
                "ime" to ours,
                "previous" to prefs.getString(KEY_PREV, null),
            )
        }
        if (!current.isNullOrBlank() && current != ours) {
            prefs.edit().putString(KEY_PREV, current).apply()
        }
        val enabledOk = tryEnableInList(context, ours)
        val selectedOk = trySetDefault(context, ours)
        val nowSelected = isOursSelected(context) || MobilerunKeyboardIME.isSelected(context)
        if (nowSelected) {
            prefs.edit().putBoolean(KEY_TASK_ACTIVE, true).apply()
        }
        Log.i(TAG, "ensureSelected enabled=$enabledOk selected=$selectedOk now=$nowSelected")
        return mapOf(
            "ok" to nowSelected,
            "selected" to nowSelected,
            "enabled" to enabledOk,
            "switched" to selectedOk,
            "ime" to ours,
            "previous" to prefs.getString(KEY_PREV, null),
            "needs_user" to !nowSelected,
        )
    }

    /** Restore the IME that was active before [ensureSelected]. */
    fun restore(context: Context): Map<String, Any?> {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val prev = prefs.getString(KEY_PREV, null)
        val ours = componentId(context)
        if (prev.isNullOrBlank() || prev == ours) {
            prefs.edit().putBoolean(KEY_TASK_ACTIVE, false).apply()
            return mapOf(
                "ok" to true,
                "restored" to false,
                "reason" to "no_previous",
                "current" to currentDefault(context),
            )
        }
        val ok = trySetDefault(context, prev)
        if (ok) {
            prefs.edit().remove(KEY_PREV).putBoolean(KEY_TASK_ACTIVE, false).apply()
        }
        return mapOf(
            "ok" to ok,
            "restored" to ok,
            "previous" to prev,
            "current" to currentDefault(context),
            "needs_user" to !ok,
        )
    }

    private fun tryEnableInList(context: Context, imeId: String): Boolean {
        return try {
            val cr = context.contentResolver
            val key = Settings.Secure.ENABLED_INPUT_METHODS
            val existing = Settings.Secure.getString(cr, key).orEmpty()
            if (existing.split(':').any { it.equals(imeId, ignoreCase = true) }) {
                return true
            }
            val next = if (existing.isBlank()) imeId else "$existing:$imeId"
            Settings.Secure.putString(cr, key, next)
            true
        } catch (e: SecurityException) {
            Log.w(TAG, "enable IME needs WRITE_SECURE_SETTINGS: ${e.message}")
            false
        } catch (e: Exception) {
            Log.w(TAG, "enable IME failed: ${e.message}")
            false
        }
    }

    private fun trySetDefault(context: Context, imeId: String): Boolean {
        return try {
            Settings.Secure.putString(
                context.contentResolver,
                Settings.Secure.DEFAULT_INPUT_METHOD,
                imeId,
            )
            // Nudge IMM so the new IME binds sooner
            try {
                val imm = context.getSystemService(Context.INPUT_METHOD_SERVICE) as? InputMethodManager
                imm?.showInputMethodPicker()
            } catch (_: Exception) {
            }
            true
        } catch (e: SecurityException) {
            Log.w(TAG, "set default IME needs WRITE_SECURE_SETTINGS: ${e.message}")
            false
        } catch (e: Exception) {
            Log.w(TAG, "set default IME failed: ${e.message}")
            false
        }
    }
}
