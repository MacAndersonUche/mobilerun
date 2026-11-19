package ai.mobilerun.selfhosted.input

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.inputmethod.InputMethodManager
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import ai.mobilerun.selfhosted.R

/**
 * Declared as android:settingsActivity for Mobilerun Keyboard so Samsung /
 * AOSP list the IME under Keyboard settings. Guides the user through enable
 * + picker without requiring WRITE_SECURE_SETTINGS.
 */
class ImeSettingsActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    ImeSettingsScreen(
                        onOpenSettings = { openInputMethodSettings(this) },
                        onShowPicker = { showInputMethodPicker(this) },
                    )
                }
            }
        }
    }

    companion object {
        fun openInputMethodSettings(context: Context) {
            try {
                context.startActivity(
                    Intent(Settings.ACTION_INPUT_METHOD_SETTINGS).apply {
                        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    },
                )
            } catch (_: Exception) {
                Toast.makeText(
                    context,
                    R.string.keyboard_switch_unavailable,
                    Toast.LENGTH_SHORT,
                ).show()
            }
        }

        fun showInputMethodPicker(context: Context) {
            val imm =
                context.getSystemService(Context.INPUT_METHOD_SERVICE) as? InputMethodManager
            if (imm == null) {
                Toast.makeText(
                    context,
                    R.string.keyboard_switch_unavailable,
                    Toast.LENGTH_SHORT,
                ).show()
                return
            }
            try {
                imm.showInputMethodPicker()
            } catch (_: Exception) {
                openInputMethodSettings(context)
            }
        }

        /** Settings first, then picker so the user can enable us then select us. */
        fun openSettingsThenPicker(context: Context, pickerDelayMs: Long = 1_200L) {
            openInputMethodSettings(context)
            Handler(Looper.getMainLooper()).postDelayed({
                showInputMethodPicker(context)
            }, pickerDelayMs)
        }
    }
}

@Composable
private fun ImeSettingsScreen(
    onOpenSettings: () -> Unit,
    onShowPicker: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text(
            stringResource(R.string.ime_settings_title),
            style = MaterialTheme.typography.headlineSmall,
        )
        Text(
            stringResource(R.string.ime_settings_body),
            style = MaterialTheme.typography.bodyMedium,
        )
        Text(
            stringResource(R.string.ime_enable_help),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Button(
            onClick = onOpenSettings,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(stringResource(R.string.ime_settings_open))
        }
        OutlinedButton(
            onClick = onShowPicker,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(stringResource(R.string.ime_settings_picker))
        }
    }
}
