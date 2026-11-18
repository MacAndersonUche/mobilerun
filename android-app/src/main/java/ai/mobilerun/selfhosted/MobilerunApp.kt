package ai.mobilerun.selfhosted

import android.app.Application
import android.util.Log

/**
 * Process-wide holder for [BackendClient] so [ConnectionService] can keep the
 * WebSocket alive after MainActivity is destroyed / the process is restarted
 * by the sticky foreground service (Samsung Doze, app switch, screen off).
 */
class MobilerunApp : Application() {
    lateinit var backendClient: BackendClient
        private set

    override fun onCreate() {
        super.onCreate()
        instance = this
        backendClient = BackendClient(applicationContext)
        Log.i(TAG, "MobilerunApp ready device=${backendClient.publicDeviceId()}")
        // Ensure FGS is up even before the user opens the UI
        try {
            ConnectionService.start(this)
        } catch (e: Exception) {
            Log.w(TAG, "ConnectionService.start: ${e.message}")
        }
    }

    companion object {
        private const val TAG = "MobilerunApp"
        @Volatile
        private var instance: MobilerunApp? = null

        fun get(): MobilerunApp? = instance

        fun client(): BackendClient? = instance?.backendClient
    }
}
