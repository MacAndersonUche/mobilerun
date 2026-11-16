package ai.mobilerun.selfhosted

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.util.Log
import java.util.concurrent.CopyOnWriteArrayList

/**
 * Discovers laptop backends advertising `_mobilerun._tcp` via Android NSD/mDNS.
 */
class LanDiscovery(context: Context) {
    data class Service(
        val host: String,
        val port: Int,
        val httpUrl: String,
        val wsUrl: String,
    )

    interface Listener {
        fun onServiceFound(service: Service)
        fun onError(message: String)
    }

    private val tag = "LanDiscovery"
    private val nsd = context.getSystemService(Context.NSD_SERVICE) as NsdManager
    private val listeners = CopyOnWriteArrayList<Listener>()
    private var discoveryListener: NsdManager.DiscoveryListener? = null
    @Volatile
    var lastFound: Service? = null
        private set

    fun addListener(listener: Listener) {
        listeners.add(listener)
        lastFound?.let { listener.onServiceFound(it) }
    }

    fun removeListener(listener: Listener) {
        listeners.remove(listener)
    }

    fun start() {
        if (discoveryListener != null) return
        val listener = object : NsdManager.DiscoveryListener {
            override fun onStartDiscoveryFailed(serviceType: String?, errorCode: Int) {
                Log.w(tag, "start failed $errorCode")
                listeners.forEach { it.onError("NSD start failed: $errorCode") }
            }

            override fun onStopDiscoveryFailed(serviceType: String?, errorCode: Int) {
                Log.w(tag, "stop failed $errorCode")
            }

            override fun onDiscoveryStarted(serviceType: String?) {
                Log.d(tag, "discovery started $serviceType")
            }

            override fun onDiscoveryStopped(serviceType: String?) {
                Log.d(tag, "discovery stopped")
            }

            override fun onServiceFound(serviceInfo: NsdServiceInfo) {
                if (!serviceInfo.serviceType.contains("mobilerun", ignoreCase = true) &&
                    serviceInfo.serviceName?.contains("Mobilerun", true) != true
                ) {
                    // Still resolve if type matches our constant
                    if (serviceInfo.serviceType?.contains("_tcp") != true) return
                }
                nsd.resolveService(
                    serviceInfo,
                    object : NsdManager.ResolveListener {
                        override fun onResolveFailed(serviceInfo: NsdServiceInfo?, errorCode: Int) {
                            Log.w(tag, "resolve failed $errorCode")
                        }

                        override fun onServiceResolved(resolved: NsdServiceInfo) {
                            val host = resolved.host?.hostAddress ?: return
                            val port = resolved.port
                            val attrs = resolved.attributes ?: emptyMap()
                            fun attr(key: String): String? {
                                val bytes = attrs[key] ?: return null
                                return String(bytes, Charsets.UTF_8)
                            }

                            val http = attr("http") ?: "http://$host:$port"
                            val ws = attr("ws") ?: "ws://$host:$port/api/devices/connect"
                            val svc = Service(host, port, http, ws)
                            lastFound = svc
                            Log.i(tag, "found $http / $ws")
                            listeners.forEach { it.onServiceFound(svc) }
                        }
                    },
                )
            }

            override fun onServiceLost(serviceInfo: NsdServiceInfo) {
                Log.d(tag, "lost ${serviceInfo.serviceName}")
            }
        }
        discoveryListener = listener
        try {
            nsd.discoverServices(SERVICE_TYPE, NsdManager.PROTOCOL_DNS_SD, listener)
        } catch (e: Exception) {
            Log.e(tag, "discoverServices", e)
            listeners.forEach { it.onError(e.message ?: "NSD error") }
        }
    }

    fun stop() {
        discoveryListener?.let {
            try {
                nsd.stopServiceDiscovery(it)
            } catch (_: Exception) {
            }
        }
        discoveryListener = null
    }

    companion object {
        const val SERVICE_TYPE = "_mobilerun._tcp."
    }
}
