package ai.mobilerun.selfhosted

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.util.Log
import androidx.browser.customtabs.CustomTabsIntent
import com.google.gson.Gson
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import okhttp3.FormBody
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64
import java.util.concurrent.TimeUnit

/**
 * Cognito sign-in for the APK:
 * 1) Preferred: device-code flow (show code → approve on Netlify Account page).
 * 2) Fallback: Custom Tabs / AppAuth-style authorize + PKCE to Cognito Hosted UI.
 *
 * Same Cognito user pool as the hosted web UI — device auto-registers to that account.
 */
class CognitoAuth(private val context: Context) {
    private val tag = "CognitoAuth"
    private val gson = Gson()
    private val http = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    private fun prefs() = context.getSharedPreferences("mobilerun", Context.MODE_PRIVATE)

    fun savedIdToken(): String? = prefs().getString("id_token", null)
    fun savedAccessToken(): String? = prefs().getString("access_token", null)
    fun savedEmail(): String? = prefs().getString("user_email", null)

    fun clear() {
        prefs().edit()
            .remove("id_token")
            .remove("access_token")
            .remove("user_email")
            .remove("pkce_verifier")
            .apply()
    }

    fun storeTokens(idToken: String?, accessToken: String?, email: String?) {
        prefs().edit()
            .putString("id_token", idToken)
            .putString("access_token", accessToken)
            .putString("user_email", email)
            .apply()
    }

    data class DeviceCodeResponse(
        val user_code: String,
        val device_code: String,
        val expires_in: Int = 600,
        val interval: Int = 3,
        val verification_uri: String? = null,
        val message: String? = null,
    )

    data class TokenResponse(
        val access_token: String?,
        val session_token: String?,
        val device_id: String?,
        val owner: String?,
        val token_type: String? = null,
    )

    /** Start device-code link against the MobileRun backend (not Cognito directly). */
    suspend fun startDeviceCode(backendHttp: String, deviceName: String = "Android"): DeviceCodeResponse =
        withContext(Dispatchers.IO) {
            val body = gson.toJson(
                mapOf("device_name" to deviceName, "platform" to "android"),
            ).toRequestBody("application/json".toMediaType())
            val req = Request.Builder()
                .url("${backendHttp.trimEnd('/')}/api/auth/device/code")
                .post(body)
                .build()
            http.newCall(req).execute().use { resp ->
                val text = resp.body?.string().orEmpty()
                if (!resp.isSuccessful) error("device code failed: ${resp.code} $text")
                gson.fromJson(text, DeviceCodeResponse::class.java)
            }
        }

    /**
     * Poll until the web UI approves the code. Returns tokens + session for WS auth.
     */
    suspend fun pollDeviceCode(
        backendHttp: String,
        deviceCode: String,
        intervalSec: Int = 3,
        onTick: ((String) -> Unit)? = null,
    ): TokenResponse = withContext(Dispatchers.IO) {
        val deadline = System.currentTimeMillis() + 600_000
        while (System.currentTimeMillis() < deadline) {
            onTick?.invoke("Waiting for approval…")
            val body = gson.toJson(mapOf("device_code" to deviceCode))
                .toRequestBody("application/json".toMediaType())
            val req = Request.Builder()
                .url("${backendHttp.trimEnd('/')}/api/auth/device/token")
                .post(body)
                .build()
            http.newCall(req).execute().use { resp ->
                val text = resp.body?.string().orEmpty()
                if (resp.isSuccessful) {
                    val tok = gson.fromJson(text, TokenResponse::class.java)
                    storeTokens(tok.access_token, tok.access_token, tok.owner)
                    return@withContext tok
                }
                if (text.contains("authorization_pending") || resp.code == 400) {
                    delay((intervalSec * 1000L).coerceAtLeast(2000))
                } else {
                    error("poll failed: ${resp.code} $text")
                }
            }
        }
        error("Device code expired")
    }

    /** Open Cognito Hosted UI in a Custom Tab (PKCE). */
    fun openHostedUi(
        domain: String,
        clientId: String,
        redirectUri: String,
        identityProvider: String? = null,
    ) {
        val verifier = randomVerifier()
        prefs().edit().putString("pkce_verifier", verifier).apply()
        val challenge = sha256Base64Url(verifier)
        val params = Uri.Builder()
            .scheme("https")
            .authority(domain.removePrefix("https://").trimEnd('/'))
            .appendPath("oauth2")
            .appendPath("authorize")
            .appendQueryParameter("client_id", clientId)
            .appendQueryParameter("response_type", "code")
            .appendQueryParameter("scope", "openid email profile")
            .appendQueryParameter("redirect_uri", redirectUri)
            .appendQueryParameter("code_challenge_method", "S256")
            .appendQueryParameter("code_challenge", challenge)
        if (!identityProvider.isNullOrBlank()) {
            params.appendQueryParameter("identity_provider", identityProvider)
        }
        val intent = CustomTabsIntent.Builder().build()
        intent.launchUrl(context, params.build())
    }

    suspend fun exchangeAuthCode(
        domain: String,
        clientId: String,
        redirectUri: String,
        code: String,
    ): Map<*, *> = withContext(Dispatchers.IO) {
        val verifier = prefs().getString("pkce_verifier", "") ?: ""
        val form = FormBody.Builder()
            .add("grant_type", "authorization_code")
            .add("client_id", clientId)
            .add("code", code)
            .add("redirect_uri", redirectUri)
            .add("code_verifier", verifier)
            .build()
        val req = Request.Builder()
            .url("https://${domain.removePrefix("https://").trimEnd('/')}/oauth2/token")
            .post(form)
            .build()
        http.newCall(req).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) error("token exchange failed: ${resp.code} $text")
            @Suppress("UNCHECKED_CAST")
            val map = gson.fromJson(text, Map::class.java) as Map<String, Any?>
            val id = map["id_token"] as? String
            val access = map["access_token"] as? String
            val email = id?.let { decodeEmail(it) }
            storeTokens(id, access, email)
            map
        }
    }

    fun handleRedirectIntent(intent: Intent?, domain: String, clientId: String, redirectUri: String) {
        val data = intent?.data ?: return
        val code = data.getQueryParameter("code") ?: return
        // Caller should launch a coroutine to exchangeAuthCode
        Log.d(tag, "Got auth code from redirect")
        prefs().edit().putString("pending_auth_code", code).apply()
        prefs().edit().putString("cognito_domain", domain)
            .putString("cognito_client_id", clientId)
            .putString("cognito_redirect", redirectUri)
            .apply()
    }

    private fun decodeEmail(idToken: String): String? = try {
        val payload = idToken.split(".")[1]
        val padded = payload + "=".repeat((4 - payload.length % 4) % 4)
        val json = String(Base64.getUrlDecoder().decode(padded))
        @Suppress("UNCHECKED_CAST")
        (gson.fromJson(json, Map::class.java) as Map<String, Any?>)["email"] as? String
    } catch (e: Exception) {
        null
    }

    private fun randomVerifier(len: Int = 64): String {
        val alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
        val rnd = SecureRandom()
        return (1..len).map { alphabet[rnd.nextInt(alphabet.length)] }.joinToString("")
    }

    private fun sha256Base64Url(input: String): String {
        val md = MessageDigest.getInstance("SHA-256")
        val dig = md.digest(input.toByteArray(Charsets.US_ASCII))
        return Base64.getUrlEncoder().withoutPadding().encodeToString(dig)
    }
}
