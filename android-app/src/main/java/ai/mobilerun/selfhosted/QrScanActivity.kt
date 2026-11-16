package ai.mobilerun.selfhosted

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Full-screen QR scanner for pairing links (mobilerun://pair?… or https://…/pair?…).
 */
class QrScanActivity : ComponentActivity() {
    private val tag = "QrScan"
    private val handled = AtomicBoolean(false)
    private lateinit var previewView: PreviewView

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (granted) startCamera() else finish()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        previewView = PreviewView(this)
        setContentView(previewView)
        when {
            ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) ==
                PackageManager.PERMISSION_GRANTED -> startCamera()
            else -> permissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    private fun startCamera() {
        val providerFuture = ProcessCameraProvider.getInstance(this)
        providerFuture.addListener({
            val provider = providerFuture.get()
            val preview = Preview.Builder().build().also {
                it.surfaceProvider = previewView.surfaceProvider
            }
            val analysis = ImageAnalysis.Builder()
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .build()
            val scanner = BarcodeScanning.getClient()
            analysis.setAnalyzer(ContextCompat.getMainExecutor(this)) { imageProxy ->
                if (handled.get()) {
                    imageProxy.close()
                    return@setAnalyzer
                }
                val media = imageProxy.image
                if (media == null) {
                    imageProxy.close()
                    return@setAnalyzer
                }
                val image = InputImage.fromMediaImage(media, imageProxy.imageInfo.rotationDegrees)
                scanner.process(image)
                    .addOnSuccessListener { barcodes ->
                        for (b in barcodes) {
                            val raw = b.rawValue ?: continue
                            if (b.format != Barcode.FORMAT_QR_CODE) continue
                            if (raw.contains("mobilerun://pair") || raw.contains("/pair?")) {
                                if (handled.compareAndSet(false, true)) {
                                    setResult(
                                        RESULT_OK,
                                        Intent().setData(Uri.parse(raw)),
                                    )
                                    finish()
                                }
                                break
                            }
                        }
                    }
                    .addOnFailureListener { Log.w(tag, "scan failed", it) }
                    .addOnCompleteListener { imageProxy.close() }
            }
            try {
                provider.unbindAll()
                provider.bindToLifecycle(
                    this,
                    CameraSelector.DEFAULT_BACK_CAMERA,
                    preview,
                    analysis,
                )
            } catch (e: Exception) {
                Log.e(tag, "camera bind failed", e)
                finish()
            }
        }, ContextCompat.getMainExecutor(this))
    }
}
