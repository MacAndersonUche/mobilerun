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
import androidx.compose.ui.unit.dp

class MainActivity : ComponentActivity() {
    private lateinit var backendClient: BackendClient
    private var pendingFps: Int = 3
    private var pendingQuality: Int = 45

    private val projectionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK && result.data != null) {
            // One-time MediaProjection grant — reused until revoked
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
                    onOpenAccessibilitySettings = {
                        startActivity(Intent("android.settings.ACCESSIBILITY_SETTINGS"))
                    },
                    onRequestLiveView = {
                        // Manual start from phone UI (also triggered by UI stream_control)
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
        val token = uri.getQueryParameter("token")
        val backend = uri.getQueryParameter("backend")
        val ws = uri.getQueryParameter("ws")
        if (token != null && backend != null) {
            backendClient.pair(backend, token, ws)
        }
    }
}

@Composable
fun MainScreen(
    backendClient: BackendClient,
    onOpenAccessibilitySettings: () -> Unit,
    onRequestLiveView: () -> Unit,
) {
    var connectionStatus by remember { mutableStateOf("Disconnected") }
    var lastTask by remember { mutableStateOf("No tasks yet") }
    var streamStatus by remember { mutableStateOf("idle") }

    LaunchedEffect(Unit) {
        backendClient.statusFlow.collect { connectionStatus = it }
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
            Text(text = "Mobilerun", style = MaterialTheme.typography.headlineLarge)

            StatusCard("Status", connectionStatus, connectionStatus.contains("Connected"))
            StatusCard("Last Task", lastTask, true)
            StatusCard("Live stream", streamStatus, streamStatus == "streaming")

            Spacer(modifier = Modifier.weight(1f))

            Button(onClick = onOpenAccessibilitySettings, modifier = Modifier.fillMaxWidth()) {
                Text("Enable Accessibility Service")
            }
            OutlinedButton(onClick = onRequestLiveView, modifier = Modifier.fillMaxWidth()) {
                Text("Allow screen capture (one-time)")
            }

            Text(
                text = "Scan a QR from the control UI to pair. Grant MediaProjection once for live view.",
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
