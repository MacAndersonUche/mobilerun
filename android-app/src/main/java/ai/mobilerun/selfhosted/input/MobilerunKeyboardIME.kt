package ai.mobilerun.selfhosted.input

import ai.mobilerun.selfhosted.R

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.inputmethodservice.InputMethodService
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.provider.Settings
import android.util.Base64
import android.util.Log
import android.view.KeyEvent
import android.view.View
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.widget.Button
import android.widget.Toast
import java.util.concurrent.CountDownLatch
import java.util.concurrent.ThreadLocalRandom
import java.util.concurrent.TimeUnit

/** Outcome for cloud command routing (mirrors Portal ApiHandler.keyboardInput). */
enum class AutomationInput {
    /** Verified or accepted — do not also run a11y SET_TEXT. */
    DONE,
    /** IME unavailable / rejected — fall back to accessibility. */
    FALLBACK,
    /** IME committed but unverifiable — skip a11y to avoid double-type. */
    STUCK,
}

class MobilerunKeyboardIME : InputMethodService() {
    private val TAG = "MobilerunKeyboardIME"
    @Volatile
    private var inputGeneration = 0L
    private val textEditor by lazy {
        InputConnectionTextEditor(
            connectionProvider = { currentInputConnection },
            generationProvider = { inputGeneration },
            sleep = SystemClock::sleep,
        )
    }

    companion object {
        private var instance: MobilerunKeyboardIME? = null

        fun getInstance(): MobilerunKeyboardIME? = instance

        /**
         * Check if the MobilerunKeyboardIME is currently active and available
         */
        fun isAvailable(): Boolean = instance != null

        /**
         * Check if this IME is currently selected as the system default
         */
        fun isSelected(context: android.content.Context): Boolean {
            val currentId = android.provider.Settings.Secure.getString(
                context.contentResolver,
                android.provider.Settings.Secure.DEFAULT_INPUT_METHOD
            )
            val myId = android.content.ComponentName(context, MobilerunKeyboardIME::class.java).flattenToShortString()
            return currentId == myId
        }

        /**
         * Portal order: try IME when selected+available, else FALLBACK to a11y.
         * AcceptedUnverified / session-changed → STUCK (no a11y double-input).
         */
        fun tryAutomationInput(
            context: android.content.Context,
            text: String,
            clear: Boolean,
            humanize: Boolean = true,
        ): AutomationInput {
            if (!isAvailable() || !isSelected(context)) return AutomationInput.FALLBACK
            val ime = getInstance() ?: return AutomationInput.FALLBACK
            if (!ime.hasInputConnection()) return AutomationInput.FALLBACK
            val result = if (humanize && text.length > 2) {
                ime.inputTextHumanPaced(text, clear)
            } else {
                ime.inputTextResult(text, clear)
            }
            return when (result) {
                TextInputResult.Verified,
                TextInputResult.AcceptedUnverified -> AutomationInput.DONE
                TextInputResult.Rejected -> AutomationInput.FALLBACK
                TextInputResult.CommitOutcomeUnknown,
                TextInputResult.InputSessionChanged -> AutomationInput.STUCK
            }
        }
    }

