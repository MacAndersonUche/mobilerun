package ai.mobilerun.selfhosted

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.util.Log
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

/**
 * Pairing + minimal setup.
 *
 * Manual: Accessibility (system toggle) — deep-linked to this service.
 * Automatic (system dialogs): POST_NOTIFICATIONS, battery unrestricted.
 * On-demand only: MediaProjection when Live View starts (API 30+ screenshots
 * for agent steps use AccessibilityService.takeScreenshot instead).
 */
class MainActivity : ComponentActivity() {
    private lateinit var backendClient: BackendClient
    private var pendingFps: Int = 3
    private var pendingQuality: Int = 45
    private var mediaProjectionGranted = false
    private var autoGrantRunning = false

    private val notificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) {
        // Continue chain regardless of grant/deny
        runAutoGrantChain(fromCallback = true)
    }

    private val batteryExemptionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) {
        runAutoGrantChain(fromCallback = true)
    }

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

        // Process-wide client — ConnectionService keeps WS alive without this Activity
        backendClient = MobilerunApp.client() ?: BackendClient(applicationContext).also {
            Log.w("MainActivity", "MobilerunApp.client() null — created fallback")
        }
        backendClient.onStreamPermissionNeeded = { fps, quality ->
            // Live View only — not part of onboarding checklist
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
        backendClient.ensureServerConnected("main_onCreate")

        setContent {
            MaterialTheme {
                MainScreen(
                    activity = this,
                    backendClient = backendClient,
                    mediaProjectionGranted = mediaProjectionGranted,
                    onEnableAccessibility = {
                        PermissionStatus.openAccessibilitySettings(this)
                    },
                    onOpenRestrictedSettings = {
                        PermissionStatus.openAppDetails(this)
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
                    onEnsureAutoGrants = {
                        runAutoGrantChain(fromCallback = false)
                    },
                )
            }
        }
    }

    override fun onResume() {
        super.onResume()
        // Auto-recover Accessibility stuck in Binding after install/update
        val snap = PermissionStatus.snapshot(this, mediaProjectionGranted)
        if (snap.accessibilityStuckBinding) {
            PermissionStatus.tryRecoverAccessibilityBinding(this)
        }
        if (::backendClient.isInitialized) {
            backendClient.reportPermissions(mediaProjectionGranted)
            backendClient.ensureServerConnected("main_onResume")
            if (backendClient.isPaired()) {
                runAutoGrantChain(fromCallback = false)
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        intent.data?.let { handleDeepLink(it) }
    }

    /**
     * Fire one system dialog at a time for everything that is not Accessibility.
     * Skips already-granted items. Safe to call repeatedly from onResume.
     */
    private fun runAutoGrantChain(fromCallback: Boolean) {
        if (!::backendClient.isInitialized) return
        if (!backendClient.isPaired()) return
        if (autoGrantRunning && !fromCallback) return

        ConnectionService.start(this)

        if (!PermissionStatus.hasNotifications(this) && Build.VERSION.SDK_INT >= 33) {
            autoGrantRunning = true
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            return
        }
        if (!PermissionStatus.isIgnoringBatteryOptimizations(this)) {
            autoGrantRunning = true
            try {
                batteryExemptionLauncher.launch(PermissionStatus.batteryExemptionIntent(this))
            } catch (_: Exception) {
                PermissionStatus.openBatterySettings(this)
                autoGrantRunning = false
            }
            return
        }
        autoGrantRunning = false
        backendClient.reportPermissions(mediaProjectionGranted)
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
    onEnableAccessibility: () -> Unit,
    onOpenRestrictedSettings: () -> Unit,
    onRequestLiveView: () -> Unit,
    onScanQr: () -> Unit,
    onPermissionsChanged: () -> Unit,
    onEnsureAutoGrants: () -> Unit,
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
        backendClient.pairedFlow.collect {
            paired = it
            if (it) onEnsureAutoGrants()
        }
    }
    LaunchedEffect(mediaProjectionGranted) { refreshPerms() }
    LaunchedEffect(paired) {
        if (paired) {
            refreshPerms()
            onEnsureAutoGrants()
        }
    }

    // Poll a11y after user returns from Settings
    LaunchedEffect(paired) {
        if (!paired) return@LaunchedEffect
        while (true) {
            kotlinx.coroutines.delay(1500)
            val next = PermissionStatus.snapshot(activity, mediaProjectionGranted)
            if (next != snap) {
                snap = next
                onPermissionsChanged()
            }
        }
    }

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
                // Green only when server-acked Connected — not "Registering…" / stale.
                StatusCard("Status", connectionStatus, connectionStatus == "Connected")
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

                // Slim setup: hide everything already granted
                val showRestricted = PermissionStatus.restrictedSettingsNeeded(activity) && !snap.accessibility
                val showA11y = !snap.accessibility
                val showA11yStuck = snap.accessibilityStuckBinding
                val showNotifs = !snap.notifications
                val showBattery = !snap.batteryOptimization
                val setupDone = snap.readyForAgent && snap.notifications && snap.batteryOptimization

                if (!setupDone || showRestricted || showA11yStuck) {
                    Card(modifier = Modifier.fillMaxWidth()) {
                        Column(
                            Modifier.padding(16.dp),
                            verticalArrangement = Arrangement.spacedBy(10.dp),
                        ) {
                            Text("Setup", style = MaterialTheme.typography.titleMedium)
                            Text(
                                when {
                                    showA11yStuck ->
                                        "Accessibility is stuck Binding after install. Tap Recover — or toggle it Off/On in system settings."
                                    showA11y ->
                                        "One manual step: turn on Accessibility. Notifications and battery are requested automatically."
                                    else ->
                                        "Finishing automatic system prompts…"
                                },
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            if (showRestricted) {
                                AssistCard(
                                    title = "Allow restricted settings (Android 13+)",
                                    body = "Sideloaded apps need this before Accessibility can turn on. Apps → MobileRun → ⋮ → Allow restricted settings.",
                                    actionLabel = "Open app settings",
                                    onClick = {
                                        onOpenRestrictedSettings()
                                        refreshPerms()
                                    },
                                )
                            }
                            if (showA11yStuck) {
                                Button(
                                    onClick = {
                                        val ok = PermissionStatus.tryRecoverAccessibilityBinding(activity)
                                        if (!ok) {
                                            onEnableAccessibility()
                                        }
                                        refreshPerms()
                                    },
                                    modifier = Modifier.fillMaxWidth(),
                                ) {
                                    Text("Recover Accessibility bind")
                                }
                            }
                            if (showA11y) {
                                Button(
                                    onClick = {
                                        onEnableAccessibility()
                                        refreshPerms()
                                    },
                                    modifier = Modifier.fillMaxWidth(),
                                ) {
                                    Text("Enable Accessibility")
                                }
                            }
                            if (showNotifs) {
                                Text(
                                    "Waiting for notification permission dialog…",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            if (showBattery) {
                                Text(
                                    "Waiting for battery unrestricted prompt…",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            TextButton(
                                onClick = {
                                    refreshPerms()
                                    onEnsureAutoGrants()
                                },
                                modifier = Modifier.fillMaxWidth(),
                            ) {
                                Text("Re-check / retry prompts")
                            }
                        }
                    }
                } else {
                    StatusCard(
                        "Setup",
                        if (snap.accessibilityBound) {
                            "Ready — Accessibility bound · notifications + battery OK"
                        } else {
                            "Ready — Accessibility on · notifications + battery OK"
                        },
                        true,
                    )
                    val keyboardSelected = remember(snap) {
                        ai.mobilerun.selfhosted.input.MobilerunKeyboardIME.isSelected(activity)
                    }
                    // Always offer Enable keyboard — Samsung may hide us until
                    // subtypes are present and the user toggles the IME on.
                    Text(
                        if (keyboardSelected) {
                            "Mobilerun Keyboard is selected."
                        } else {
                            "Required for reliable typing: enable Mobilerun Keyboard " +
                                "in system settings, then pick it. Agents still fall " +
                                "back to accessibility SET_TEXT if the IME is off."
                        },
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Button(
                        onClick = {
                            // Best-effort silent enable (needs WRITE_SECURE_SETTINGS)
                            ai.mobilerun.selfhosted.input.ImeSessionController
                                .ensureSelected(activity)
                            // Always open system IME settings, then show picker
                            ai.mobilerun.selfhosted.input.ImeSettingsActivity
                                .openSettingsThenPicker(activity)
                            refreshPerms()
                        },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text("Enable keyboard")
                    }
                }

                // Live view is optional / on-demand, not onboarding
                if (showAdvanced || streamStatus == "streaming" || mediaProjectionGranted) {
                    TextButton(
                        onClick = onRequestLiveView,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(
                            if (mediaProjectionGranted || streamStatus == "streaming") {
                                "Live view capture OK"
                            } else {
                                "Enable live view capture (optional)"
                            },
                        )
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
