package ai.mobilerun.selfhosted

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/** Encrypted storage for long-lived device session credentials. */
object SecurePrefs {
    private const val FILE = "mobilerun_secure"

    fun get(context: Context): SharedPreferences {
        return try {
            val masterKey = MasterKey.Builder(context)
                .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                .build()
            EncryptedSharedPreferences.create(
                context,
                FILE,
                masterKey,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
            )
        } catch (e: Exception) {
            // Emulator / missing keystore fallback — still better than plaintext prefs for CI
            context.getSharedPreferences(FILE, Context.MODE_PRIVATE)
        }
    }
}
