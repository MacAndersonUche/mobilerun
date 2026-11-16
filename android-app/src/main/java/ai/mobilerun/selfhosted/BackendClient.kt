package ai.mobilerun.selfhosted

import android.content.Context
import android.content.Intent
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
    private var wsOverride: String? = null
    private var deviceId: String = getOrCreateDeviceId()
    private var pendingToken: String? = null

    private val _statusFlow = MutableStateFlow("Disconnected")
    val statusFlow: StateFlow<String> = _statusFlow

    private val _taskFlow = MutableStateFlow("No tasks yet")
    val taskFlow: StateFlow<String> = _taskFlow

    private val _streamFlow = MutableStateFlow("idle")
    val streamFlow: StateFlow<String> = _streamFlow

    var onStreamPermissionNeeded: ((fps: Int, quality: Int) -> Unit)? = null

    init {
        ScreenCaptureService.frameListener = { frame ->
            sendFrame(frame)
        }
    }

    private fun getOrCreateDeviceId(): String {
        val prefs = context.getSharedPreferences("mobilerun", Context.MODE_PRIVATE)
        var id = prefs.getString("device_id", null)
        if (id == null) {
            id = "android_${UUID.randomUUID()}"
            prefs.edit().putString("device_id", id).apply()
        }
        return id
    }

    fun pair(backendUrl: String, token: String, wsUrl: String? = null) {
        this.backendUrl = backendUrl
        this.wsOverride = wsUrl
        this.pendingToken = token

        context.getSharedPreferences("mobilerun", Context.MODE_PRIVATE)
            .edit()
            .putString("backend_url", backendUrl)
            .putString("pairing_token", token)
            .putString("ws_url", wsUrl)
            .apply()

        connect(token)
    }

    private fun connect(token: String) {
        val wsUrl = when {
            !wsOverride.isNullOrBlank() -> wsOverride!!
            else -> backendUrl?.replace("http", "ws") + "/api/devices/connect"
        }

        val request = Request.Builder().url(wsUrl!!).build()

        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                Log.d(TAG, "WebSocket opened")
                _statusFlow.value = "Connected"
                val msg = mapOf(
                    "token" to token,
                    "device_id" to deviceId,
                    "platform" to "android",
                    "type" to "register",
                    "role" to "device",
                )
                webSocket.send(gson.toJson(msg))
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
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.e(TAG, "WebSocket error", t)
                _statusFlow.value = "Error: ${t.message}"
            }
        })
    }

    private fun handleMessage(text: String) {
        try {
            @Suppress("UNCHECKED_CAST")
            val message = gson.fromJson(text, Map::class.java) as Map<String, Any?>
            when (message["type"] as? String) {
                "command" -> handleCommand(message)
                "stream_control" -> handleStreamControl(message)
                "run_task" -> {
                    val instruction = message["instruction"] as? String ?: "Unknown"
                    _taskFlow.value = "Running: $instruction"
                    scope.launch {
                        sendTaskUpdate(
                            message["task_id"] as? String ?: "",
                            "running",
                            "Task started: $instruction",
                        )
                        sendAgentEvent(
                            currentApp = null,
                            step = 0,
                            action = "run_task",
                            log = instruction,
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
                "heartbeat_ack" -> Unit
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to handle message", e)
        }
    }

    private fun handleStreamControl(message: Map<String, Any?>) {
        val action = message["action"] as? String ?: return
        val fps = (message["fps"] as? Number)?.toInt() ?: 3
        val quality = (message["quality"] as? Number)?.toInt() ?: 45
        when (action) {
            "start" -> {
                _streamFlow.value = "starting"
                // Ask MainActivity to obtain MediaProjection (one-time system prompt)
                onStreamPermissionNeeded?.invoke(fps, quality)
                    ?: Log.w(TAG, "No permission callback registered for stream start")
            }
            "stop" -> stopStreamInternal()
        }
    }

    fun startCaptureWithPermission(resultCode: Int, data: Intent, fps: Int, quality: Int) {
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
        // Keep frames ephemeral — never persisted by phone
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
                    "screenshot" -> {
                        // Prefer live MediaProjection stream; one-shot still stubbed
                        ""
                    }
                    "get_device_info" -> {
                        mapOf(
                            "device_id" to deviceId,
                            "platform" to "android",
                            "stream" to _streamFlow.value,
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
        val msg = mapOf(
            "type" to "task_update",
            "task_id" to taskId,
            "update" to mapOf(
                "status" to status,
                "result" to result,
                "completed_at" to System.currentTimeMillis(),
            ),
        )
        webSocket?.send(gson.toJson(msg))
    }

    fun disconnect() {
        stopStreamInternal()
        webSocket?.close(1000, "User disconnect")
    }
}
