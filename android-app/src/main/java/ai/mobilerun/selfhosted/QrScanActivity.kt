package ai.mobilerun.selfhosted

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.util.Log
import android.view.Gravity
import android.widget.FrameLayout
import android.widget.ImageButton
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.FocusMeteringAction
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.core.SurfaceOrientedMeteringPointFactory
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Full-screen QR scanner for pairing links:
 * https://…/p/CODE · mobilerun://pair?c=… · /pair?token=…
 */
class QrScanActivity : ComponentActivity() {
    private val tag = "QrScan"
    private val handled = AtomicBoolean(false)
    private lateinit var previewView: PreviewView
    private var camera: Camera? = null
    private var torchOn = false

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (granted) {
            startCamera()
        } else {
            Toast.makeText(this, "Camera permission is required to scan QR", Toast.LENGTH_LONG).show()
            finish()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = FrameLayout(this)
        previewView = PreviewView(this).also {
            it.implementationMode = PreviewView.ImplementationMode.COMPATIBLE
            it.scaleType = PreviewView.ScaleType.FILL_CENTER
        }
        root.addView(
            previewView,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT,
            ),
        )
        val torchBtn = ImageButton(this).apply {
            setImageResource(android.R.drawable.ic_menu_camera)
            contentDescription = "Toggle torch"
            setBackgroundColor(0x66000000)
            setOnClickListener { toggleTorch() }
        }
        val lp = FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.WRAP_CONTENT,
            FrameLayout.LayoutParams.WRAP_CONTENT,
            Gravity.BOTTOM or Gravity.END,
        )
        lp.setMargins(32, 32, 32, 64)
        root.addView(torchBtn, lp)
        setContentView(root)

        when {
            ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) ==
                PackageManager.PERMISSION_GRANTED -> startCamera()
            else -> permissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    private fun toggleTorch() {
        val cam = camera ?: return
        if (!cam.cameraInfo.hasFlashUnit()) {
            Toast.makeText(this, "No torch on this camera", Toast.LENGTH_SHORT).show()
            return
        }
        torchOn = !torchOn
        cam.cameraControl.enableTorch(torchOn)
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
                .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_YUV_420_888)
                .build()
            val options = BarcodeScannerOptions.Builder()
                .setBarcodeFormats(Barcode.FORMAT_QR_CODE)
                .build()
            val scanner = BarcodeScanning.getClient(options)
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
                            if (looksLikePair(raw) && handled.compareAndSet(false, true)) {
                                val uri = Uri.parse(raw.trim())
                                setResult(RESULT_OK, Intent().setData(uri))
                                finish()
                                break
                            }
                        }
                    }
                    .addOnFailureListener { Log.w(tag, "scan failed", it) }
                    .addOnCompleteListener { imageProxy.close() }
            }
            try {
                provider.unbindAll()
                camera = provider.bindToLifecycle(
                    this,
                    CameraSelector.DEFAULT_BACK_CAMERA,
                    preview,
                    analysis,
                )
                // Continuous autofocus toward center — helps laptop-screen QRs
                previewView.post {
                    try {
                        val factory = SurfaceOrientedMeteringPointFactory(
                            previewView.width.toFloat(),
                            previewView.height.toFloat(),
                        )
                        val point = factory.createPoint(
                            previewView.width / 2f,
                            previewView.height / 2f,
                        )
                        val action = FocusMeteringAction.Builder(point, FocusMeteringAction.FLAG_AF)
                            .setAutoCancelDuration(3, TimeUnit.SECONDS)
                            .build()
                        camera?.cameraControl?.startFocusAndMetering(action)
                    } catch (e: Exception) {
                        Log.w(tag, "autofocus: ${e.message}")
                    }
                }
            } catch (e: Exception) {
                Log.e(tag, "camera bind failed", e)
                Toast.makeText(this, "Camera failed: ${e.message}", Toast.LENGTH_LONG).show()
                finish()
            }
        }, ContextCompat.getMainExecutor(this))
    }

    companion object {
        fun looksLikePair(raw: String): Boolean {
            val r = raw.trim()
            if (r.contains("mobilerun://pair")) return true
            if (Regex("""(?i)/p/[A-Z0-9]{6,12}""").containsMatchIn(r)) return true
            if (r.contains("/pair?") || r.contains("/pair/")) return true
            if (r.contains("c=") || r.contains("token=")) {
                return r.contains("pair") || r.contains("mobilerun") || r.contains("/p/")
            }
            // Bare short code from some scanners
            if (Regex("""^[A-Z0-9]{6,8}$""", RegexOption.IGNORE_CASE).matches(r)) return true
            return false
        }
    }
}
