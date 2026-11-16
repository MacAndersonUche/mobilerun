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
                "command" -> {
                    // Handle device control commands
                    handleCommand(message)
                }
                "run_task" -> {
                    val instruction = message["instruction"] as? String ?: "Unknown"
                    _taskFlow.value = "Running: $instruction"
                    
                    scope.launch {
                        try {
                            // Execute task via mobilerun backend
                            // The backend will send individual commands which we handle above
                            sendTaskUpdate(
                                message["task_id"] as? String ?: "",
                                "running",
                                "Task started"
                            )
                        } catch (e: Exception) {
                            sendTaskUpdate(
                                message["task_id"] as? String ?: "",
                                "failed",
                                "Error: ${e.message}"
                            )
                        }
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
    
    private fun handleCommand(message: Map<*, *>) {
        val command = message["command"] as? String ?: return
        val requestId = message["request_id"] as? String ?: return
        val params = message["params"] as? Map<*, *>
        
        scope.launch {
            try {
                val a11yService = MobilerunAccessibilityService.instance
                    ?: throw Exception("Accessibility service not connected")
                
                val result = when (command) {
                    "tap" -> {
                        val x = (params?.get("x") as? Number)?.toInt() ?: 0
                        val y = (params?.get("y") as? Number)?.toInt() ?: 0
                        a11yService.tapAsync(x, y)
                        "OK"
                    }
                    "swipe" -> {
                        val x1 = (params?.get("x1") as? Number)?.toInt() ?: 0
                        val y1 = (params?.get("y1") as? Number)?.toInt() ?: 0
                        val x2 = (params?.get("x2") as? Number)?.toInt() ?: 0
                        val y2 = (params?.get("y2") as? Number)?.toInt() ?: 0
                        val duration = (params?.get("duration_ms") as? Number)?.toLong() ?: 300
                        a11yService.swipeAsync(x1, y1, x2, y2, duration)
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
                    "get_ui_tree" -> {
                        a11yService.getUITree()
                    }
                    "screenshot" -> {
                        // Screenshot requires MediaProjection API which is complex
                        // For now, return empty
                        ""
                    }
                    else -> {
                        throw Exception("Unknown command: $command")
                    }
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
            "request_id" to requestId
        )
        
        if (error != null) {
            response["error"] = error
        } else {
            response["result"] = result
        }
        
        webSocket?.send(gson.toJson(response))
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