    /** Focused EditorInfo + heuristics for search vs compose (WhatsApp id/entry). */
    fun focusedFieldInfo(): Map<String, Any?> {
        val ei = currentInputEditorInfo
        val pkg = ei?.packageName
        val viewId = try {
            if (ei != null && ei.fieldId != 0 && pkg != null) {
                // fieldId alone is not a resource name; prefer a11y when available
                null
            } else null
        } catch (_: Exception) {
            null
        }
        val hint = ei?.hintText?.toString()
        val inputType = ei?.inputType ?: 0
        val imeAction = if (ei != null) ei.imeOptions and EditorInfo.IME_MASK_ACTION else 0
        val a11y = ai.mobilerun.selfhosted.MobilerunAccessibilityService.instance
            ?.focusedEditableMeta()
        val resolvedId = (a11y?.get("viewId") as? String) ?: viewId
        val resolvedHint = (a11y?.get("hint") as? String)?.takeIf { it.isNotBlank() } ?: hint
        val resolvedPkg = (a11y?.get("packageName") as? String) ?: pkg
        val idLow = resolvedId.orEmpty().lowercase()
        val hintLow = resolvedHint.orEmpty().lowercase()
        val isSearch = imeAction == EditorInfo.IME_ACTION_SEARCH ||
            idLow.contains("search") ||
            hintLow.contains("search") ||
            hintLow.startsWith("to:")
        val isCompose = !isSearch && (
            idLow.endsWith("/entry") ||
                idLow.endsWith(":id/entry") ||
                idLow.contains("entry") ||
                idLow.contains("compose") ||
                hintLow.contains("message") ||
                hintLow.contains("type a message") ||
                hintLow.contains("write a message") ||
                imeAction == EditorInfo.IME_ACTION_SEND
            )
        return mapOf(
            "packageName" to resolvedPkg,
            "viewId" to resolvedId,
            "hint" to resolvedHint,
            "inputType" to inputType,
            "imeAction" to imeAction,
            "imeActionName" to imeActionName(imeAction),
            "isSearch" to isSearch,
            "isCompose" to isCompose,
            "hasConnection" to hasInputConnection(),
            "selected" to isSelected(this),
            "text" to (a11y?.get("text") as? String),
            "className" to (a11y?.get("className") as? String),
        )
    }

    private fun imeActionName(action: Int): String = when (action) {
        EditorInfo.IME_ACTION_SEND -> "send"
        EditorInfo.IME_ACTION_SEARCH -> "search"
        EditorInfo.IME_ACTION_GO -> "go"
        EditorInfo.IME_ACTION_DONE -> "done"
        EditorInfo.IME_ACTION_NEXT -> "next"
        EditorInfo.IME_ACTION_PREVIOUS -> "previous"
        EditorInfo.IME_ACTION_NONE -> "none"
        else -> "unspecified"
    }

    /**
     * Human-paced InputConnection.commitText in small chunks (Portal-style control
     * of our own keyboard — not a11y SET_TEXT).
     */
    internal fun inputTextHumanPaced(text: String, clear: Boolean = true): TextInputResult {
        if (text.isEmpty()) return inputTextResult("", clear)
        if (clear) {
            val cleared = clearTextResult()
            if (cleared == TextInputResult.Rejected ||
                cleared == TextInputResult.InputSessionChanged
            ) {
                return cleared
            }
        }
        val rng = ThreadLocalRandom.current()
        var i = 0
        var last: TextInputResult = TextInputResult.Rejected
        val budgetMs = 2_500L
        var slept = 0L
        while (i < text.length) {
            val remaining = text.length - i
            val chunk = if (slept >= budgetMs) {
                remaining
            } else {
                rng.nextInt(2, 6).coerceAtMost(remaining)
            }
            val piece = text.substring(i, i + chunk)
            last = inputTextResult(piece, clear = false)
            if (last == TextInputResult.Rejected ||
                last == TextInputResult.InputSessionChanged
            ) {
                return last
            }
            i += chunk
            if (i < text.length && slept < budgetMs) {
                val pause = rng.nextLong(35, 95)
                val allowed = (budgetMs - slept).coerceAtLeast(0L)
                val actual = pause.coerceAtMost(allowed)
                if (actual > 0) {
                    SystemClock.sleep(actual)
                    slept += actual
                }
            }
        }
        return when (last) {
            TextInputResult.Verified,
            TextInputResult.AcceptedUnverified -> TextInputResult.Verified
            else -> last
        }
    }

