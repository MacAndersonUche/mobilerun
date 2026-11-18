package ai.mobilerun.selfhosted

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.util.Log
import com.google.gson.Gson
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import android.os.SystemClock
import java.util.UUID
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import kotlin.math.min
import kotlin.random.Random

/**
 * Outbound-only WebSocket client: prefers LAN (mDNS / QR lan_ws), falls back to cloud.
 * Never requires USB/ADB. Reconnects with exponential backoff using session_token.
 */
class BackendClient(private val context: Context) {
    private val tag = "BackendClient"
    private val client = OkHttpClient.Builder()
        .pingInterval(20, TimeUnit.SECONDS)
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.SECONDS)
        .build()

    /** LAN/emulator claim — fail fast (≤2s connect) so mobile-data phones reach AWS quickly. */
    private val claimLanClient = OkHttpClient.Builder()
        .connectTimeout(2, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.SECONDS)
        .callTimeout(4, TimeUnit.SECONDS)
        .build()

    /** AWS / execute-api claim — normal timeouts for mobile data. */
    private val claimCloudClient = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .callTimeout(20, TimeUnit.SECONDS)
        .build()

    private val gson = Gson()
    private val scope = CoroutineScope(Dispatchers.IO)
    /**
     * Fast gestures (tap/swipe/press) must NEVER wait behind get_ui_tree.
     * Heartbeats stay on [scope]; slow RPCs use [slowCommandExecutor].
     */
    private val fastCommandExecutor: ExecutorService =
        Executors.newCachedThreadPool { r ->
            Thread(r, "mr-cmd-fast").also { it.isDaemon = true }
        }
    private val slowCommandExecutor: ExecutorService =
        Executors.newFixedThreadPool(2) { r ->
            Thread(r, "mr-cmd-slow").also { it.isDaemon = true }
        }
    private val discovery = LanDiscovery(context)

    private var webSocket: WebSocket? = null
    private var deviceId: String = getOrCreateDeviceId()
    private var pairingToken: String? = null
    private var sessionToken: String? = null
    private var authToken: String? = null
    private val cognitoAuth = CognitoAuth(context)

    private var lanHttp: String? = null
    private var lanWs: String? = null
    private var cloudHttp: String? = null
    private var cloudWs: String? = null
    private var discoveredWs: String? = null
    private var discoveredHttp: String? = null

    companion object {
        val DEFAULT_CLOUD_HTTP: String = BuildConfig.DEFAULT_CLOUD_HTTP
        val DEFAULT_CLOUD_WS: String = BuildConfig.DEFAULT_CLOUD_WS

        /** Wait for register/ack before claiming Connected. */
        const val REGISTER_ACK_TIMEOUT_MS = 8_000L
        /** App-level ping; keeps API GW idle (10m) and Dynamo last_seen fresh. */
        const val HEARTBEAT_INTERVAL_MS = 30_000L
        /** Reconnect if no server pong within this window (~1 missed ping + slack). */
        const val HEARTBEAT_STALE_MS = 75_000L
        /** Proactive socket refresh before API GW 2h max / long-idle edges. */
        const val PROACTIVE_REFRESH_MS = 8 * 60_000L
        /** Soft deadline so a hung a11y call still emits an RPC error response. */
        const val COMMAND_SOFT_TIMEOUT_MS = 35_000L

        const val SECURE_FOLDER_PKG = "com.samsung.knox.securefolder"

        /** Map known HTTP API → WS API (they are separate API Gateways). */
        fun cloudWsForHttp(http: String?): String? {
            if (http.isNullOrBlank()) return null
            val base = http.trimEnd('/')
            return when {
                base.contains("68tgk4z5n6.execute-api") -> DEFAULT_CLOUD_WS
                base.contains("execute-api") -> null
                else -> null
            }
        }
    }

    private var activeRoute: String = "none"
    private var lastLatencyMs: Double? = null
    /** 0 until the server acks register/heartbeat — UI must not show Connected before that. */
    @Volatile private var lastHeartbeatAckAtMs: Long = 0L
    @Volatile private var serverAcked: Boolean = false
    private val reconnectAttempt = AtomicInteger(0)
    /** Bumped on every openSocket so stale cancel/failure callbacks cannot stomp a newer socket. */
    private val socketGeneration = AtomicInteger(0)
    private var reconnectJob: Job? = null
    private var heartbeatJob: Job? = null
    private var registerAckJob: Job? = null
    private var proactiveRefreshJob: Job? = null
    private var userDisconnected = false
    @Volatile private var connecting = false
    @Volatile private var lastOpenAtMs: Long = 0L

    private val _statusFlow = MutableStateFlow("Disconnected")
    val statusFlow: StateFlow<String> = _statusFlow

    private val _routeFlow = MutableStateFlow("Route: —")
    val routeFlow: StateFlow<String> = _routeFlow

    private val _taskFlow = MutableStateFlow("No tasks yet")
    val taskFlow: StateFlow<String> = _taskFlow

    private val _streamFlow = MutableStateFlow("idle")
    val streamFlow: StateFlow<String> = _streamFlow

    private val _pairedFlow = MutableStateFlow(false)
    val pairedFlow: StateFlow<Boolean> = _pairedFlow

    private val _pairErrorFlow = MutableStateFlow<String?>(null)
    val pairErrorFlow: StateFlow<String?> = _pairErrorFlow

    private val _pairBusyFlow = MutableStateFlow(false)
    val pairBusyFlow: StateFlow<Boolean> = _pairBusyFlow

    var onStreamPermissionNeeded: ((fps: Int, quality: Int) -> Unit)? = null

    init {
        ScreenCaptureService.frameListener = { frame ->
            sendFrame(frame)
        }
        loadPrefs()
        // Always have cloud defaults baked in
        if (cloudHttp.isNullOrBlank()) cloudHttp = DEFAULT_CLOUD_HTTP
        if (cloudWs.isNullOrBlank()) cloudWs = DEFAULT_CLOUD_WS
        _pairedFlow.value = !sessionToken.isNullOrBlank()
        discovery.addListener(object : LanDiscovery.Listener {
            override fun onServiceFound(service: LanDiscovery.Service) {
                discoveredHttp = service.httpUrl
                discoveredWs = service.wsUrl
                // Prefer switching to LAN if currently on cloud (local laptop nearby)
                if (sessionToken != null && (activeRoute == "cloud" || webSocket == null)) {
                    scope.launch { connectBest(force = activeRoute == "cloud") }
                }
            }

            override fun onError(message: String) {
                Log.w(tag, "discovery: $message")
            }
        })
        discovery.start()
        authToken = cognitoAuth.savedIdToken() ?: cognitoAuth.savedAccessToken()
        if (sessionToken != null || pairingToken != null || authToken != null) {
            scope.launch { connectBest() }
        }
    }

    fun isPaired(): Boolean = !sessionToken.isNullOrBlank()

    fun publicDeviceId(): String = deviceId

    /** True only when Dynamo would see a live authed socket (server ack + fresh pong). */
    fun isServerConnectedPublic(): Boolean = isServerConnected()

    /**
     * Called from [ConnectionService] watchdog / screen-on so the socket survives
     * MainActivity teardown, app switch, and Samsung Doze without a UI reopen.
     */
    fun ensureServerConnected(reason: String = "ensure"): Boolean {
        if (userDisconnected) return false
        if (isServerConnected() && _statusFlow.value == "Connected") {
            Log.d(tag, "ensureServerConnected($reason): already acked")
            return true
        }
        Log.i(tag, "ensureServerConnected($reason): status=${_statusFlow.value} — reconnect")
        userDisconnected = false
        scope.launch { connectBest(force = true) }
        return false
    }

    fun setCloudEndpoints(http: String, ws: String?) {
        cloudHttp = http.trimEnd('/')
        cloudWs = ws ?: cloudWsForHttp(cloudHttp) ?: DEFAULT_CLOUD_WS
        prefs().edit()
            .putString("cloud_http", cloudHttp)
            .putString("cloud_ws", cloudWs)
            .putString("backend_url", cloudHttp)
            .putString("ws_url", cloudWs)
            .apply()
    }

    fun unpair() {
        userDisconnected = true
        webSocket?.cancel()
        webSocket = null
        sessionToken = null
        pairingToken = null
        authToken = null
        secure().edit().remove("session_token").remove("device_id").remove("owner").apply()
        prefs().edit().remove("session_token").remove("pairing_token").apply()
        _pairedFlow.value = false
        _statusFlow.value = "Unpaired"
    }

    /** After Cognito / device-code login — register with JWT (no pairing QR). */
    fun setAuthToken(token: String, backendHttp: String? = null, backendWs: String? = null) {
        authToken = token
        if (backendHttp != null) {
            cloudHttp = backendHttp.trimEnd('/')
            prefs().edit().putString("cloud_http", cloudHttp)
                .putString("backend_url", cloudHttp).apply()
        }
        val resolvedWs = backendWs
            ?: cloudWsForHttp(cloudHttp)
            ?: cloudWs
            ?: DEFAULT_CLOUD_WS
        cloudWs = resolvedWs
        prefs().edit().putString("cloud_ws", resolvedWs)
            .putString("ws_url", resolvedWs).apply()
        // Prefer cloud when linking against the hosted API — do not get stuck on stale LAN.
        if (cloudHttp?.contains("execute-api") == true) {
            lanWs = null
            lanHttp = null
            discoveredWs = null
            discoveredHttp = null
        }
        userDisconnected = false
        reconnectAttempt.set(0)
        ConnectionService.start(context)
        scope.launch { connectBest(force = true) }
    }

    /** Push permission checklist to hosted UI (Devices page). */
    fun reportPermissions(mediaProjectionGranted: Boolean = false) {
        val snap = PermissionStatus.snapshot(context, mediaProjectionGranted)
        val payload = mutableMapOf<String, Any?>(
            "type" to "permission_status",
            "device_id" to deviceId,
        )
        payload.putAll(snap.toMap(mediaProjectionGranted))
        webSocket?.send(gson.toJson(payload))
    }

    fun setSessionFromDeviceCode(session: String, device: String?, owner: String?) {
        sessionToken = session
        if (device != null) {
            deviceId = device
        }
        secure().edit()
            .putString("session_token", session)
            .putString("device_id", deviceId)
            .putString("owner", owner)
            .apply()
        prefs().edit()
            .putString("user_email", owner)
            .remove("pairing_token")
            .remove("session_token")
            .apply()
        pairingToken = null
        if (cloudHttp.isNullOrBlank()) cloudHttp = DEFAULT_CLOUD_HTTP
        if (cloudWs.isNullOrBlank()) cloudWs = cloudWsForHttp(cloudHttp) ?: DEFAULT_CLOUD_WS
        prefs().edit()
            .putString("cloud_http", cloudHttp)
            .putString("cloud_ws", cloudWs)
            .apply()
        _pairedFlow.value = true
        userDisconnected = false
        reconnectAttempt.set(0)
        scope.launch { connectBest(force = true) }
    }

    fun defaultBackendHttp(): String? =
        cloudHttp ?: lanHttp ?: discoveredHttp
            ?: prefs().getString("backend_url", null)
            ?: DEFAULT_CLOUD_HTTP

    private fun prefs() = context.getSharedPreferences("mobilerun", Context.MODE_PRIVATE)
    private fun secure() = SecurePrefs.get(context)

    private fun getOrCreateDeviceId(): String {
        val s = secure()
        var id = s.getString("device_id", null) ?: prefs().getString("device_id", null)
        if (id == null) {
            id = "android_${UUID.randomUUID()}"
            s.edit().putString("device_id", id).apply()
            prefs().edit().putString("device_id", id).apply()
        }
        return id
    }

    private fun loadPrefs() {
        val p = prefs()
        val s = secure()
        pairingToken = p.getString("pairing_token", null)
        sessionToken = s.getString("session_token", null) ?: p.getString("session_token", null)
        cloudHttp = p.getString("cloud_http", null) ?: DEFAULT_CLOUD_HTTP
        cloudWs = p.getString("cloud_ws", null) ?: DEFAULT_CLOUD_WS
        val legacyBackend = p.getString("backend_url", null)
        if (legacyBackend?.contains("execute-api") == true) {
            cloudHttp = legacyBackend
        }
        cloudWs = cloudWsForHttp(cloudHttp) ?: cloudWs ?: DEFAULT_CLOUD_WS
        lanHttp = p.getString("lan_http", null)
        lanWs = p.getString("lan_ws", null)
        if (lanHttp?.contains("execute-api") == true) lanHttp = null
        if (lanWs?.contains("execute-api") == true) lanWs = null
        deviceId = s.getString("device_id", null) ?: p.getString("device_id", null) ?: deviceId
        // Migrate plaintext session into encrypted store
        if (!sessionToken.isNullOrBlank()) {
            s.edit().putString("session_token", sessionToken)
                .putString("device_id", deviceId).apply()
            p.edit().remove("session_token").apply()
        }
    }

    /**
     * QR / deep-link pairing: exchange single-use token for long-lived session_token,
     * then auto-connect over cloud (LAN mDNS remains a faster fallback when available).
     */
    fun pairFromUri(uri: Uri) {
        val token = extractPairToken(uri)
        if (token.isNullOrBlank()) {
            val msg = "No pairing token in QR/link (${uri.scheme}://${uri.host}${uri.path})"
            Log.e(tag, msg)
            _pairErrorFlow.value = msg
            prefs().edit().putString("last_pair_error", msg).apply()
            return
        }
        val cloud = uri.getQueryParameter("cloud")
            ?: uri.getQueryParameter("backend")
            ?: cloudHttp
            ?: DEFAULT_CLOUD_HTTP
        val cws = uri.getQueryParameter("cloud_ws")
            ?: uri.getQueryParameter("ws")
            ?: cloudWsForHttp(cloud)
            ?: cloudWs
            ?: DEFAULT_CLOUD_WS
        lanHttp = uri.getQueryParameter("lan")
        lanWs = uri.getQueryParameter("lan_ws")
        if (lanHttp?.contains("execute-api") == true) lanHttp = null
        if (lanWs?.contains("execute-api") == true) lanWs = null
        cloudHttp = cloud.trimEnd('/')
        cloudWs = cws
        prefs().edit()
            .putString("cloud_http", cloudHttp)
            .putString("cloud_ws", cloudWs)
            .putString("lan_http", lanHttp)
            .putString("lan_ws", lanWs)
            .apply()
        _pairBusyFlow.value = true
        _pairErrorFlow.value = null
        _statusFlow.value = "Pairing… exchanging code"
        prefs().edit().putString("last_pair_error", "").apply()
        scope.launch {
            try {
                claimPairingToken(token)
                userDisconnected = false
                reconnectAttempt.set(0)
                ConnectionService.start(context)
                _statusFlow.value = "Paired · opening WebSocket…"
                connectBest(force = true)
                if (webSocket == null) {
                    val msg = "Paired but WebSocket not connected — will retry"
                    _pairErrorFlow.value = msg
                    prefs().edit().putString("last_pair_error", msg).apply()
                }
            } catch (e: Exception) {
                Log.e(tag, "pair claim failed", e)
                val msg = e.message ?: "Pairing failed"
                _pairErrorFlow.value = msg
                _statusFlow.value = "Pairing failed"
                prefs().edit().putString("last_pair_error", msg).apply()
            } finally {
                _pairBusyFlow.value = false
            }
        }
    }

    /** Pull code from mobilerun://pair?c=…, https://…/p/CODE, /pair?token=…, or raw. */
    fun extractPairToken(uri: Uri): String? {
        uri.getQueryParameter("c")?.trim()?.takeIf { it.isNotEmpty() }?.let {
            return it.uppercase()
        }
        uri.getQueryParameter("token")?.trim()?.takeIf { it.isNotEmpty() }?.let {
            return it.uppercase()
        }
        val path = uri.path.orEmpty()
        // https://…/p/ABC12345
        val segs = path.split('/').filter { it.isNotEmpty() }
        if (segs.size >= 2 && segs[segs.size - 2].equals("p", ignoreCase = true)) {
            return segs.last().uppercase().takeIf { it.isNotEmpty() }
        }
        if (segs.size >= 2 && segs[segs.size - 2].equals("pair", ignoreCase = true)) {
            return segs.last().uppercase().takeIf { it.isNotEmpty() }
        }
        val raw = uri.toString()
        for (marker in listOf("c=", "token=", "/p/")) {
            val idx = raw.indexOf(marker, ignoreCase = true)
            if (idx >= 0) {
                val rest = raw.substring(idx + marker.length)
                val end = rest.indexOfFirst { it == '&' || it == '#' || it == ' ' || it == '?' }
                val value = if (end < 0) rest else rest.substring(0, end)
                return Uri.decode(value).trim().uppercase().takeIf { it.isNotEmpty() }
            }
        }
        // Bare short code
        val bare = raw.trim().uppercase()
        if (bare.matches(Regex("^[A-Z0-9]{6,8}$"))) return bare
        return null
    }

    fun lastPairError(): String? =
        prefs().getString("last_pair_error", null)?.takeIf { it.isNotBlank() }

    /** True for emulator/LAN hosts that are safe to try before AWS. */
    private fun isLocalClaimBase(base: String): Boolean {
        val h = base.lowercase()
        return h.contains("10.0.2.2") ||
            h.contains("127.0.0.1") ||
            h.contains("localhost") ||
            h.contains("192.168.") ||
            Regex("""://10\.\d+\.""").containsMatchIn(h) ||
            h.contains(".local")
    }

    /** True for the baked AWS API (or another execute-api). Skip TEST-NET probes. */
    private fun isCloudClaimBase(base: String): Boolean {
        val h = base.lowercase()
        if (h.contains("203.0.113.") || h.contains("198.51.100.") || h.contains("192.0.2.")) {
            return false
        }
        return h.contains("execute-api") ||
            h.trimEnd('/') == DEFAULT_CLOUD_HTTP.trimEnd('/').lowercase()
    }

    /**
     * Claim order for real phones (often mobile data, no LAN):
     * 1) local LAN only if present (≤2s connect), then
     * 2) execute-api / baked DEFAULT_CLOUD_HTTP.
     * Never block on unreachable cloud= probe hosts.
     */
    private fun claimHttpBases(): List<String> {
        val out = linkedSetOf<String>()
        lanHttp?.trimEnd('/')?.takeIf { it.isNotBlank() && isLocalClaimBase(it) }?.let { out.add(it) }
        cloudHttp?.trimEnd('/')?.takeIf { it.isNotBlank() }?.let { c ->
            if (isLocalClaimBase(c) || isCloudClaimBase(c)) out.add(c)
        }
        // Always end on baked AWS so mobile-data / code-only pairing works when
        // LAN is absent or times out in ≤2s.
        out.add(DEFAULT_CLOUD_HTTP.trimEnd('/'))
        return out.toList()
    }

    private fun claimPairingToken(token: String) {
        val bases = claimHttpBases()
        Log.i(tag, "claim bases=$bases")

        val body = gson.toJson(
            mapOf(
                "token" to token,
                "device_name" to android.os.Build.MODEL,
                "platform" to "android",
                "device_id" to deviceId,
            ),
        ).toRequestBody("application/json".toMediaType())

        var lastErr: Exception? = null
        var map: Map<String, Any?>? = null
        var usedBase: String? = null
        for (httpBase in bases) {
            val t0 = System.nanoTime()
            val http = if (isLocalClaimBase(httpBase)) claimLanClient else claimCloudClient
            try {
                val req = Request.Builder()
                    .url("$httpBase/api/auth/pair/claim")
                    .post(body)
                    .build()
                http.newCall(req).execute().use { resp ->
                    val text = resp.body?.string().orEmpty()
                    if (!resp.isSuccessful) {
                        val detail = try {
                            @Suppress("UNCHECKED_CAST")
                            (gson.fromJson(text, Map::class.java) as? Map<String, Any?>)?.get("detail")
                        } catch (_: Exception) {
                            null
                        }
                        error("Claim failed (${resp.code}): ${detail ?: text.ifBlank { resp.message }}")
                    }
                    @Suppress("UNCHECKED_CAST")
                    map = gson.fromJson(text, Map::class.java) as Map<String, Any?>
                    usedBase = httpBase
                }
                Log.i(
                    tag,
                    "claim ok via $httpBase in ${(System.nanoTime() - t0) / 1_000_000}ms",
                )
                break
            } catch (e: Exception) {
                val ms = (System.nanoTime() - t0) / 1_000_000
                Log.w(tag, "claim via $httpBase failed in ${ms}ms: ${e.message}")
                // Prefer the first network/local failure over a later "invalid token"
                // from the wrong environment (local code claimed against AWS).
                if (lastErr == null || isLocalClaimBase(httpBase)) {
                    lastErr = e
                }
            }
        }
        val claimed = map ?: throw (lastErr ?: IllegalStateException("Claim failed"))
        val httpBase = usedBase ?: DEFAULT_CLOUD_HTTP
        val session = claimed["session_token"] as? String ?: error("no session_token in claim response")
        val did = claimed["device_id"] as? String
        val owner = claimed["owner"] as? String
        // Keep emulator/local overrides (10.0.2.2 / localhost) — claim often
        // echoes prod CLOUD_BACKEND_URL which would yank the phone off the LAN.
        val localOverride = isLocalClaimBase(httpBase)
        if (!localOverride) {
            (claimed["cloud_http"] as? String)?.let { cloudHttp = it.trimEnd('/') }
            (claimed["cloud_ws"] as? String)?.let { cloudWs = it }
        }
        (claimed["access_token"] as? String)?.let { authToken = it }
        // Always fall back to baked prod endpoints after claim
        if (cloudHttp.isNullOrBlank() || !isCloudClaimBase(cloudHttp!!)) {
            cloudHttp = DEFAULT_CLOUD_HTTP
        }
        if (cloudWs.isNullOrBlank()) cloudWs = DEFAULT_CLOUD_WS
        sessionToken = session
        pairingToken = null
        if (did != null) deviceId = did
        secure().edit()
            .putString("session_token", session)
            .putString("device_id", deviceId)
            .putString("owner", owner)
            .apply()
        prefs().edit()
            .remove("pairing_token")
            .remove("session_token")
            .putString("cloud_http", cloudHttp)
            .putString("cloud_ws", cloudWs)
            .putString("user_email", owner)
            .putString("last_pair_error", "")
            .apply()
        _pairedFlow.value = true
        _pairErrorFlow.value = null
        _statusFlow.value = "Paired · connecting…"
    }

    /** Paste / type the short pairing code from Devices (no QR). */
    fun pairWithCode(rawCode: String) {
        val raw = rawCode.trim().trim('"')
        if (raw.contains("://") || raw.contains("/pair") || raw.contains("/p/")) {
            pairFromUri(Uri.parse(raw))
            return
        }
        var token = raw
        for (prefix in listOf("token=", "TOKEN=", "c=", "C=")) {
            if (token.startsWith(prefix)) token = token.removePrefix(prefix)
        }
        token = token.substringBefore('&').substringBefore('#').trim()
            .filter { it.isLetterOrDigit() }
            .uppercase()
        if (token.isBlank()) {
            val msg = "Enter the pairing code from Devices (or the full link)"
            _pairErrorFlow.value = msg
            prefs().edit().putString("last_pair_error", msg).apply()
            return
        }
        // Code alone → baked AWS API (works on mobile data with no LAN server).
        lanHttp = null
        lanWs = null
        discoveredHttp = null
        discoveredWs = null
        cloudHttp = DEFAULT_CLOUD_HTTP
        cloudWs = DEFAULT_CLOUD_WS
        prefs().edit()
            .remove("lan_http")
            .remove("lan_ws")
            .putString("cloud_http", cloudHttp)
            .putString("cloud_ws", cloudWs)
            .apply()
        pairFromUri(Uri.parse("mobilerun://pair?c=${Uri.encode(token)}"))
    }

    /** @deprecated use pairFromUri */
    fun pair(backendUrl: String, token: String, wsUrl: String? = null) {
        pairFromUri(
            Uri.parse(
                "mobilerun://pair?token=$token&backend=$backendUrl" +
                    (if (wsUrl != null) "&ws=$wsUrl" else ""),
            ),
        )
    }

    private data class Candidate(val route: String, val http: String?, val ws: String)

    private fun candidates(): List<Candidate> {
        val list = mutableListOf<Candidate>()
        // Prefer cloud when we have an execute-api backend (prod phone linking)
        val preferCloud = cloudHttp?.contains("execute-api") == true ||
            cloudWs?.contains("execute-api") == true
        if (preferCloud) {
            val ws = cloudWs ?: cloudWsForHttp(cloudHttp) ?: DEFAULT_CLOUD_WS
            list.add(Candidate("cloud", cloudHttp ?: DEFAULT_CLOUD_HTTP, ws))
        }
        discoveredWs?.let { list.add(Candidate("discovered", discoveredHttp, it)) }
        lanWs?.let { list.add(Candidate("lan", lanHttp, it)) }
        if (!preferCloud) {
            val ws = cloudWs ?: cloudWsForHttp(cloudHttp)
            if (ws != null) {
                list.add(Candidate("cloud", cloudHttp ?: DEFAULT_CLOUD_HTTP, ws))
            }
        }
        // Deduplicate by ws url
        return list.distinctBy { it.ws }
    }

    private fun isServerConnected(): Boolean =
        serverAcked &&
            webSocket != null &&
            lastHeartbeatAckAtMs > 0 &&
            System.currentTimeMillis() - lastHeartbeatAckAtMs < HEARTBEAT_STALE_MS

    private suspend fun connectBest(force: Boolean = false) {
        if (userDisconnected) return
        // Serialize connects: force=true used to barge in and cancel a socket that
        // just opened, producing an open→cancel→open storm (Socket is closed).
        if (connecting) return
        // Only skip when we have a *server-acked* live socket — local "Connected"
        // used to lie when Dynamo had no row.
        if (!force && isServerConnected() && _statusFlow.value == "Connected") return
        // Grace window after a successful open — ignore duplicate force reconnects
        if (force && lastOpenAtMs > 0 && System.currentTimeMillis() - lastOpenAtMs < 2_500) {
            Log.d(tag, "skip connectBest(force): opened ${System.currentTimeMillis() - lastOpenAtMs}ms ago")
            return
        }
        val cands = candidates()
        if (cands.isEmpty()) {
            _statusFlow.value = "No endpoints — set backend URL & sign in"
            _routeFlow.value = "Route: —"
            return
        }
        connecting = true
        _statusFlow.value = "Selecting route…"
        try {
            // Probe TCP connect latency; prefer LAN/discovered under 250ms
            data class Measured(val c: Candidate, val ms: Double?)
            val measured = cands.map { c ->
                Measured(c, probeLatencyMs(c.ws, c.http))
            }
            val preferCloud = cloudHttp?.contains("execute-api") == true
            val pick = if (preferCloud) {
                // Prod / device-code link: always prefer reachable cloud WS first
                measured.firstOrNull { it.c.route == "cloud" && it.ms != null }
                    ?: measured.firstOrNull { it.c.route == "cloud" }
                    ?: measured.filter { it.ms != null }.minByOrNull { it.ms!! }
                    ?: measured.first()
            } else {
                val lanOk = measured
                    .filter { it.c.route != "cloud" && it.ms != null && it.ms <= 250.0 }
                    .minByOrNull { it.ms!! }
                lanOk
                    ?: measured.filter { it.ms != null }.minByOrNull { it.ms!! }
                    ?: measured.firstOrNull { it.c.route != "cloud" }
                    ?: measured.first()
            }

            openSocket(pick.c, pick.ms)
        } finally {
            connecting = false
        }
    }

    private fun probeLatencyMs(wsUrl: String, httpHint: String? = null): Double? {
        return try {
            // Prefer HTTP API /api/health — WS API Gateway has no health route
            val httpProbe = when {
                !httpHint.isNullOrBlank() && httpHint.contains("execute-api") ->
                    httpHint.trimEnd('/') + "/api/health"
                wsUrl.contains("execute-api") && !cloudHttp.isNullOrBlank() ->
                    cloudHttp!!.trimEnd('/') + "/api/health"
                else ->
                    wsUrl
                        .replace("wss://", "https://")
                        .replace("ws://", "http://")
                        .substringBefore("/api/")
                        .trimEnd('/') + "/api/health"
            }
            // Also accept bare /health once deployed
            val req = Request.Builder().url(httpProbe).get().build()
            val t0 = System.nanoTime()
            client.newCall(req).execute().use { resp ->
                val ms = (System.nanoTime() - t0) / 1e6
                if (resp.isSuccessful) ms else null
            }
        } catch (e: Exception) {
            Log.d(tag, "probe failed $wsUrl: ${e.message}")
            null
        }
    }

    private fun openSocket(candidate: Candidate, latencyMs: Double?) {
        val gen = socketGeneration.incrementAndGet()
        try {
            webSocket?.cancel()
        } catch (_: Exception) {
        }
        webSocket = null
        activeRoute = candidate.route
        lastLatencyMs = latencyMs
        updateRouteUi()
        _statusFlow.value = "Connecting (${candidate.route})…"

        // Put device_id on $connect so Dynamo is keyed correctly even before register
        val wsUrl = appendConnectQuery(candidate.ws, deviceId)
        val request = Request.Builder().url(wsUrl).build()
        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            private fun isCurrent(): Boolean = socketGeneration.get() == gen

            override fun onOpen(webSocket: WebSocket, response: Response) {
                if (!isCurrent()) {
                    Log.d(tag, "ignore stale onOpen gen=$gen")
                    try {
                        webSocket.cancel()
                    } catch (_: Exception) {
                    }
                    return
                }
                Log.d(tag, "WebSocket opened via ${candidate.route} gen=$gen")
                reconnectAttempt.set(0)
                lastOpenAtMs = System.currentTimeMillis()
                // Do NOT claim Connected until the server acks register —
                // otherwise the UI lies while Dynamo has no connection row.
                serverAcked = false
                lastHeartbeatAckAtMs = 0L
                _statusFlow.value = "Registering with server…"
                _pairErrorFlow.value = null
                prefs().edit().putString("last_pair_error", "").apply()
                val snap = PermissionStatus.snapshot(context, mediaProjectionGranted = false)
                val msg = mutableMapOf<String, Any?>(
                    "device_id" to deviceId,
                    "platform" to "android",
                    "type" to "register",
                    "role" to "device",
                    "route" to candidate.route,
                    "latency_ms" to latencyMs,
                    "name" to android.os.Build.MODEL,
                    "permissions" to snap.toMap(mediaGranted = false),
                )
                val sess = sessionToken
                val pair = pairingToken
                val jwt = authToken
                when {
                    !sess.isNullOrBlank() -> msg["session_token"] = sess
                    !jwt.isNullOrBlank() -> msg["auth_token"] = jwt
                    !pair.isNullOrBlank() -> msg["token"] = pair
                }
                webSocket.send(gson.toJson(msg))
                startHeartbeat()
                armRegisterAckWatch(gen)
                // Explicit permission_status so Devices page updates immediately
                reportPermissions(mediaProjectionGranted = false)
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                if (!isCurrent()) return
                handleMessage(text)
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                if (!isCurrent()) return
                _statusFlow.value = "Disconnecting"
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                if (!isCurrent()) return
                serverAcked = false
                lastHeartbeatAckAtMs = 0L
                registerAckJob?.cancel()
                proactiveRefreshJob?.cancel()
                _statusFlow.value = "Disconnected"
                stopStreamInternal()
                scheduleReconnect()
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                if (!isCurrent()) {
                    Log.d(tag, "ignore stale onFailure gen=$gen: ${t.message}")
                    return
                }
                Log.e(tag, "WebSocket error via ${candidate.route}", t)
                serverAcked = false
                lastHeartbeatAckAtMs = 0L
                registerAckJob?.cancel()
                proactiveRefreshJob?.cancel()
                _statusFlow.value = "Error: ${t.message}"
                stopStreamInternal()
                // Single reconnect path with backoff — do not immediately openSocket
                // another candidate (that raced with cancel and caused Socket-is-closed).
                scheduleReconnect()
            }
        })
    }

    /** Only flip UI to Connected after a server ack; otherwise reconnect. */
    private fun armRegisterAckWatch(gen: Int) {
        registerAckJob?.cancel()
        registerAckJob = scope.launch {
            delay(REGISTER_ACK_TIMEOUT_MS)
            if (socketGeneration.get() != gen) return@launch
            if (serverAcked && lastHeartbeatAckAtMs > 0) return@launch
            Log.w(tag, "no server register ack within ${REGISTER_ACK_TIMEOUT_MS}ms — reconnect")
            _statusFlow.value = "No server ack — reconnecting…"
            _pairErrorFlow.value = "Socket opened but server never registered this device"
            try {
                webSocket?.cancel()
            } catch (_: Exception) {
            }
            webSocket = null
            serverAcked = false
            scheduleReconnect()
        }
    }

    private fun markServerAcked() {
        serverAcked = true
        lastHeartbeatAckAtMs = System.currentTimeMillis()
        _statusFlow.value = "Connected"
        registerAckJob?.cancel()
        ConnectionService.start(context)
        armProactiveRefresh()
    }

    /** Refresh the socket before API Gateway idle/max-connection edges. */
    private fun armProactiveRefresh() {
        proactiveRefreshJob?.cancel()
        proactiveRefreshJob = scope.launch {
            delay(PROACTIVE_REFRESH_MS)
            if (userDisconnected) return@launch
            if (!isServerConnected()) return@launch
            Log.i(tag, "proactive WS refresh after ${PROACTIVE_REFRESH_MS}ms")
            _statusFlow.value = "Refreshing connection…"
            serverAcked = false
            try {
                webSocket?.close(1000, "proactive_refresh")
            } catch (_: Exception) {
                try {
                    webSocket?.cancel()
                } catch (_: Exception) {
                }
            }
            webSocket = null
            scheduleReconnect()
        }
    }

    private fun updateRouteUi() {
        val lat = lastLatencyMs?.let { "${it.toInt()} ms" } ?: "—"
        _routeFlow.value = "Route: ${activeRoute.uppercase()} · $lat"
    }

    private fun startHeartbeat() {
        heartbeatJob?.cancel()
        // Do not pretend we have an ack — wait for heartbeat_ack / register ack.
        heartbeatJob = scope.launch {
            while (isActive && webSocket != null) {
                val t0 = System.nanoTime()
                val now = System.currentTimeMillis()
                // Force reconnect if server stopped acking (half-open socket)
                if (lastHeartbeatAckAtMs > 0 && now - lastHeartbeatAckAtMs > HEARTBEAT_STALE_MS) {
                    Log.w(tag, "heartbeat ack stale ${now - lastHeartbeatAckAtMs}ms — reconnect")
                    serverAcked = false
                    _statusFlow.value = "Connection stale — reconnecting…"
                    try {
                        webSocket?.cancel()
                    } catch (_: Exception) {
                    }
                    webSocket = null
                    scheduleReconnect()
                    break
                }
                val snap = PermissionStatus.snapshot(context, mediaProjectionGranted = false)
                val hb = mutableMapOf<String, Any?>(
                    "type" to "heartbeat",
                    "device_id" to deviceId,
                    "client_ts" to now,
                    "route" to activeRoute,
                    "latency_ms" to lastLatencyMs,
                    // Keep portal online + permission rows honest across reconnects
                    "permissions" to snap.toMap(mediaGranted = false),
                )
                sessionToken?.let { hb["session_token"] = it }
                authToken?.let { hb["auth_token"] = it }
                val sent = webSocket?.send(gson.toJson(hb)) == true
                if (!sent) {
                    serverAcked = false
                    _statusFlow.value = "Disconnected — reconnecting…"
                    scheduleReconnect()
                    break
                }
                delay(HEARTBEAT_INTERVAL_MS)
                if (lastLatencyMs != null) {
                    webSocket?.send(
                        gson.toJson(
                            mapOf(
                                "type" to "connection_status",
                                "device_id" to deviceId,
                                "route" to activeRoute,
                                "latency_ms" to lastLatencyMs,
                            ),
                        ),
                    )
                }
                Log.v(tag, "heartbeat tick ${(System.nanoTime() - t0) / 1e6}")
            }
        }
    }

    private fun scheduleReconnect() {
        if (userDisconnected) return
        reconnectJob?.cancel()
        reconnectJob = scope.launch {
            val attempt = reconnectAttempt.getAndIncrement()
            // Fast recovery, but never sub-second — that races OkHttp cancel/open.
            val base = min(15.0, 1.2 * Math.pow(2.0, attempt.toDouble()))
            val jitter = base * 0.25
            val delaySec = (base + Random.nextDouble(-jitter, jitter)).coerceAtLeast(1.2)
            _statusFlow.value = "Reconnecting in ${"%.1f".format(delaySec)}s…"
            delay((delaySec * 1000).toLong())
            connectBest(force = true)
        }
    }

    private fun handleMessage(text: String) {
        try {
            @Suppress("UNCHECKED_CAST")
            val message = gson.fromJson(text, Map::class.java) as Map<String, Any?>
            when (message["type"] as? String ?: message["status"] as? String) {
                "connected", "ack", null -> {
                    if (
                        message["status"] == "connected" ||
                        message["type"] == "ack" ||
                        message["session_token"] != null
                    ) {
                        (message["session_token"] as? String)?.let {
                            sessionToken = it
                            prefs().edit().putString("session_token", it)
                                .remove("pairing_token").apply()
                            pairingToken = null
                        }
                        (message["device_id"] as? String)?.let {
                            deviceId = it
                            prefs().edit().putString("device_id", it).apply()
                        }
                        (message["route"] as? String)?.let { activeRoute = it }
                        (message["latency_ms"] as? Number)?.let {
                            lastLatencyMs = it.toDouble()
                        }
                        updateRouteUi()
                        markServerAcked()
                        reportPermissions(
                            ScreenCaptureService.instance != null,
                        )
                    }
                }
                "heartbeat_ack" -> {
                    lastLatencyMs = lastLatencyMs ?: 20.0
                    markServerAcked()
                    updateRouteUi()
                }
                "command" -> handleCommand(message)
                "stream_control" -> handleStreamControl(message)
                "run_task" -> {
                    // Legacy: cloud agent owns multi-step work via `command` RPC.
                    val instruction = message["instruction"] as? String ?: "Unknown"
                    val taskId = message["task_id"] as? String ?: ""
                    _taskFlow.value = "Cloud agent: $instruction"
                    scope.launch {
                        sendAgentEvent(null, 0, "run_task_ack", "cloud_agent_owns:$instruction")
                        if (taskId.isNotBlank()) {
                            sendTaskUpdate(taskId, "running", "Waiting for cloud agent steps")
                        }
                    }
                }
                "agent_control" -> {
                    val action = message["action"] as? String ?: ""
                    val instruction = message["instruction"] as? String ?: ""
                    val step = (message["step"] as? Number)?.toInt()
                    val dry = message["dry_run"] == true ||
                        instruction.contains("[DRY RUN]", ignoreCase = true)
                    val dryTag = if (dry) "[DRY RUN] " else ""
                    _taskFlow.value = when {
                        action == "start" -> "${dryTag}Cloud agent starting…"
                        step != null -> "${dryTag}Cloud step $step"
                        else -> dryTag + action.ifBlank { "agent" }
                    }
                    sendAgentEvent(null, step, action, instruction)
                }
                "task_control" -> {
                    val action = message["action"] as? String
                    if (action == "pause" || action == "stop") {
                        _taskFlow.value = "Task $action"
                        sendAgentEvent(null, null, action, "UI requested $action")
                    }
                }
                "push_notification" -> {
                    val title = message["title"] as? String ?: "Needs you"
                    val body = message["body"] as? String ?: ""
                    val badge = (message["badge"] as? Number)?.toInt() ?: 0
                    _taskFlow.value = "$title ($badge): $body"
                    // System notification when POST_NOTIFICATIONS granted
                    try {
                        val nm = context.getSystemService(Context.NOTIFICATION_SERVICE)
                            as android.app.NotificationManager
                        val channelId = "needs_you"
                        if (android.os.Build.VERSION.SDK_INT >= 26) {
                            nm.createNotificationChannel(
                                android.app.NotificationChannel(
                                    channelId,
                                    "Needs you",
                                    android.app.NotificationManager.IMPORTANCE_HIGH,
                                ),
                            )
                        }
                        val notif = android.app.Notification.Builder(context, channelId)
                            .setContentTitle(title)
                            .setContentText(body)
                            .setSmallIcon(R.drawable.ic_stat_mobilerun)
                            .setAutoCancel(true)
                            .build()
                        nm.notify(9001, notif)
                    } catch (e: Exception) {
                        Log.w(tag, "push_notification: ${e.message}")
                    }
                }
            }
            if (message["error"] != null) {
                _statusFlow.value = "Auth error: ${message["error"]}"
            }
        } catch (e: Exception) {
            Log.e(tag, "Failed to handle message", e)
        }
    }

    private fun handleStreamControl(message: Map<String, Any?>) {
        val action = message["action"] as? String ?: return
        val fps = (message["fps"] as? Number)?.toInt() ?: 3
        val quality = (message["quality"] as? Number)?.toInt() ?: 45
        when (action) {
            "start" -> {
                // Reuse active MediaProjection — Android 14+ consent is one-shot per grant
                if (ScreenCaptureService.isStreaming()) {
                    ScreenCaptureService.updateParams(fps, quality)
                    _streamFlow.value = "streaming"
                    sendAgentEvent(null, null, "stream_resume", "Live view resumed (consent reused)")
                    return
                }
                _streamFlow.value = "starting"
                onStreamPermissionNeeded?.invoke(fps, quality)
                    ?: Log.w(tag, "No permission callback registered for stream start")
            }
            "stop" -> stopStreamInternal()
        }
    }

    fun startCaptureWithPermission(resultCode: Int, data: Intent, fps: Int, quality: Int) {
        // Persist grant extras so a later stream_control can restart without UI if process alive
        prefs().edit()
            .putBoolean("media_projection_granted", true)
            .apply()
        val intent = Intent(context, ScreenCaptureService::class.java).apply {
            action = ScreenCaptureService.ACTION_START
            putExtra(ScreenCaptureService.EXTRA_RESULT_CODE, resultCode)
            putExtra(ScreenCaptureService.EXTRA_RESULT_DATA, data)
            putExtra(ScreenCaptureService.EXTRA_FPS, fps)
            putExtra(ScreenCaptureService.EXTRA_QUALITY, quality)
        }
        context.startForegroundService(intent)
        _streamFlow.value = "streaming"
        sendAgentEvent(null, null, "stream_start", "Live view streaming at ${fps}fps")
    }

    private fun stopStreamInternal() {
        val intent = Intent(context, ScreenCaptureService::class.java).apply {
            action = ScreenCaptureService.ACTION_STOP
        }
        context.startService(intent)
        _streamFlow.value = "idle"
    }

    private fun sendFrame(frame: ScreenCaptureService.Companion.FramePayload) {
        val msg = mapOf(
            "type" to "frame",
            "device_id" to deviceId,
            "mime" to frame.mime,
            "width" to frame.width,
            "height" to frame.height,
            "seq" to frame.seq,
            "ts" to frame.ts,
            "data" to frame.dataBase64,
        )
        webSocket?.send(gson.toJson(msg))
    }

    fun sendAgentEvent(currentApp: String?, step: Int?, action: String?, log: String?) {
        val msg = mutableMapOf<String, Any?>(
            "type" to "agent_event",
            "device_id" to deviceId,
        )
        if (currentApp != null) msg["current_app"] = currentApp
        if (step != null) msg["step"] = step
        if (action != null) msg["action"] = action
        if (log != null) msg["log"] = log
        webSocket?.send(gson.toJson(msg))
    }

    private fun appendConnectQuery(ws: String, did: String): String {
        return try {
            val b = Uri.parse(ws).buildUpon()
            b.appendQueryParameter("device_id", did)
            b.appendQueryParameter("role", "device")
            b.appendQueryParameter("platform", "android")
            b.build().toString()
        } catch (_: Exception) {
            val sep = if (ws.contains("?")) "&" else "?"
            "$ws${sep}device_id=${Uri.encode(did)}&role=device&platform=android"
        }
    }

    private fun handleCommand(message: Map<String, Any?>) {
        val command = message["command"] as? String ?: return
        val requestId = message["request_id"] as? String ?: return
        @Suppress("UNCHECKED_CAST")
        val params = message["params"] as? Map<String, Any?>
        val t0 = SystemClock.elapsedRealtime()

        // CRITICAL: ACK tap/swipe/press on the OkHttp reader thread BEFORE any
        // executor queue. Fresh heartbeats + timed-out taps meant hung get_ui_tree
        // starved the single command pool while Dynamo still looked online.
        when (command) {
            "tap" -> {
                val x = (params?.get("x") as? Number)?.toInt() ?: 0
                val y = (params?.get("y") as? Number)?.toInt() ?: 0
                val humanize = params?.get("humanize") as? Boolean ?: true
                val a11y = MobilerunAccessibilityService.instance
                if (a11y == null) {
                    sendCommandResponse(requestId, null, "Accessibility service not connected")
                    return
                }
                sendCommandResponse(
                    requestId,
                    mapOf(
                        "ok" to true,
                        "acked" to true,
                        "x" to x,
                        "y" to y,
                        "humanize" to humanize,
                        "timing" to mapOf("ack_ms" to (SystemClock.elapsedRealtime() - t0)),
                    ),
                    null,
                )
                fastCommandExecutor.execute {
                    try {
                        a11y.tapFireAndForget(x, y, humanize)
                        sendAgentEvent(null, null, "tap", "tap($x,$y)")
                    } catch (e: Exception) {
                        Log.w(tag, "tap gesture after ACK failed: ${e.message}")
                    }
                }
                return
            }
            "swipe" -> {
                val x1 = (params?.get("x1") as? Number)?.toInt() ?: 0
                val y1 = (params?.get("y1") as? Number)?.toInt() ?: 0
                val x2 = (params?.get("x2") as? Number)?.toInt() ?: 0
                val y2 = (params?.get("y2") as? Number)?.toInt() ?: 0
                val duration = (params?.get("duration_ms") as? Number)?.toLong() ?: 300
                val a11y = MobilerunAccessibilityService.instance
                if (a11y == null) {
                    sendCommandResponse(requestId, null, "Accessibility service not connected")
                    return
                }
                sendCommandResponse(
                    requestId,
                    mapOf(
                        "ok" to true,
                        "acked" to true,
                        "timing" to mapOf("ack_ms" to (SystemClock.elapsedRealtime() - t0)),
                    ),
                    null,
                )
                fastCommandExecutor.execute {
                    try {
                        a11y.swipeFireAndForget(x1, y1, x2, y2, duration)
                        sendAgentEvent(null, null, "swipe", "swipe($x1,$y1->$x2,$y2)")
                    } catch (e: Exception) {
                        Log.w(tag, "swipe gesture after ACK failed: ${e.message}")
                    }
                }
                return
            }
            "press_button" -> {
                val button = params?.get("button") as? String
                val a11y = MobilerunAccessibilityService.instance
                if (a11y == null) {
                    sendCommandResponse(requestId, null, "Accessibility service not connected")
                    return
                }
                val ok = when (button) {
                    "back" -> a11y.pressBack()
                    "home" -> a11y.pressHome()
                    "recents" -> a11y.pressRecents()
                    else -> false
                }
                sendCommandResponse(
                    requestId,
                    mapOf(
                        "ok" to ok,
                        "timing" to mapOf("ack_ms" to (SystemClock.elapsedRealtime() - t0)),
                    ),
                    null,
                )
                return
            }
        }

        // Slow path: tree / type / open_app / screenshot — never blocks tap ACK
        slowCommandExecutor.execute {
            val done = java.util.concurrent.atomic.AtomicBoolean(false)
            val watchdog = scope.launch {
                delay(COMMAND_SOFT_TIMEOUT_MS)
                if (done.compareAndSet(false, true)) {
                    Log.e(tag, "command soft-timeout $command rid=$requestId")
                    sendCommandResponse(
                        requestId,
                        null,
                        "Command $command soft-timeout after ${COMMAND_SOFT_TIMEOUT_MS}ms",
                    )
                }
            }
            try {
                // open_app uses PackageManager — must work even if a11y unbound
                val a11yService = MobilerunAccessibilityService.instance
                val needsA11y = command !in setOf(
                    "open_app",
                    "start_app",
                    "get_device_info",
                    "get_ui_tree",
                    "screenshot",
                    "dismiss_anr",
                    "dismiss_dialogs",
                    "rebind_a11y",
                    "ensure_ime",
                    "switch_ime",
                    "restore_ime",
                    "get_focused_input",
                    "focused_input",
                )
                if (needsA11y && a11yService == null) {
                    throw Exception("Accessibility service not connected")
                }

                val result: Any = when (command) {
                    "input_text", "type_text" -> {
                        val text = params?.get("text") as? String ?: ""
                        val clear = params?.get("clear") as? Boolean ?: false
                        val humanize = params?.get("humanize") as? Boolean ?: true
                        // Portal order: Mobilerun Keyboard IME first, then a11y SET_TEXT.
                        // Prefer our own keyboard; fall back to a11y SET_TEXT.
                        ai.mobilerun.selfhosted.input.ImeSessionController.ensureSelected(context)
                        val focus = ai.mobilerun.selfhosted.input.MobilerunKeyboardIME
                            .getInstance()?.focusedFieldInfo()
                            ?: a11yService?.focusedEditableMeta().orEmpty()
                        val via = when (
                            ai.mobilerun.selfhosted.input.MobilerunKeyboardIME.tryAutomationInput(
                                context,
                                text,
                                clear,
                                humanize,
                            )
                        ) {
                            ai.mobilerun.selfhosted.input.AutomationInput.DONE -> "ime"
                            ai.mobilerun.selfhosted.input.AutomationInput.STUCK ->
                                throw Exception(
                                    "input_text via IME accepted but unverified — " +
                                        "enable Mobilerun Keyboard or focus the field",
                                )
                            ai.mobilerun.selfhosted.input.AutomationInput.FALLBACK -> {
                                val ok = a11yService!!.inputText(text, clear, humanize)
                                if (!ok) {
                                    throw Exception("input_text failed — focus a text field")
                                }
                                "a11y"
                            }
                        }
                        sendAgentEvent(null, null, "type", "type(${text.take(40)}) via=$via")
                        mapOf(
                            "ok" to true,
                            "acked" to true,
                            "via" to via,
                            "humanize" to humanize,
                            "chars" to text.length,
                            "focus" to focus,
                            "timing" to mapOf(
                                "ack_ms" to (SystemClock.elapsedRealtime() - t0),
                            ),
                        )
                    }
                    "ensure_ime", "switch_ime" -> {
                        val r = ai.mobilerun.selfhosted.input.ImeSessionController
                            .ensureSelected(context)
                        if (r["needs_user"] == true) {
                            PermissionStatus.openInputMethodSettings(context)
                        }
                        sendAgentEvent(null, null, "ime", "ensure_ime selected=${r["selected"]}")
                        r + mapOf(
                            "timing" to mapOf(
                                "ack_ms" to (SystemClock.elapsedRealtime() - t0),
                            ),
                        )
                    }
                    "restore_ime" -> {
                        val r = ai.mobilerun.selfhosted.input.ImeSessionController.restore(context)
                        sendAgentEvent(null, null, "ime", "restore_ime ok=${r["ok"]}")
                        r + mapOf(
                            "timing" to mapOf(
                                "ack_ms" to (SystemClock.elapsedRealtime() - t0),
                            ),
                        )
                    }
                    "ime_action", "keyboard_action" -> {
                        val actionName = (params?.get("action") as? String) ?: "send"
                        val ime = ai.mobilerun.selfhosted.input.MobilerunKeyboardIME.getInstance()
                        val focus = ime?.focusedFieldInfo()
                            ?: a11yService?.focusedEditableMeta().orEmpty()
                        val ok = if (ime != null && ime.hasInputConnection()) {
                            ime.performImeAction(actionName)
                        } else {
                            false
                        }
                        if (!ok && actionName.equals("send", ignoreCase = true)) {
                            // Fall back to tapping known send ids via a11y tree
                            val tree = a11yService?.getUITree().orEmpty()
                            val sendHit = Regex(
                                """i="[^"]*(?:id/)?send[^"]*"[^>]*\bxy="(\d+),(\d+)"""",
                                RegexOption.IGNORE_CASE,
                            ).find(tree)
                            if (sendHit != null) {
                                val x = sendHit.groupValues[1].toInt()
                                val y = sendHit.groupValues[2].toInt()
                                GestureController.tap(x, y, humanize = false)
                            } else {
                                throw Exception("ime_action=$actionName failed — no IME connection")
                            }
                        }
                        sendAgentEvent(null, null, "ime_action", "ime_action($actionName)")
                        mapOf(
                            "ok" to true,
                            "action" to actionName,
                            "via" to if (ok) "ime" else "tap_send",
                            "focus" to focus,
                            "timing" to mapOf(
                                "ack_ms" to (SystemClock.elapsedRealtime() - t0),
                            ),
                        )
                    }
                    "get_focused_input", "focused_input" -> {
                        val ime = ai.mobilerun.selfhosted.input.MobilerunKeyboardIME.getInstance()
                        val focus = ime?.focusedFieldInfo()
                            ?: a11yService?.focusedEditableMeta()
                            ?: mapOf("ok" to false)
                        focus + mapOf(
                            "ime_selected" to
                                ai.mobilerun.selfhosted.input.MobilerunKeyboardIME.isSelected(context),
                            "ime_available" to
                                ai.mobilerun.selfhosted.input.MobilerunKeyboardIME.isAvailable(),
                            "timing" to mapOf(
                                "ack_ms" to (SystemClock.elapsedRealtime() - t0),
                            ),
                        )
                    }
                    "dismiss_anr", "dismiss_dialogs" -> {
                        val dismissed = a11yService?.dismissBlockingDialogs(
                            anrOnly = command == "dismiss_anr",
                        ) == true
                        mapOf(
                            "ok" to true,
                            "dismissed" to dismissed,
                            "timing" to mapOf(
                                "ack_ms" to (SystemClock.elapsedRealtime() - t0),
                            ),
                        )
                    }
                    "rebind_a11y" -> {
                        val ok = PermissionStatus.tryRecoverAccessibilityBinding(context)
                        mapOf(
                            "ok" to ok,
                            "bound" to PermissionStatus.isAccessibilityBound(),
                            "timing" to mapOf(
                                "ack_ms" to (SystemClock.elapsedRealtime() - t0),
                            ),
                        )
                    }
                    "open_app", "start_app" -> {
                        val app = (params?.get("app") as? String)
                            ?: (params?.get("package") as? String)
                            ?: ""
                        val pkg = params?.get("package") as? String
                        var launched = openAppByNameOrPackage(app, pkg)
                        var viaSecureFolder = false
                        var secureFolderWaitMs = 0L
                        if (launched == null) {
                            val sf = openAppViaSecureFolder(app, pkg)
                            launched = sf.packageName
                            viaSecureFolder = sf.openedSecureFolder
                            secureFolderWaitMs = sf.waitMs
                            if (sf.needsFingerprint) {
                                sendAgentEvent(
                                    null,
                                    null,
                                    "secure_folder_unlock",
                                    "Unlock Secure Folder with fingerprint to open $app",
                                )
                            }
                        }
                        sendAgentEvent(null, null, "open_app", "open_app($app)")
                        if (launched == null) {
                            throw Exception(
                                "Could not open app: $app" +
                                    if (secureFolderInstalled()) {
                                        " (not in main profile; Secure Folder unlock failed or timed out)"
                                    } else {
                                        ""
                                    },
                            )
                        }
                        // Brief settle — keep agent steps under the 3–5s budget
                        val settle = 280L + kotlin.random.Random.nextLong(0, 180)
                        Thread.sleep(settle)
                        val activePkg = a11yService?.activePackageName().orEmpty()
                        mapOf(
                            "ok" to true,
                            "requested" to app,
                            "package" to launched,
                            "active_package" to activePkg,
                            "launched" to true,
                            "secure_folder" to viaSecureFolder,
                            "secure_folder_wait_ms" to secureFolderWaitMs,
                            "a11y" to (a11yService != null),
                            // Main-profile a11y often cannot see Secure Folder (user 150)
                            "a11y_cross_user_limited" to viaSecureFolder,
                            "timing" to mapOf(
                                "ack_ms" to (SystemClock.elapsedRealtime() - t0),
                            ),
                        )
                    }
                    "get_ui_tree" -> {
                        if (a11yService == null) {
                            mapOf(
                                "tree" to """<hierarchy windows="0" nodes="0" empty="true" reason="a11y_unbound"/>""",
                                "package" to "",
                                "empty" to true,
                                "chars" to 0,
                                "a11y" to false,
                                "timing" to mapOf(
                                    "build_ms" to 0,
                                    "round_trip_ms" to (SystemClock.elapsedRealtime() - t0),
                                    "bytes" to 0,
                                    "cached" to false,
                                    "partial" to true,
                                ),
                            )
                        } else {
                            var detailed = a11yService.getUITreeDetailed(allowCache = true)
                            // One forced rebuild if empty — covers post-reconnect a11y blips
                            if (detailed.empty) {
                                Thread.sleep(120)
                                detailed = a11yService.getUITreeDetailed(allowCache = false)
                            }
                            val tree = detailed.tree
                            val out = mutableMapOf<String, Any?>(
                                "tree" to tree,
                                "package" to detailed.packageName.ifBlank {
                                    a11yService.activePackageName().orEmpty()
                                },
                                "empty" to detailed.empty,
                                "chars" to detailed.chars,
                                "nodes" to detailed.nodes,
                                "a11y" to true,
                                "truncated" to detailed.partial,
                                "partial" to detailed.partial,
                                "anr_dismissed" to detailed.anrDismissed,
                                "timing" to mapOf(
                                    "build_ms" to detailed.buildMs,
                                    "bytes" to detailed.bytes,
                                    "nodes" to detailed.nodes,
                                    "cached" to detailed.cached,
                                    "partial" to detailed.partial,
                                    "round_trip_ms" to (SystemClock.elapsedRealtime() - t0),
                                ),
                            )
                            if (!detailed.treeGzB64.isNullOrBlank()) {
                                out["tree_gz"] = detailed.treeGzB64
                                out["encoding"] = "gzip+base64"
                            }
                            out
                        }
                    }
                    "screenshot" -> {
                        val b64 = a11yService?.takeScreenshotJpegBase64(
                            maxWidth = 720,
                            quality = 42,
                        )
                        if (b64.isNullOrBlank()) {
                            mapOf(
                                "ok" to false,
                                "error" to "screenshot unavailable",
                                "a11y" to (a11yService != null),
                            )
                        } else {
                            mapOf(
                                "ok" to true,
                                "mime" to "image/jpeg",
                                "encoding" to "base64",
                                "data" to b64,
                                "timing" to mapOf(
                                    "round_trip_ms" to (SystemClock.elapsedRealtime() - t0),
                                ),
                            )
                        }
                    }
                    "get_device_info" -> {
                        mapOf(
                            "device_id" to deviceId,
                            "platform" to "android",
                            "stream" to _streamFlow.value,
                            "route" to activeRoute,
                            "latency_ms" to lastLatencyMs,
                            "active_package" to a11yService?.activePackageName(),
                            "a11y" to (a11yService != null),
                        )
                    }
                    else -> throw Exception("Unknown command: $command")
                }

                if (done.compareAndSet(false, true)) {
                    watchdog.cancel()
                    sendCommandResponse(requestId, result, null)
                }
            } catch (e: Exception) {
                if (done.compareAndSet(false, true)) {
                    watchdog.cancel()
                    sendCommandResponse(requestId, null, e.message ?: "Unknown error")
                }
            }
        }
    }

    private fun sendCommandResponse(requestId: String, result: Any?, error: String?) {
        val response = mutableMapOf<String, Any?>(
            "type" to "response",
            "request_id" to requestId,
        )
        if (error != null) {
            response["error"] = error
        } else {
            // Shrink oversized tree payloads so send() is not silently dropped
            val safe: Any? = when (result) {
                is Map<*, *> -> {
                    val tree = result["tree"]
                    if (tree is String && tree.length > 24_000) {
                        @Suppress("UNCHECKED_CAST")
                        val m = (result as Map<String, Any?>).toMutableMap()
                        // Prefer gzip-only when plain is still large
                        if (m["tree_gz"] != null) {
                            m["tree"] = """<hierarchy empty="false" reason="see_tree_gz" chars="${tree.length}"/>"""
                        } else {
                            m["tree"] = tree.take(18_000) + "\n<!-- force_truncated -->\n"
                        }
                        m["truncated"] = true
                        m["chars"] = (m["tree"] as String).length
                        m
                    } else {
                        result
                    }
                }
                else -> result
            }
            response["result"] = safe
        }
        val json = gson.toJson(response)
        if (json.length > 110_000) {
            Log.w(tag, "response $requestId too large (${json.length}); sending error stub")
            val stub = gson.toJson(
                mapOf(
                    "type" to "response",
                    "request_id" to requestId,
                    "result" to mapOf(
                        "tree" to """<hierarchy empty="true" reason="payload_too_large" chars="${json.length}"/>""",
                        "empty" to true,
                        "chars" to 0,
                        "package" to ((result as? Map<*, *>)?.get("package") ?: ""),
                        "a11y" to true,
                    ),
                ),
            )
            val ok = webSocket?.send(stub) == true
            if (!ok) Log.e(tag, "failed to send truncated response $requestId")
            return
        }
        val ok = webSocket?.send(json) == true
        if (!ok) {
            Log.e(tag, "webSocket.send failed for response $requestId (len=${json.length})")
        }
    }

    private fun sendTaskUpdate(taskId: String, status: String, result: String) {
        if (taskId.isBlank()) return
        val msg = mapOf(
            "type" to "task_update",
            "task_id" to taskId,
            "device_id" to deviceId,
            "update" to mapOf(
                "status" to status,
                "result" to result,
                "completed_at" to System.currentTimeMillis(),
            ),
        )
        webSocket?.send(gson.toJson(msg))
    }

    /**
     * Launch a UI activity from the FGS/WebSocket path. Android 14+ blocks
     * background starts (BAL); try move-to-front, ActivityOptions BAL allow,
     * then a full-screen notification trampoline.
     */
    private fun startUiActivity(intent: Intent): Boolean {
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        // Prefer move-to-front + PendingIntent BAL allow — we no longer request overlay
        try {
            val am = context.getSystemService(Context.ACTIVITY_SERVICE) as android.app.ActivityManager
            am.appTasks.firstOrNull()?.moveToFront()
        } catch (_: Exception) {
        }
        try {
            if (android.os.Build.VERSION.SDK_INT >= 34) {
                val opts = android.app.ActivityOptions.makeBasic()
                opts.setPendingIntentCreatorBackgroundActivityStartMode(
                    android.app.ActivityOptions.MODE_BACKGROUND_ACTIVITY_START_ALLOWED,
                )
                // Options must be attached at PendingIntent *creation* time
                val pi = android.app.PendingIntent.getActivity(
                    context,
                    (System.currentTimeMillis() % Int.MAX_VALUE).toInt(),
                    intent,
                    android.app.PendingIntent.FLAG_UPDATE_CURRENT or
                        android.app.PendingIntent.FLAG_IMMUTABLE,
                    opts.toBundle(),
                )
                pi.send()
                return true
            }
            context.startActivity(intent)
            return true
        } catch (e: Exception) {
            Log.w(tag, "startUiActivity direct failed: ${e.message}")
        }
        return try {
            context.startActivity(intent)
            true
        } catch (e: Exception) {
            try {
                val pi = android.app.PendingIntent.getActivity(
                    context,
                    9101,
                    intent,
                    android.app.PendingIntent.FLAG_UPDATE_CURRENT or
                        android.app.PendingIntent.FLAG_IMMUTABLE,
                )
                val nm = context.getSystemService(Context.NOTIFICATION_SERVICE)
                    as android.app.NotificationManager
                val channelId = "task_launch"
                if (android.os.Build.VERSION.SDK_INT >= 26) {
                    nm.createNotificationChannel(
                        android.app.NotificationChannel(
                            channelId,
                            "Task launch",
                            android.app.NotificationManager.IMPORTANCE_HIGH,
                        ),
                    )
                }
                val notif = android.app.Notification.Builder(context, channelId)
                    .setContentTitle("MobileRun")
                    .setContentText("Opening requested screen…")
                    .setSmallIcon(R.drawable.ic_stat_mobilerun)
                    .setContentIntent(pi)
                    .setFullScreenIntent(pi, true)
                    .setAutoCancel(true)
                    .build()
                nm.notify(9101, notif)
                true
            } catch (e2: Exception) {
                Log.e(tag, "startUiActivity failed", e2)
                false
            }
        }
    }

    /**
     * Launch via PackageManager.getLaunchIntentForPackage — never by hunting
     * launcher icons. Returns the package that was launched, or null.
     */
    private data class SecureFolderLaunch(
        val packageName: String?,
        val openedSecureFolder: Boolean,
        val needsFingerprint: Boolean,
        val waitMs: Long,
    )

    private fun secureFolderInstalled(): Boolean {
        return try {
            context.packageManager.getPackageInfo(SECURE_FOLDER_PKG, 0)
            true
        } catch (_: Exception) {
            false
        }
    }

    /**
     * Samsung Secure Folder (Knox user ~150): apps like WhatsApp may live only there.
     * Open Secure Folder, wait up to ~60s for fingerprint unlock, then try the app
     * again / tap its icon. Main-profile Accessibility often cannot see Folder windows
     * — callers should fall back to screenshot+vision when a11y_cross_user_limited.
     */
    private fun openAppViaSecureFolder(app: String, pkg: String?): SecureFolderLaunch {
        if (!secureFolderInstalled()) {
            return SecureFolderLaunch(null, false, false, 0)
        }
        val launchSf = context.packageManager.getLaunchIntentForPackage(SECURE_FOLDER_PKG)
            ?: Intent().setClassName(
                SECURE_FOLDER_PKG,
                "com.samsung.knox.securefolder.presentation.switcher.SwitcherActivity",
            ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (!startUiActivity(launchSf)) {
            Log.w(tag, "Secure Folder present but could not launch")
            return SecureFolderLaunch(null, true, false, 0)
        }
        sendAgentEvent(
            null,
            null,
            "secure_folder",
            "Opened Secure Folder — confirm fingerprint if prompted",
        )
        val a11y = MobilerunAccessibilityService.instance
        val t0 = SystemClock.elapsedRealtime()
        var needsFp = false
        // Cap well under open_app RPC timeout (45s) so we still ACK
        val deadline = t0 + 28_000L
        var unlocked = false
        while (SystemClock.elapsedRealtime() < deadline) {
            Thread.sleep(900)
            val tree = try {
                a11y?.getUITree().orEmpty()
            } catch (_: Exception) {
                ""
            }
            val low = tree.lowercase()
            val active = a11y?.activePackageName().orEmpty()
            if (
                low.contains("fingerprint") ||
                low.contains("confirm pattern") ||
                low.contains("confirm pin") ||
                low.contains("use biometrics") ||
                low.contains("authenticate")
            ) {
                needsFp = true
                continue
            }
            // Folder home / app grid likely unlocked
            if (
                active == SECURE_FOLDER_PKG ||
                low.contains("secure folder") ||
                low.contains("whatsapp") ||
                low.contains("instagram") ||
                low.contains("tinder") ||
                low.contains("bumble") ||
                low.contains("hinge") ||
                low.contains("telegram") ||
                low.contains("messenger")
            ) {
                // Prefer tapping the requested app icon inside the Folder UI
                val label = app.trim().removePrefix("open ").trim()
                if (label.isNotBlank() && a11y != null) {
                    val tapped = try {
                        a11y.tapByVisibleText(label, fuzzy = true)
                    } catch (_: Exception) {
                        false
                    }
                    if (tapped) {
                        Thread.sleep(700)
                        unlocked = true
                        break
                    }
                }
                // Retry PackageManager launch — some OEMs resolve after Folder unlock
                val again = openAppByNameOrPackage(app, pkg)
                if (again != null) {
                    return SecureFolderLaunch(
                        again,
                        true,
                        needsFp,
                        SystemClock.elapsedRealtime() - t0,
                    )
                }
                unlocked = true
                break
            }
        }
        val wait = SystemClock.elapsedRealtime() - t0
        if (!unlocked) {
            return SecureFolderLaunch(null, true, needsFp || wait > 2_000, wait)
        }
        val resolved = resolvePackageName(
            app.trim().lowercase().removePrefix("open ").trim(),
            pkg,
        ) ?: pkg?.takeIf { it.contains('.') } ?: app
        return SecureFolderLaunch(resolved, true, needsFp, wait)
    }

    private fun openAppByNameOrPackage(app: String, pkg: String?): String? {
        val name = app.trim()
        val lower = name.lowercase().removePrefix("open ").trim()
        val pm = context.packageManager

        // Explicit system Settings intents (more reliable than package on OEM skins)
        if (lower == "settings" || lower.contains("setting") || pkg == "com.android.settings") {
            if (startUiActivity(Intent(android.provider.Settings.ACTION_SETTINGS))) {
                return "com.android.settings"
            }
        }
        if (lower.contains("wifi") || lower.contains("wi-fi")) {
            if (startUiActivity(Intent(android.provider.Settings.ACTION_WIFI_SETTINGS))) {
                return "com.android.settings"
            }
        }

        val resolved = resolvePackageName(lower, pkg) ?: return null
        val launch = pm.getLaunchIntentForPackage(resolved)
            ?: Intent(Intent.ACTION_MAIN).apply {
                addCategory(Intent.CATEGORY_LAUNCHER)
                setPackage(resolved)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
        return if (startUiActivity(launch)) resolved else null
    }

    /** Map friendly labels / known aliases → installed package name. */
    private fun resolvePackageName(lower: String, pkg: String?): String? {
        pkg?.takeIf { it.contains('.') }?.let { candidate ->
            return try {
                context.packageManager.getPackageInfo(candidate, 0)
                candidate
            } catch (_: Exception) {
                null
            }
        }
        val aliases = mapOf(
            "settings" to "com.android.settings",
            "chrome" to "com.android.chrome",
            "gmail" to "com.google.android.gm",
            "maps" to "com.google.android.apps.maps",
            "youtube" to "com.google.android.youtube",
            "camera" to "com.android.camera",
            "whatsapp" to "com.whatsapp",
            "wa" to "com.whatsapp",
            "snapchat" to "com.snapchat.android",
            "snap" to "com.snapchat.android",
            "instagram" to "com.instagram.android",
            "facebook" to "com.facebook.katana",
            "messenger" to "com.facebook.orca",
            "telegram" to "org.telegram.messenger",
            "tg" to "org.telegram.messenger",
            "twitter" to "com.twitter.android",
            "x" to "com.twitter.android",
            "tiktok" to "com.zhiliaoapp.musically",
            "tinder" to "com.tinder",
            "bumble" to "com.bumble.app",
            "hinge" to "co.hinge.app",
            "phone" to "com.samsung.android.dialer",
            "messages" to "com.google.android.apps.messaging",
            "photos" to "com.google.android.apps.photos",
            "play store" to "com.android.vending",
            "playstore" to "com.android.vending",
        )
        for ((key, packageName) in aliases) {
            if (lower == key || lower.contains(key)) {
                try {
                    context.packageManager.getPackageInfo(packageName, 0)
                    return packageName
                } catch (_: Exception) {
                    // try next / label scan
                }
            }
        }
        // Exact / contains label match against launchable apps only
        val pm = context.packageManager
        val main = Intent(Intent.ACTION_MAIN, null).addCategory(Intent.CATEGORY_LAUNCHER)
        val launchables = pm.queryIntentActivities(main, 0)
        var containsHit: String? = null
        for (ri in launchables) {
            val label = ri.loadLabel(pm)?.toString() ?: continue
            val p = ri.activityInfo?.packageName ?: continue
            if (label.equals(lower, ignoreCase = true)) {
                return p
            }
            if (containsHit == null && label.lowercase().contains(lower) && lower.length >= 3) {
                containsHit = p
            }
        }
        return containsHit
    }

    /**
     * Execute common chat instructions without a full LLM agent loop.
     * "open settings" / "settings" → system Settings; other open X → try launch.
     */
    private fun executeSimpleInstruction(instruction: String): String {
        val text = instruction.trim()
        val lower = text.lowercase()
        return try {
            when {
                lower.contains("setting") -> {
                    val intent = Intent(android.provider.Settings.ACTION_SETTINGS)
                    if (startUiActivity(intent)) "OK · opened Settings"
                    else "Failed: could not launch Settings (background activity blocked)"
                }
                lower.contains("wifi") || lower.contains("wi-fi") -> {
                    val intent = Intent(android.provider.Settings.ACTION_WIFI_SETTINGS)
                    if (startUiActivity(intent)) "OK · opened Wi‑Fi settings"
                    else "Failed: could not launch Wi‑Fi settings"
                }
                lower.contains("bluetooth") -> {
                    val intent = Intent(android.provider.Settings.ACTION_BLUETOOTH_SETTINGS)
                    if (startUiActivity(intent)) "OK · opened Bluetooth settings"
                    else "Failed: could not launch Bluetooth settings"
                }
                lower.startsWith("open ") || lower.startsWith("launch ") -> {
                    val app = text.substringAfter(' ').trim()
                    val pm = context.packageManager
                    val launch = pm.getLaunchIntentForPackage(app)
                        ?: pm.getLaunchIntentForPackage(guessPackage(app))
                    if (launch != null) {
                        if (startUiActivity(launch)) "OK · launched $app"
                        else "Failed: could not launch $app"
                    } else {
                        val intent = Intent(android.provider.Settings.ACTION_SETTINGS)
                        if (startUiActivity(intent)) {
                            "OK · could not resolve '$app'; opened Settings instead"
                        } else {
                            "Failed: could not resolve '$app'"
                        }
                    }
                }
                else -> {
                    val intent = Intent(android.provider.Settings.ACTION_SETTINGS)
                    if (startUiActivity(intent)) "OK · opened Settings for: $text"
                    else "Failed: could not launch Settings for: $text"
                }
            }
        } catch (e: Exception) {
            Log.e(tag, "executeSimpleInstruction failed", e)
            "Failed: ${e.message}"
        }
    }

    private fun guessPackage(name: String): String {
        val n = name.lowercase().replace(" ", "")
        return when {
            n.contains("chrome") -> "com.android.chrome"
            n.contains("setting") -> "com.android.settings"
            n.contains("camera") -> "com.android.camera2"
            n.contains("phone") -> "com.android.dialer"
            n.contains("message") || n.contains("sms") -> "com.android.messaging"
            else -> name
        }
    }

    fun disconnect() {
        userDisconnected = true
        reconnectJob?.cancel()
        heartbeatJob?.cancel()
        registerAckJob?.cancel()
        proactiveRefreshJob?.cancel()
        stopStreamInternal()
        webSocket?.close(1000, "User disconnect")
        webSocket = null
        serverAcked = false
        lastHeartbeatAckAtMs = 0L
        _statusFlow.value = "Disconnected"
        _routeFlow.value = "Route: —"
    }
}
