package ai.mobilerun.fakechats

import android.content.Intent
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity

/** Routes to inbox / swipe deck / Secure Folder based on flavor family. */
class LauncherActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (intent?.getBooleanExtra("clear_log", false) == true) {
            SentLog.clear(this)
            SwipeLog.clear(this)
            TimingLog.clear(this)
            MatchStore.clear(this)
        }
        val target =
            when (BuildConfig.FAMILY) {
                "swipe", "facebook_dating" -> DeckActivity::class.java
                "secure_folder" -> SecureFolderActivity::class.java
                else -> InboxActivity::class.java
            }
        startActivity(
            Intent(this, target).putExtras(intent?.extras ?: Bundle.EMPTY),
        )
        finish()
    }
}
