package ai.mobilerun.fakechats

import android.app.Activity
import android.os.Bundle

/** adb: am start -n \$pkg/ai.mobilerun.fakechats.ClearLogActivity */
class ClearLogActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        SentLog.clear(this)
        finish()
    }
}