    /** performEditorAction — SEND when the field supports it (WhatsApp compose). */
    fun performImeAction(action: String = "send"): Boolean {
        val ic = currentInputConnection ?: return false
        val ei = currentInputEditorInfo
        val want = when (action.lowercase()) {
            "send" -> EditorInfo.IME_ACTION_SEND
            "search" -> EditorInfo.IME_ACTION_SEARCH
            "go" -> EditorInfo.IME_ACTION_GO
            "done" -> EditorInfo.IME_ACTION_DONE
            "next" -> EditorInfo.IME_ACTION_NEXT
            else -> EditorInfo.IME_ACTION_SEND
        }
        val fieldAction = ei?.let { it.imeOptions and EditorInfo.IME_MASK_ACTION }
            ?: EditorInfo.IME_ACTION_UNSPECIFIED
        val target = when {
            fieldAction == want -> want
            fieldAction != EditorInfo.IME_ACTION_UNSPECIFIED &&
                fieldAction != EditorInfo.IME_ACTION_NONE -> fieldAction
            else -> want
        }
        return try {
            val ok = ic.performEditorAction(target)
            Log.i(TAG, "performEditorAction action=$action target=$target ok=$ok")
            if (!ok && action.equals("send", ignoreCase = true)) {
                // Fallback: ENTER key for apps that don't wire IME_ACTION_SEND
                sendKeyEventDirect(KeyEvent.KEYCODE_ENTER)
            } else {
                ok
            }
        } catch (e: Exception) {
            Log.w(TAG, "performEditorAction failed: ${e.message}")
            false
        }
    }

    override fun onCreate() {
        super.onCreate()
        instance = this
        Log.d(TAG, "MobilerunKeyboardIME: onCreate() called")
    }


    /**
     * Direct method to input text from Base64 without using broadcasts
     */
    fun inputB64Text(base64Text: String, clear: Boolean = true): Boolean {
        return inputB64TextResult(base64Text, clear) == TextInputResult.Verified
    }

    internal fun inputB64TextResult(base64Text: String, clear: Boolean = true): TextInputResult {
        return try {
            val decoded = Base64.decode(base64Text, Base64.DEFAULT)
            val text = String(decoded, Charsets.UTF_8)
            inputTextResult(text, clear)
        } catch (e: Exception) {
            Log.e(TAG, "Error decoding base64 for direct input", e)
            TextInputResult.Rejected
        }
    }
    
    fun inputText(text: String, clear: Boolean = true): Boolean {
        return inputTextResult(text, clear) == TextInputResult.Verified
    }

    internal fun inputTextResult(text: String, clear: Boolean = true): TextInputResult {
        return try {
            val result = textEditor.inputText(text, clear)
            when (result) {
                TextInputResult.Verified -> Log.d(TAG, "Text input verified (clear=$clear)")
                TextInputResult.Rejected -> Log.w(TAG, "Text input rejected (clear=$clear)")
                TextInputResult.AcceptedUnverified -> {
                    Log.w(TAG, "Text input accepted but could not be verified (clear=$clear)")
                }
                TextInputResult.CommitOutcomeUnknown -> {
                    Log.w(TAG, "Text input commit outcome is unknown (clear=$clear)")
                }
                TextInputResult.InputSessionChanged -> {
                    Log.w(TAG, "Input session changed during text input (clear=$clear)")
                }
            }
            result
        } catch (e: Exception) {
            Log.e(TAG, "Error in text input", e)
            TextInputResult.Rejected
        }
    }
    

    /**
     * Direct method to clear text without using broadcasts
     */
    fun clearText(): Boolean {
        return clearTextResult() == TextInputResult.Verified
    }

    internal fun clearTextResult(): TextInputResult {
        return inputTextResult("", clear = true)
    }

