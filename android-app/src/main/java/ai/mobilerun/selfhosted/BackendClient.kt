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
import java.util.UUID
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
    private val reconnectAttempt = AtomicInteger(0)
    private var reconnectJob: Job? = null
    private var heartbeatJob: Job? = null
    private var userDisconnected = false
    private var connecting = false

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

    private suspend fun connectBest(force: Boolean = false) {
        if (userDisconnected) return
        if (connecting && !force) return
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
        webSocket?.cancel()
        webSocket = null
        activeRoute = candidate.route
        lastLatencyMs = latencyMs
        updateRouteUi()
        _statusFlow.value = "Connecting (${candidate.route})…"

        val request = Request.Builder().url(candidate.ws).build()
        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                Log.d(tag, "WebSocket opened via ${candidate.route}")
                reconnectAttempt.set(0)
                _statusFlow.value = "Connected"
                _pairErrorFlow.value = null
                prefs().edit().putString("last_pair_error", "").apply()
                val msg = mutableMapOf<String, Any?>(
                    "device_id" to deviceId,
                    "platform" to "android",
                    "type" to "register",
                    "role" to "device",
                    "route" to candidate.route,
                    "latency_ms" to latencyMs,
                    "name" to android.os.Build.MODEL,
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
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                handleMessage(text)
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                _statusFlow.value = "Disconnecting"
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                _statusFlow.value = "Disconnected"
                stopStreamInternal()
                scheduleReconnect()
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.e(tag, "WebSocket error via ${candidate.route}", t)
                _statusFlow.value = "Error: ${t.message}"
                stopStreamInternal()
                // Try next route immediately once, then backoff
                scope.launch {
                    val others = candidates().filter { it.ws != candidate.ws }
                    if (others.isNotEmpty() && reconnectAttempt.get() == 0) {
                        val next = others.first()
                        openSocket(next, probeLatencyMs(next.ws, next.http))
                    } else {
                        scheduleReconnect()
                    }
                }
            }
        })
    }

    private fun updateRouteUi() {
        val lat = lastLatencyMs?.let { "${it.toInt()} ms" } ?: "—"
        _routeFlow.value = "Route: ${activeRoute.uppercase()} · $lat"
    }

    private fun startHeartbeat() {
        heartbeatJob?.cancel()
        heartbeatJob = scope.launch {
            while (isActive && webSocket != null) {
                val t0 = System.nanoTime()
                val hb = mutableMapOf<String, Any?>(
                    "type" to "heartbeat",
                    "device_id" to deviceId,
                    "client_ts" to System.currentTimeMillis(),
                    "route" to activeRoute,
                    "latency_ms" to lastLatencyMs,
                )
                sessionToken?.let { hb["session_token"] = it }
                authToken?.let { hb["auth_token"] = it }
                val sent = webSocket?.send(gson.toJson(hb)) == true
                if (!sent) break
                delay(15_000)
                // Rough RTT estimate from last ack handled in handleMessage
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
                // Keep t0 referenced for future precise RTT if server echoes
                Log.v(tag, "heartbeat tick ${(System.nanoTime() - t0) / 1e6}")
            }
        }
    }

    private fun scheduleReconnect() {
        if (userDisconnected) return
        reconnectJob?.cancel()
        reconnectJob = scope.launch {
            val attempt = reconnectAttempt.getAndIncrement()
            val base = min(60.0, 1.0 * Math.pow(2.0, attempt.toDouble()))
            val jitter = base * 0.2
            val delaySec = (base + Random.nextDouble(-jitter, jitter)).coerceAtLeast(0.5)
            _statusFlow.value = "Reconnecting in ${delaySec.toInt()}s…"
            delay((delaySec * 1000).toLong())
            connectBest(force = true)
        }
    }

    private fun handleMessage(text: String) {
        try {
            @Suppress("UNCHECKED_CAST")
            val message = gson.fromJson(text, Map::class.java) as Map<String, Any?>
            when (message["type"] as? String ?: message["status"] as? String) {
                "connected", null -> {
                    if (message["status"] == "connected" || message["session_token"] != null) {
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
                        _statusFlow.value = "Connected"
                        ConnectionService.start(context)
                        reportPermissions(
                            ScreenCaptureService.instance != null,
                        )
                    }
                }
                "heartbeat_ack" -> {
                    // Refresh displayed latency lightly
                    lastLatencyMs = lastLatencyMs ?: 20.0
                    updateRouteUi()
                }
                "command" -> handleCommand(message)
                "stream_control" -> handleStreamControl(message)
                "run_task" -> {
                    val instruction = message["instruction"] as? String ?: "Unknown"
                    val taskId = message["task_id"] as? String ?: ""
                    _taskFlow.value = "Running: $instruction"
                    scope.launch {
                        sendTaskUpdate(taskId, "running", "Task started: $instruction")
                        sendAgentEvent(null, 0, "run_task", instruction)
                        val outcome = executeSimpleInstruction(instruction)
                        _taskFlow.value = outcome
                        sendAgentEvent(null, 1, "run_task_done", outcome)
                        sendTaskUpdate(
                            taskId,
                            if (outcome.startsWith("OK")) "completed" else "failed",
                            outcome,
                        )
                    }
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

    private fun handleCommand(message: Map<String, Any?>) {
        val command = message["command"] as? String ?: return
        val requestId = message["request_id"] as? String ?: return
        @Suppress("UNCHECKED_CAST")
        val params = message["params"] as? Map<String, Any?>

        scope.launch {
            try {
                val a11yService = MobilerunAccessibilityService.instance
                    ?: throw Exception("Accessibility service not connected")

                val result = when (command) {
                    "tap" -> {
                        val x = (params?.get("x") as? Number)?.toInt() ?: 0
                        val y = (params?.get("y") as? Number)?.toInt() ?: 0
                        a11yService.tapAsync(x, y)
                        sendAgentEvent(null, null, "tap", "tap($x,$y)")
                        "OK"
                    }
                    "swipe" -> {
                        val x1 = (params?.get("x1") as? Number)?.toInt() ?: 0
                        val y1 = (params?.get("y1") as? Number)?.toInt() ?: 0
                        val x2 = (params?.get("x2") as? Number)?.toInt() ?: 0
                        val y2 = (params?.get("y2") as? Number)?.toInt() ?: 0
                        val duration = (params?.get("duration_ms") as? Number)?.toLong() ?: 300
                        a11yService.swipeAsync(x1, y1, x2, y2, duration)
                        sendAgentEvent(null, null, "swipe", "swipe($x1,$y1->$x2,$y2)")
                        "OK"
                    }
                    "press_button" -> {
                        val button = params?.get("button") as? String
                        when (button) {
                            "back" -> a11yService.pressBack()
                            "home" -> a11yService.pressHome()
                            "recents" -> a11yService.pressRecents()
                            else -> false
                        }
                        "OK"
                    }
                    "get_ui_tree" -> a11yService.getUITree()
                    "screenshot" -> ""
                    "get_device_info" -> {
                        mapOf(
                            "device_id" to deviceId,
                            "platform" to "android",
                            "stream" to _streamFlow.value,
                            "route" to activeRoute,
                            "latency_ms" to lastLatencyMs,
                        )
                    }
                    else -> throw Exception("Unknown command: $command")
                }

                sendCommandResponse(requestId, result, null)
            } catch (e: Exception) {
                sendCommandResponse(requestId, null, e.message ?: "Unknown error")
            }
        }
    }

    private fun sendCommandResponse(requestId: String, result: Any?, error: String?) {
        val response = mutableMapOf<String, Any?>(
            "type" to "response",
            "request_id" to requestId,
        )
        if (error != null) response["error"] = error else response["result"] = result
        webSocket?.send(gson.toJson(response))
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
        // Overlay permission is a documented BAL exemption on Android 10+
        try {
            if (android.provider.Settings.canDrawOverlays(context)) {
                context.startActivity(intent)
                return true
            }
        } catch (e: Exception) {
            Log.w(tag, "overlay launch failed: ${e.message}")
        }
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
        stopStreamInternal()
        webSocket?.close(1000, "User disconnect")
        webSocket = null
        _statusFlow.value = "Disconnected"
        _routeFlow.value = "Route: —"
    }
}
