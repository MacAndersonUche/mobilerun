package ai.mobilerun.selfhosted

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.util.Log
import android.widget.Toast
import androidx.core.content.FileProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.concurrent.TimeUnit
import java.util.regex.Pattern

/**
 * In-app self-update: discover the newest GitHub `apk-N` release, download the
 * APK, and hand it to the system PackageInstaller (same applicationId + signing
 * key → in-place upgrade over the previous build).
 */
object AppUpdater {
    private const val TAG = "AppUpdater"
    private const val REPO = "MacAndersonUche/mobilerun"
    private val APK_TAG = Pattern.compile("^apk-(\\d+)$")

    data class ReleaseInfo(
        val versionCode: Int,
        val versionName: String,
        val tag: String,
        val apkUrl: String,
    )

    sealed class CheckResult {
        data class UpToDate(val current: Int) : CheckResult()
        data class Available(val release: ReleaseInfo) : CheckResult()
        data class Error(val message: String) : CheckResult()
    }

    /** Short timeouts for release metadata (never block UI feel). */
    private val metaHttp: OkHttpClient =
        OkHttpClient.Builder()
            .connectTimeout(8, TimeUnit.SECONDS)
            .readTimeout(12, TimeUnit.SECONDS)
            .callTimeout(15, TimeUnit.SECONDS)
            .followRedirects(true)
            .followSslRedirects(true)
            .build()

    /** Longer timeouts for the APK download itself. */
    private val downloadHttp: OkHttpClient =
        OkHttpClient.Builder()
            .connectTimeout(20, TimeUnit.SECONDS)
            .readTimeout(120, TimeUnit.SECONDS)
            .callTimeout(180, TimeUnit.SECONDS)
            .followRedirects(true)
            .followSslRedirects(true)
            .build()

    suspend fun checkLatest(context: Context, backendHttp: String? = null): CheckResult =
        withContext(Dispatchers.IO) {
            try {
                val release =
                    fetchFromBackend(backendHttp)
                        ?: fetchFromGitHubApi()
                        ?: return@withContext CheckResult.Error("Could not reach release feed")
                val current = BuildConfig.VERSION_CODE
                if (release.versionCode <= current) {
                    CheckResult.UpToDate(current)
                } else {
                    CheckResult.Available(release)
                }
            } catch (e: Exception) {
                Log.w(TAG, "checkLatest failed: ${e.message}")
                CheckResult.Error(e.message ?: "update check failed")
            }
        }

    /**
     * Download [release] and launch the system install UI. Returns a short
     * status string for the UI; never silently uninstalls anything.
     */
    suspend fun downloadAndPromptInstall(
        activity: Activity,
        release: ReleaseInfo,
        onProgress: ((String) -> Unit)? = null,
    ): String =
        withContext(Dispatchers.IO) {
            try {
                if (!ensureInstallPermission(activity)) {
                    return@withContext "Allow installs from this app, then tap Check for update again"
                }
                onProgress?.invoke("Downloading ${release.tag}…")
                val apk = downloadApk(activity, release)
                onProgress?.invoke("Opening installer…")
                withContext(Dispatchers.Main) {
                    launchInstaller(activity, apk)
                }
                "Install prompt opened for ${release.tag} (v${release.versionName})"
            } catch (e: Exception) {
                Log.e(TAG, "downloadAndPromptInstall: ${e.message}", e)
                "Update failed: ${e.message}"
            }
        }

    /** Handle a backend `update_available` WS payload. */
    fun releaseFromWs(message: Map<String, Any?>): ReleaseInfo? {
        val code =
            (message["version_code"] as? Number)?.toInt()
                ?: (message["versionCode"] as? Number)?.toInt()
                ?: parseCodeFromTag(message["tag"] as? String)
                ?: return null
        val tag = (message["tag"] as? String)?.takeIf { it.isNotBlank() } ?: "apk-$code"
        val name =
            (message["version_name"] as? String)?.takeIf { it.isNotBlank() }
                ?: (message["versionName"] as? String)?.takeIf { it.isNotBlank() }
                ?: "1.0.$code"
        val url =
            (message["apk_url"] as? String)?.takeIf { it.isNotBlank() }
                ?: (message["apkUrl"] as? String)?.takeIf { it.isNotBlank() }
                ?: "https://github.com/$REPO/releases/download/$tag/mobilerun.apk"
        return ReleaseInfo(code, name, tag, url)
    }

    private fun parseCodeFromTag(tag: String?): Int? {
        if (tag.isNullOrBlank()) return null
        val m = APK_TAG.matcher(tag.trim())
        return if (m.matches()) m.group(1)?.toIntOrNull() else null
    }

