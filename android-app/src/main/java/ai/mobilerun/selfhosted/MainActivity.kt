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
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    private lateinit var backendClient: BackendClient
    private lateinit var cognitoAuth: CognitoAuth
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

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        backendClient = BackendClient(this)
        cognitoAuth = CognitoAuth(this)
        backendClient.onStreamPermissionNeeded = { fps, quality ->
            pendingFps = fps
            pendingQuality = quality
            val mgr = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
            projectionLauncher.launch(mgr.createScreenCaptureIntent())
        }

        intent?.data?.let { handleDeepLink(it) }

        setContent {
            MaterialTheme {
                MainScreen(
                    activity = this,
                    backendClient = backendClient,
                    cognitoAuth = cognitoAuth,
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
        // Legacy deep link ignored for pairing — Cognito login links the device.
        // Keep no-op so old QR links don't crash.
        if (uri.scheme == "mobilerun" && uri.host == "pair") {
            // no pairing via QR
        }
    }
}

@Composable
fun MainScreen(
    activity: ComponentActivity,
    backendClient: BackendClient,
    cognitoAuth: CognitoAuth,
    mediaProjectionGranted: Boolean,
    onRequestNotifications: () -> Unit,
    onRequestLiveView: () -> Unit,
    onPermissionsChanged: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var connectionStatus by remember { mutableStateOf("Disconnected") }
    var routeStatus by remember { mutableStateOf("Route: —") }
    var lastTask by remember { mutableStateOf("No tasks yet") }
    var streamStatus by remember { mutableStateOf("idle") }
    var userCode by remember { mutableStateOf<String?>(null) }
    var linkStatus by remember { mutableStateOf(cognitoAuth.savedEmail() ?: "Not signed in") }
    var busy by remember { mutableStateOf(false) }
    var snap by remember {
        mutableStateOf(PermissionStatus.snapshot(activity, mediaProjectionGranted))
    }
    var backendUrl by remember {
        mutableStateOf(
            backendClient.defaultBackendHttp()
                ?: "https://68tgk4z5n6.execute-api.eu-west-2.amazonaws.com",
        )
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
                text = "Executor APK · wireless · MacAI",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            StatusCard("Account", linkStatus, cognitoAuth.savedEmail() != null)
            StatusCard("Status", connectionStatus, connectionStatus.contains("Connected"))
            StatusCard("Active route", routeStatus, routeStatus.contains("LAN") || routeStatus.contains("DISCOVERED") || routeStatus.contains("CLOUD"))
            StatusCard("Last Task", lastTask, true)
            StatusCard("Live stream", streamStatus, streamStatus == "streaming")

            Card(modifier = Modifier.fillMaxWidth()) {
                Column(
                    Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Text("Permissions checklist", style = MaterialTheme.typography.titleMedium)
                    Text(
                        "Required so the hosted UI can drive this phone. Re-checked every time you return.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )

                    if (PermissionStatus.restrictedSettingsNeeded(activity)) {
                        AssistCard(
                            title = "Android 13+ · Allow restricted settings",
                            body = "Because this APK is sideloaded: Settings → Apps → MobileRun → ⋮ (top right) → Allow restricted settings. Then enable Accessibility.",
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
                    PermRow("Query installed packages", snap.queryPackages) {
                        // Install-time permission; open details for awareness
                        PermissionStatus.openAppDetails(activity)
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

            if (userCode != null) {
                Card(modifier = Modifier.fillMaxWidth()) {
                    Column(
                        Modifier.padding(16.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Text(
                            "Enter this code on the hosted UI → Account → Link a phone",
                            style = MaterialTheme.typography.bodySmall,
                            textAlign = TextAlign.Center,
                        )
                        Text(text = userCode!!, style = MaterialTheme.typography.headlineMedium)
                        Text(linkStatus, style = MaterialTheme.typography.bodySmall)
                    }
                }
            }

            OutlinedTextField(
                value = backendUrl,
                onValueChange = { backendUrl = it },
                label = { Text("Backend URL") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )

            Button(
                onClick = {
                    busy = true
                    scope.launch {
                        try {
                            val started = cognitoAuth.startDeviceCode(backendUrl.trim())
                            userCode = started.user_code
                            linkStatus = "Approve ${started.user_code} on Account"
                            val tok = cognitoAuth.pollDeviceCode(
                                backendUrl.trim(),
                                started.device_code,
                                started.interval,
                            ) { linkStatus = it }
                            tok.access_token?.let { backendClient.setAuthToken(it, backendUrl.trim()) }
                            tok.session_token?.let {
                                backendClient.setSessionFromDeviceCode(it, tok.device_id, tok.owner)
                            }
                            ConnectionService.start(activity)
                            backendClient.reportPermissions(mediaProjectionGranted)
                            linkStatus = tok.owner ?: "Linked"
                            userCode = null
                        } catch (e: Exception) {
                            linkStatus = "Link failed: ${e.message}"
                        } finally {
                            busy = false
                            refreshPerms()
                        }
                    }
                },
                enabled = !busy,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(if (busy) "Waiting…" else "Sign in & link phone")
            }

            Text(
                text = "Same Cognito account as the hosted UI. QR codes are only for downloading this APK.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier = Modifier.height(24.dp))
        }
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
        Column(Modifier = Modifier.weight(1f)) {
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
