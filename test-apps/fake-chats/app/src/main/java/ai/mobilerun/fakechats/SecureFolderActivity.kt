package ai.mobilerun.fakechats

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import org.json.JSONObject

/**
 * Fake Samsung Secure Folder gate. Unlock reveals installed Mobilerun fake
 * dating/social packages for launch — covers the Secure Folder path without
 * real Knox.
 */
class SecureFolderActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_secure_folder)
        val unlock = findViewById<Button>(R.id.secure_unlock)
        unlock.contentDescription = "Unlock Secure Folder"
        val list = findViewById<LinearLayout>(R.id.secure_app_list)
        unlock.setOnClickListener {
            TimingLog.record(this, "secure_folder_unlock", 0)
            unlock.visibility = View.GONE
            list.visibility = View.VISIBLE
            findViewById<TextView>(R.id.secure_title).text = "Secure Folder · Unlocked"
            populate(list)
        }
    }

    private fun populate(list: LinearLayout) {
        list.removeAllViews()
        for (app in readCatalogApps()) {
            if (app.optString("family") == "secure_folder") continue
            if (!app.optBoolean("secure_folder", true)) continue
            val pkg = app.optString("package")
            val label = app.optString("label")
            val row = TextView(this)
            row.text = label
            row.textSize = 18f
            row.setPadding(24, 32, 24, 32)
            row.isClickable = true
            row.contentDescription = "Open $label"
            row.setOnClickListener {
                val launch = packageManager.getLaunchIntentForPackage(pkg)
                if (launch != null) {
                    launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    startActivity(launch)
                }
            }
            list.addView(row)
        }
    }

    private fun readCatalogApps(): List<JSONObject> =
        try {
            val raw = assets.open("catalog.json").bufferedReader().use { it.readText() }
            val root = JSONObject(raw)
            val arr = root.getJSONArray("apps")
            (0 until arr.length()).map { arr.getJSONObject(it) }
        } catch (_: Exception) {
            emptyList()
        }
}
