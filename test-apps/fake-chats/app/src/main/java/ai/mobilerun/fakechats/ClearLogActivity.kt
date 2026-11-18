package ai.mobilerun.fakechats

import android.app.Activity
import android.os.Bundle

class ClearLogActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        SentLog.clear(this)
        SwipeLog.clear(this)
        TimingLog.clear(this)
        MatchStore.clear(this)
        getSharedPreferences("deck_progress", MODE_PRIVATE).edit().clear().apply()
        finish()
    }
}
