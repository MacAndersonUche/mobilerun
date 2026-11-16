package ai.mobilerun.selfhosted

import android.app.Activity
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
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

    private val projectionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK && result.data != null) {
            backendClient.startCaptureWithPermission(
                result.resultCode,
                result.data!!,
                pendingFps,
                pendingQuality,
            )
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

        intent?.data?.let { handlePairingUri(it) }

        setContent {
            MaterialTheme {
                MainScreen(
                    backendClient = backendClient,
                    cognitoAuth = cognitoAuth,
                    onOpenAccessibilitySettings = {
                        startActivity(Intent("android.settings.ACCESSIBILITY_SETTINGS"))
                    },
                    onRequestLiveView = {
                        pendingFps = 3
                        pendingQuality = 45
                        val mgr = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
                        projectionLauncher.launch(mgr.createScreenCaptureIntent())
                    },
                )
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        intent.data?.let { handlePairingUri(it) }
    }

    private fun handlePairingUri(uri: Uri) {
        // QR remains fallback for pairing / APK deep link
        if (uri.scheme == "mobilerun" && uri.host == "pair") {
            backendClient.pairFromUri(uri)
        }
    }
}

@Composable
fun MainScreen(
    backendClient: BackendClient,
    cognitoAuth: CognitoAuth,
    onOpenAccessibilitySettings: () -> Unit,
    onRequestLiveView: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var connectionStatus by remember { mutableStateOf("Disconnected") }
    var routeStatus by remember { mutableStateOf("Route: —") }
    var lastTask by remember { mutableStateOf("No tasks yet") }
    var streamStatus by remember { mutableStateOf("idle") }
    var userCode by remember { mutableStateOf<String?>(null) }
    var linkStatus by remember { mutableStateOf(cognitoAuth.savedEmail() ?: "Not signed in") }
    var busy by remember { mutableStateOf(false) }
    var backendUrl by remember {
        mutableStateOf(
            backendClient.defaultBackendHttp()
                ?: "https://68tgk4z5n6.execute-api.eu-west-2.amazonaws.com",
        )
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

    Surface(
        modifier = Modifier.fillMaxSize(),
        color = MaterialTheme.colorScheme.background,
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(text = "MobileRun", style = MaterialTheme.typography.headlineLarge)
            Text(
                text = "by MacAI · wireless · no USB",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            StatusCard("Account", linkStatus, cognitoAuth.savedEmail() != null)
            StatusCard("Status", connectionStatus, connectionStatus.contains("Connected"))
            StatusCard("Active route", routeStatus, routeStatus.contains("LAN") || routeStatus.contains("DISCOVERED") || routeStatus.contains("CLOUD"))
            StatusCard("Last Task", lastTask, true)
            StatusCard("Live stream", streamStatus, streamStatus == "streaming")

            if (userCode != null) {
                Card(modifier = Modifier.fillMaxWidth()) {
                    Column(
                        Modifier.padding(16.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Text("Enter this code on Account → Link a phone", style = MaterialTheme.typography.bodySmall)
                        Text(
                            text = userCode!!,
                            style = MaterialTheme.typography.headlineMedium,
                            textAlign = TextAlign.Center,
                        )
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
                            linkStatus = "Approve ${started.user_code} on the web Account page"
                            val tok = cognitoAuth.pollDeviceCode(
                                backendUrl.trim(),
                                started.device_code,
                                started.interval,
                            ) { linkStatus = it }
                            tok.access_token?.let { backendClient.setAuthToken(it, backendUrl.trim()) }
                            tok.session_token?.let {
                                backendClient.setSessionFromDeviceCode(
                                    it,
                                    tok.device_id,
                                    tok.owner,
                                )
                            }
                            linkStatus = tok.owner ?: "Linked"
                            userCode = null
                        } catch (e: Exception) {
                            linkStatus = "Link failed: ${e.message}"
                        } finally {
                            busy = false
                        }
                    }
                },
                enabled = !busy,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(if (busy) "Waiting…" else "Sign in & link phone")
            }

            Spacer(modifier = Modifier.weight(1f))

            Button(onClick = onOpenAccessibilitySettings, modifier = Modifier.fillMaxWidth()) {
                Text("Enable Accessibility Service")
            }
            OutlinedButton(onClick = onRequestLiveView, modifier = Modifier.fillMaxWidth()) {
                Text("Allow screen capture (one-time)")
            }

            Text(
                text = "Same Cognito account as the web UI. QR pairing remains a fallback.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
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
                color = if (ok) {
                    MaterialTheme.colorScheme.primary
                } else {
                    MaterialTheme.colorScheme.onSurface
                },
            )
        }
    }
}
