package ai.mobilerun.selfhosted

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp

class MainActivity : ComponentActivity() {
    private lateinit var backendClient: BackendClient
    private var pendingFps: Int = 3
    private var pendingQuality: Int = 45
    private var mediaProjectionGranted = false

    private val notificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { /* refreshed on resume */ }

    private val projectionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK && result.data != null) {
            mediaProjectionGranted = true
            backendClient.startCaptureWithPermission(
                result.resultCode,
                result.data!!,
                pendingFps,
                pendingQuality,
            )
            backendClient.reportPermissions(mediaProjectionGranted)
        }
    }

    private val qrLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { result ->
        val data = result.data?.data
        if (result.resultCode == Activity.RESULT_OK && data != null) {
            backendClient.pairFromUri(data)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        backendClient = BackendClient(this)
        backendClient.onStreamPermissionNeeded = { fps, quality ->
            pendingFps = fps
            pendingQuality = quality
            if (ScreenCaptureService.isStreaming()) {
                ScreenCaptureService.updateParams(fps, quality)
                backendClient.reportPermissions(true)
            } else {
                val mgr = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
                projectionLauncher.launch(mgr.createScreenCaptureIntent())
            }
        }

        intent?.data?.let { handleDeepLink(it) }

        setContent {
            MaterialTheme {
                MainScreen(
                    activity = this,
                    backendClient = backendClient,
                    mediaProjectionGranted = mediaProjectionGranted,
                    onRequestNotifications = {
                        if (Build.VERSION.SDK_INT >= 33) {
                            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
                        }
                    },
                    onRequestLiveView = {
                        pendingFps = 3
                        pendingQuality = 45
                        val mgr = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
                        projectionLauncher.launch(mgr.createScreenCaptureIntent())
                    },
                    onScanQr = {
                        qrLauncher.launch(Intent(this, QrScanActivity::class.java))
                    },
                    onPermissionsChanged = {
                        backendClient.reportPermissions(mediaProjectionGranted)
                    },
                )
            }
        }
    }

    override fun onResume() {
        super.onResume()
        if (::backendClient.isInitialized) {
            backendClient.reportPermissions(mediaProjectionGranted)
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        intent.data?.let { handleDeepLink(it) }
    }

    private fun handleDeepLink(uri: Uri) {
        val path = uri.path.orEmpty()
        val isPair = (uri.scheme == "mobilerun" && uri.host == "pair") ||
            path.contains("pair") ||
            uri.toString().contains("token=")
        if (isPair) {
            backendClient.pairFromUri(uri)
        }
    }
}

@Composable
fun MainScreen(
    activity: ComponentActivity,
    backendClient: BackendClient,
    mediaProjectionGranted: Boolean,
    onRequestNotifications: () -> Unit,
    onRequestLiveView: () -> Unit,
    onScanQr: () -> Unit,
    onPermissionsChanged: () -> Unit,
) {
    var connectionStatus by remember { mutableStateOf("Disconnected") }
    var routeStatus by remember { mutableStateOf("Route: —") }
    var lastTask by remember { mutableStateOf("No tasks yet") }
    var streamStatus by remember { mutableStateOf("idle") }
    var paired by remember { mutableStateOf(backendClient.isPaired()) }
    var pairBusy by remember { mutableStateOf(false) }
    var pairError by remember { mutableStateOf(backendClient.lastPairError()) }
    var showAdvanced by remember { mutableStateOf(false) }
    var advancedUrl by remember {
        mutableStateOf(backendClient.defaultBackendHttp() ?: BuildConfig.DEFAULT_CLOUD_HTTP)
    }
    var snap by remember {
        mutableStateOf(PermissionStatus.snapshot(activity, mediaProjectionGranted))
    }

    fun refreshPerms() {
        snap = PermissionStatus.snapshot(activity, mediaProjectionGranted)
        onPermissionsChanged()
    }

    LaunchedEffect(Unit) {
        backendClient.statusFlow.collect { connectionStatus = it }
    }
    LaunchedEffect(Unit) {
        backendClient.routeFlow.collect { routeStatus = it }
    }
    LaunchedEffect(Unit) {
        backendClient.taskFlow.collect { lastTask = it }
    }
    LaunchedEffect(Unit) {
        backendClient.streamFlow.collect { streamStatus = it }
    }
    LaunchedEffect(Unit) {
        backendClient.pairedFlow.collect { paired = it }
    }
    LaunchedEffect(mediaProjectionGranted) { refreshPerms() }

    Surface(
        modifier = Modifier.fillMaxSize(),
        color = MaterialTheme.colorScheme.background,
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(text = "MobileRun", style = MaterialTheme.typography.headlineLarge)
            Text(
                text = "Executor · wireless · MacAI",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            if (!paired) {
                Card(modifier = Modifier.fillMaxWidth()) {
                    Column(
                        Modifier.padding(16.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        Text(
                            "Scan the QR on ${BuildConfig.PAIR_UI_HINT}",
                            style = MaterialTheme.typography.titleMedium,
                            textAlign = TextAlign.Center,
                        )
                        Text(
                            "Sign in on the web UI → Devices → Connect phone, then scan that QR here (or open the link after install). No backend URL or password in the app.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            textAlign = TextAlign.Center,
                        )
                        Button(
                            onClick = {
                                pairError = null
                                onScanQr()
                            },
                            enabled = !pairBusy,
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Text(if (pairBusy) "Pairing…" else "Scan QR to pair")
                        }
                        var pasteCode by remember { mutableStateOf("") }
                        OutlinedTextField(
                            value = pasteCode,
                            onValueChange = { pasteCode = it.uppercase().filter { ch -> ch.isLetterOrDigit() }.take(8) },
                            label = { Text("Enter pairing code") },
                            placeholder = { Text("e.g. AB3K7Q2M") },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            enabled = !pairBusy,
                        )
                        OutlinedButton(
                            onClick = {
                                pairError = null
                                backendClient.pairWithCode(pasteCode)
                            },
                            enabled = !pairBusy && pasteCode.isNotBlank(),
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Text("Connect with code")
                        }
                        Text(
                            "Pairing status: " + when {
                                pairBusy -> "exchanging code…"
                                pairError != null -> "failed"
                                else -> "waiting for scan / code"
                            },
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        if (pairError != null) {
                            Text(
                                "Last error: $pairError",
                                color = MaterialTheme.colorScheme.error,
                                style = MaterialTheme.typography.bodySmall,
                            )
                        }
                    }
                }
            } else {
                StatusCard("Status", connectionStatus, connectionStatus.contains("Connected"))
                StatusCard(
                    "Active route",
                    routeStatus,
                    routeStatus.contains("LAN") || routeStatus.contains("DISCOVERED") || routeStatus.contains("CLOUD"),
                )
                StatusCard(
                    "Pairing / last error",
                    pairError ?: "OK · session stored",
                    pairError == null,
                )
                StatusCard("Last Task", lastTask, true)
                StatusCard("Live stream", streamStatus, streamStatus == "streaming")

                Card(modifier = Modifier.fillMaxWidth()) {
                    Column(
                        Modifier.padding(16.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        Text("Permissions checklist", style = MaterialTheme.typography.titleMedium)
                        if (PermissionStatus.restrictedSettingsNeeded(activity)) {
                            AssistCard(
                                title = "Android 13+ · Allow restricted settings",
                                body = "Settings → Apps → MobileRun → ⋮ → Allow restricted settings. Then enable Accessibility.",
                                actionLabel = "Open app settings",
                                onClick = {
                                    PermissionStatus.openAppDetails(activity)
                                    refreshPerms()
                                },
                            )
                        }
                        PermRow("Accessibility service", snap.accessibility) {
                            PermissionStatus.openAccessibilitySettings(activity)
                            refreshPerms()
                        }
                        PermRow("Notifications", snap.notifications, onClick = {
                            onRequestNotifications()
                            refreshPerms()
                        })
                        PermRow("Screen capture (live view)", snap.mediaProjection || mediaProjectionGranted) {
                            onRequestLiveView()
                        }
                        PermRow("Battery unrestricted", snap.batteryOptimization) {
                            PermissionStatus.openBatterySettings(activity)
                            refreshPerms()
                        }
                        PermRow("Draw over other apps", snap.overlay) {
                            PermissionStatus.openOverlaySettings(activity)
                            refreshPerms()
                        }
                        PermRow("Foreground connection", snap.foregroundService) {
                            ConnectionService.start(activity)
                            refreshPerms()
                        }
                        TextButton(onClick = { refreshPerms() }, modifier = Modifier.fillMaxWidth()) {
                            Text("Re-check permissions")
                        }
                    }
                }
            }

            TextButton(onClick = { showAdvanced = !showAdvanced }) {
                Text(if (showAdvanced) "Hide advanced" else "Advanced")
            }
            if (showAdvanced) {
                Card(modifier = Modifier.fillMaxWidth()) {
                    Column(
                        Modifier.padding(16.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Text("Backend override (optional)", style = MaterialTheme.typography.titleSmall)
                        OutlinedTextField(
                            value = advancedUrl,
                            onValueChange = { advancedUrl = it },
                            label = { Text("HTTP API URL") },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                        )
                        Button(
                            onClick = {
                                backendClient.setCloudEndpoints(advancedUrl.trim(), null)
                            },
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Text("Save override")
                        }
                        if (paired) {
                            TextButton(
                                onClick = {
                                    backendClient.unpair()
                                    paired = false
                                },
                                modifier = Modifier.fillMaxWidth(),
                            ) {
                                Text("Unpair this phone")
                            }
                        }
                    }
                }
            }

            Spacer(modifier = Modifier.height(24.dp))
        }
    }

    // Observe pair failures from client
    LaunchedEffect(Unit) {
        backendClient.pairErrorFlow.collect {
            pairError = it
            pairBusy = false
        }
    }
    LaunchedEffect(Unit) {
        backendClient.pairBusyFlow.collect { pairBusy = it }
    }
}

@Composable
private fun AssistCard(
    title: String,
    body: String,
    actionLabel: String,
    onClick: () -> Unit,
) {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.secondaryContainer,
        ),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(title, style = MaterialTheme.typography.titleSmall)
            Text(body, style = MaterialTheme.typography.bodySmall)
            Button(onClick = onClick) { Text(actionLabel) }
        }
    }
}

@Composable
private fun PermRow(label: String, ok: Boolean, onClick: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(label, style = MaterialTheme.typography.bodyMedium)
            Text(
                if (ok) "Ready" else "Tap to enable",
                style = MaterialTheme.typography.bodySmall,
                color = if (ok) MaterialTheme.colorScheme.primary
                else MaterialTheme.colorScheme.error,
            )
        }
        TextButton(onClick = onClick, enabled = !ok || label.contains("Foreground") || label.contains("Screen")) {
            Text(if (ok) "OK" else "Fix")
        }
    }
}

@Composable
private fun StatusCard(title: String, body: String, ok: Boolean) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(text = title, style = MaterialTheme.typography.titleMedium)
            Text(
                text = body,
                style = MaterialTheme.typography.bodyLarge,
                color = if (ok) MaterialTheme.colorScheme.primary
                else MaterialTheme.colorScheme.onSurface,
            )
        }
    }
}
