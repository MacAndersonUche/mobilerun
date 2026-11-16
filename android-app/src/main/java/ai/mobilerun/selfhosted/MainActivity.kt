package ai.mobilerun.selfhosted

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

class MainActivity : ComponentActivity() {
    private lateinit var backendClient: BackendClient

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        backendClient = BackendClient(this)

        // Handle pairing deep link
        intent?.data?.let { uri ->
            handlePairingUri(uri)
        }

        setContent {
            MaterialTheme {
                MainScreen(
                    backendClient = backendClient,
                    onOpenAccessibilitySettings = {
                        startActivity(Intent("android.settings.ACCESSIBILITY_SETTINGS"))
                    }
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
        
        if (token != null && backend != null) {
            backendClient.pair(backend, token)
        }
    }
}

@Composable
fun MainScreen(
    backendClient: BackendClient,
    onOpenAccessibilitySettings: () -> Unit
) {
    var connectionStatus by remember { mutableStateOf("Disconnected") }
    var lastTask by remember { mutableStateOf("No tasks yet") }

    LaunchedEffect(Unit) {
        backendClient.statusFlow.collect { status ->
            connectionStatus = status
        }
    }

    LaunchedEffect(Unit) {
        backendClient.taskFlow.collect { task ->
            lastTask = task
        }
    }

    Surface(
        modifier = Modifier.fillMaxSize(),
        color = MaterialTheme.colorScheme.background
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            Text(
                text = "Mobilerun",
                style = MaterialTheme.typography.headlineLarge
            )

            Card(
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Text(
                        text = "Status",
                        style = MaterialTheme.typography.titleMedium
                    )
                    Text(
                        text = connectionStatus,
                        style = MaterialTheme.typography.bodyLarge,
                        color = if (connectionStatus.contains("Connected")) {
                            MaterialTheme.colorScheme.primary
                        } else {
                            MaterialTheme.colorScheme.error
                        }
                    )
                }
            }

            Card(
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Text(
                        text = "Last Task",
                        style = MaterialTheme.typography.titleMedium
                    )
                    Text(
                        text = lastTask,
                        style = MaterialTheme.typography.bodyMedium
                    )
                }
            }

            Spacer(modifier = Modifier.weight(1f))

            Button(
                onClick = onOpenAccessibilitySettings,
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("Enable Accessibility Service")
            }

            Text(
                text = "Scan a QR code from the control UI to pair this device",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}