    /**
     * Direct method to send key events without using broadcasts
     */
    fun sendKeyEventDirect(keyCode: Int): Boolean {
        return try {
            val ic = currentInputConnection
            if (ic != null) {
                ic.sendKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN, keyCode))
                ic.sendKeyEvent(KeyEvent(KeyEvent.ACTION_UP, keyCode))
                Log.d(TAG, "Direct key event sent: $keyCode")
                true
            } else {
                Log.w(TAG, "No input connection available for direct key event")
                false
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error sending direct key event", e)
            false
        }
    }

    /**
     * Get current input connection status
     */
    fun hasInputConnection(): Boolean {
        return currentInputConnection != null
    }

    fun getClipboardText(): String? {
        return try {
            runOnMainThreadBlocking {
                val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
                    ?: return@runOnMainThreadBlocking null
                clipboard.primaryClip
                    ?.takeIf { it.itemCount > 0 }
                    ?.getItemAt(0)
                    ?.coerceToText(this)
                    ?.toString()
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to read clipboard", e)
            null
        }
    }

    fun setClipboardText(text: String): Boolean {
        return try {
            runOnMainThreadBlocking {
                val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
                    ?: return@runOnMainThreadBlocking false
                clipboard.setPrimaryClip(ClipData.newPlainText("text", text))
                true
            } ?: false
        } catch (e: Exception) {
            Log.e(TAG, "Failed to set clipboard", e)
            false
        }
    }

    private fun <T> runOnMainThreadBlocking(block: () -> T): T? {
        if (!shouldUseMainThreadClipboardAccess()) {
            return block()
        }

        var result: T? = null
        var failure: Throwable? = null
        val latch = CountDownLatch(1)
        Handler(Looper.getMainLooper()).post {
            try {
                result = block()
            } catch (t: Throwable) {
                failure = t
            } finally {
                latch.countDown()
            }
        }
        if (!latch.await(2, TimeUnit.SECONDS)) {
            throw IllegalStateException("Timed out waiting for main thread clipboard access")
        }
        failure?.let { throw it }
        return result
    }

    private fun shouldUseMainThreadClipboardAccess(): Boolean {
        return Build.VERSION.SDK_INT > 0 &&
            Build.VERSION.SDK_INT <= Build.VERSION_CODES.O_MR1 &&
            Looper.myLooper() == null
    }

    override fun onCreateInputView(): View {
        Log.d(TAG, "onCreateInputView called")

        val view = layoutInflater.inflate(R.layout.keyboard_view, null)
        view.findViewById<Button>(R.id.switch_keyboard_button)?.setOnClickListener {
            handleSwitchKeyboard()
        }
        return view
    }

    override fun onStartInput(attribute: android.view.inputmethod.EditorInfo?, restarting: Boolean) {
        inputGeneration++
        super.onStartInput(attribute, restarting)
        Log.d(TAG, "onStartInput called - restarting: $restarting")
    }

    override fun onFinishInput() {
        inputGeneration++
        super.onFinishInput()
    }

    override fun onStartInputView(attribute: android.view.inputmethod.EditorInfo?, restarting: Boolean) {
        super.onStartInputView(attribute, restarting)
        Log.d(TAG, "onStartInputView called - keyboard should be visible now")
    }

    override fun onDestroy() {
        Log.d(TAG, "MobilerunKeyboardIME: onDestroy() called")
        instance = null
        super.onDestroy()
    }

    private fun handleSwitchKeyboard() {
        if (showInputMethodPickerIfAlternativeExists()) return
        openInputMethodSettings()
    }

    private fun showInputMethodPickerIfAlternativeExists(): Boolean {
        val imm = getSystemService(Context.INPUT_METHOD_SERVICE) as? InputMethodManager ?: return false
        if (imm.enabledInputMethodList.size <= 1) return false

        return try {
            imm.showInputMethodPicker()
            true
        } catch (e: Exception) {
            Log.w(TAG, "Failed to show input method picker", e)
            false
        }
    }

    private fun openInputMethodSettings() {
        try {
            val intent = Intent(Settings.ACTION_INPUT_METHOD_SETTINGS).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            startActivity(intent)
            Toast.makeText(this, R.string.keyboard_switch_settings_help, Toast.LENGTH_LONG).show()
        } catch (e: Exception) {
            Log.e(TAG, "Error opening keyboard settings", e)
            Toast.makeText(this, R.string.keyboard_switch_unavailable, Toast.LENGTH_SHORT).show()
        }
    }
}