    private fun fetchFromBackend(backendHttp: String?): ReleaseInfo? {
        val base = backendHttp?.trim()?.trimEnd('/') ?: return null
        if (base.isBlank()) return null
        val req =
            Request.Builder()
                .url("$base/api/releases/latest")
                .header("Accept", "application/json")
                .get()
                .build()
        metaHttp.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) return null
            val body = resp.body?.string().orEmpty()
            if (body.isBlank()) return null
            val json = JSONObject(body)
            val code =
                json.optInt("version_code", 0).takeIf { it > 0 }
                    ?: parseCodeFromTag(json.optString("tag"))
                    ?: parseCodeFromTag(json.optString("version"))
                    ?: return null
            val tag = json.optString("tag").ifBlank { "apk-$code" }
            val name =
                json.optString("version_name").ifBlank {
                    json.optString("version").ifBlank { "1.0.$code" }
                }
            val url =
                json.optString("apk_url").ifBlank {
                    "https://github.com/$REPO/releases/download/$tag/mobilerun.apk"
                }
            return ReleaseInfo(code, name, tag, url)
        }
    }

    private fun fetchFromGitHubApi(): ReleaseInfo? {
        val req =
            Request.Builder()
                .url("https://api.github.com/repos/$REPO/releases?per_page=20")
                .header("Accept", "application/vnd.github+json")
                .header("User-Agent", "MobilerunSelfHosted/${BuildConfig.VERSION_NAME}")
                .get()
                .build()
        metaHttp.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) {
                Log.w(TAG, "GitHub releases HTTP ${resp.code}")
                return null
            }
            val arr = JSONArray(resp.body?.string().orEmpty())
            var best: ReleaseInfo? = null
            for (i in 0 until arr.length()) {
                val rel = arr.optJSONObject(i) ?: continue
                if (rel.optBoolean("draft", false)) continue
                val tag = rel.optString("tag_name")
                val code = parseCodeFromTag(tag) ?: continue
                val assets = rel.optJSONArray("assets") ?: continue
                var apkUrl: String? = null
                for (j in 0 until assets.length()) {
                    val a = assets.optJSONObject(j) ?: continue
                    val name = a.optString("name")
                    if (name.equals("mobilerun.apk", ignoreCase = true) ||
                        name.endsWith(".apk")
                    ) {
                        apkUrl = a.optString("browser_download_url")
                        if (name.equals("mobilerun.apk", ignoreCase = true)) break
                    }
                }
                if (apkUrl.isNullOrBlank()) {
                    apkUrl =
                        "https://github.com/$REPO/releases/download/$tag/mobilerun.apk"
                }
                val info = ReleaseInfo(code, "1.0.$code", tag, apkUrl!!)
                if (best == null || info.versionCode > best.versionCode) {
                    best = info
                }
            }
            return best
        }
    }

    private fun downloadApk(context: Context, release: ReleaseInfo): File {
        val dir = File(context.cacheDir, "updates").apply { mkdirs() }
        val out = File(dir, "mobilerun-${release.versionCode}.apk")
        if (out.exists()) out.delete()
        val req = Request.Builder().url(release.apkUrl).get().build()
        downloadHttp.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) {
                throw IllegalStateException("Download HTTP ${resp.code}")
            }
            val body = resp.body ?: throw IllegalStateException("Empty APK body")
            out.outputStream().use { sink ->
                body.byteStream().use { src -> src.copyTo(sink) }
            }
        }
        if (!out.exists() || out.length() < 10_000) {
            throw IllegalStateException("Downloaded APK looks empty")
        }
        return out
    }

    private fun ensureInstallPermission(activity: Activity): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return true
        if (activity.packageManager.canRequestPackageInstalls()) return true
        try {
            activity.startActivity(
                Intent(
                    Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                    Uri.parse("package:${activity.packageName}"),
                ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            )
        } catch (e: Exception) {
            Log.w(TAG, "open unknown-sources settings: ${e.message}")
            Toast.makeText(
                activity,
                "Enable “Install unknown apps” for Mobilerun, then retry",
                Toast.LENGTH_LONG,
            ).show()
        }
        return false
    }

    private fun launchInstaller(context: Context, apk: File) {
        val uri =
            FileProvider.getUriForFile(
                context,
                "${context.packageName}.fileprovider",
                apk,
            )
        val intent =
            Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(uri, "application/vnd.android.package-archive")
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
        context.startActivity(intent)
    }
}
