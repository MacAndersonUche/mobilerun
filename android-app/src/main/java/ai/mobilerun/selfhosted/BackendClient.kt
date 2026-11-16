package ai.mobilerun.selfhosted

import android.content.Context
import android.util.Log
import com.google.gson.Gson
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import okhttp3.*
import java.util.*
import java.util.concurrent.TimeUnit

class BackendClient(private val context: Context) {
    private val TAG = "BackendClient"
    private val client = OkHttpClient.Builder()
        .pingInterval(30, TimeUnit.SECONDS)
        .build()
    
    private val gson = Gson()
    private val scope = CoroutineScope(Dispatchers.IO)
    
    private var webSocket: WebSocket? = null
    private var backendUrl: String? = null
    private var deviceId: String = getOrCreateDeviceId()
    
    private val _statusFlow = MutableStateFlow("Disconnected")
    val statusFlow: StateFlow<String> = _statusFlow
    
    private val _taskFlow = MutableStateFlow("No tasks yet")
    val taskFlow: StateFlow<String> = _taskFlow

    private fun getOrCreateDeviceId(): String {
        val prefs = context.getSharedPreferences("mobilerun", Context.MODE_PRIVATE)
        var id = prefs.getString("device_id", null)
        if (id == null) {
            id = "android_${UUID.randomUUID()}"
            prefs.edit().putString("device_id", id).apply()
        }
        return id
    }

    fun pair(backendUrl: String, token: String) {
        this.backendUrl = backendUrl
        
        // Save pairing info
        context.getSharedPreferences("mobilerun", Context.MODE_PRIVATE)
            .edit()
            .putString("backend_url", backendUrl)
            .putString("pairing_token", token)
            .apply()
        
        connect(token)
    }

    private fun connect(token: String) {
        val wsUrl = backendUrl?.replace("http", "ws") + "/api/devices/connect"
        
        val request = Request.Builder()
            .url(wsUrl)
            .build()
        
        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                Log.d(TAG, "WebSocket opened")
                _statusFlow.value = "Connected"
                
                // Send pairing info
                val msg = mapOf(
                    "token" to token,
                    "device_id" to deviceId,
                    "platform" to "android"
                )
                webSocket.send(gson.toJson(msg))
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                Log.d(TAG, "Received: $text")
                handleMessage(text)
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                Log.d(TAG, "WebSocket closing: $reason")
                _statusFlow.value = "Disconnecting"
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                Log.d(TAG, "WebSocket closed: $reason")
                _statusFlow.value = "Disconnected"
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.e(TAG, "WebSocket error", t)
                _statusFlow.value = "Error: ${t.message}"
            }
        })
    }

    private fun handleMessage(text: String) {
        try {
            val message = gson.fromJson(text, Map::class.java)
            val type = message["type"] as? String
            
            when (type) {
                "run_task" -> {
                    val instruction = message["instruction"] as? String ?: "Unknown"
                    _taskFlow.value = "Running: $instruction"
                    
                    // TODO: Execute task using accessibility service
                    // For now, just acknowledge
                    scope.launch {
                        // Simulate task execution
                        kotlinx.coroutines.delay(2000)
                        sendTaskUpdate(
                            message["task_id"] as? String ?: "",
                            "completed",
                            "Task simulated"
                        )
                    }
                }
                "heartbeat_ack" -> {
                    // Keep alive acknowledged
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to handle message", e)
        }
    }

    private fun sendTaskUpdate(taskId: String, status: String, result: String) {
        val msg = mapOf(
            "type" to "task_update",
            "task_id" to taskId,
            "update" to mapOf(
                "status" to status,
                "result" to result,
                "completed_at" to System.currentTimeMillis()
            )
        )
        webSocket?.send(gson.toJson(msg))
    }

    fun disconnect() {
        webSocket?.close(1000, "User disconnect")
    }
}
