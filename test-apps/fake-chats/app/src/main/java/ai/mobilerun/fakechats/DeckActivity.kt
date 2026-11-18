package ai.mobilerun.fakechats

import android.content.Intent
import android.os.Bundle
import android.os.SystemClock
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

/**
 * Swipe / Discover deck with Like / Pass / Super Like.
 *
 * Interruptions:
 *  - every 10th like → "It's a match!" (Keep swiping)
 *  - profile 25 → upsell dialog (Maybe later)
 *  - after [AppCatalog.SWIPE_TARGET] likes → "Out of likes" paywall (stop)
 */
class DeckActivity : AppCompatActivity() {
    private var index = 0
    private var likes = 0
    private lateinit var nameView: TextView
    private lateinit var bioView: TextView
    private lateinit var overlay: LinearLayout
    private var blocked = false
    private val profiles: List<Pair<String, String>> by lazy {
        (1..AppCatalog.PROFILE_POOL).map { i ->
            "Profile%02d".format(i) to "Bio for profile $i · loves hiking"
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_deck)
        val ids = FlavorIds.current()
        // Resume deck cursor across open_app relaunches so bulk-50 doesn't
        // re-like Profile01 after a SystemUI race.
        val progress = getSharedPreferences("deck_progress", MODE_PRIVATE)
        index = progress.getInt("index", 0).coerceIn(0, profiles.size)
        likes = progress.getInt("likes", 0).coerceAtLeast(0)
        if (intent?.getBooleanExtra("clear_log", false) == true) {
            SentLog.clear(this)
            SwipeLog.clear(this)
            TimingLog.clear(this)
            MatchStore.clear(this)
            index = 0
            likes = 0
            progress.edit().clear().apply()
        }

        findViewById<View>(R.id.deck_card).remapId(this, ids.deckCard)
        nameView = findViewById(R.id.deck_profile_name)
        nameView.remapId(this, ids.profileName)
        bioView = findViewById(R.id.deck_profile_bio)
        val like = findViewById<Button>(R.id.btn_like)
        like.remapId(this, ids.like)
        val pass = findViewById<Button>(R.id.btn_pass)
        pass.remapId(this, ids.pass)
        val superLike = findViewById<Button>(R.id.btn_superlike)
        superLike.remapId(this, ids.superLike)
        val matchesBtn = findViewById<Button>(R.id.btn_matches)
        matchesBtn.remapId(this, ids.matchesTab)

        overlay = findViewById(R.id.dialog_overlay)
        MatchStore.seedIfNeeded(this)
        showProfile()

        like.setOnClickListener { swipe("like") }
        superLike.setOnClickListener { swipe("superlike") }
        pass.setOnClickListener { swipe("pass") }
        matchesBtn.setOnClickListener {
            startActivity(Intent(this, MatchesActivity::class.java))
        }
        findViewById<Button>(R.id.btn_chat_tab).setOnClickListener {
            startActivity(Intent(this, InboxActivity::class.java))
        }
    }

    private fun showProfile() {
        if (index >= profiles.size) {
            showDialog(
                "End of deck",
                "No more profiles",
                primary = "OK",
                secondary = null,
                onPrimary = { finish() },
            )
            return
        }
        val (name, bio) = profiles[index]
        nameView.text = name
        bioView.text = bio
        nameView.contentDescription = "Profile $name"
    }

    private fun swipe(action: String) {
        if (blocked) return
        if (index >= profiles.size) return
        val t0 = SystemClock.elapsedRealtime()
        val (name, _) = profiles[index]
        // Out of likes after exactly SWIPE_TARGET likes (next like blocked)
        if (action != "pass" && likes >= AppCatalog.SWIPE_TARGET) {
            showDialog(
                "Out of likes",
                "You're out of likes. Come back later or upgrade.",
                primary = "Maybe later",
                secondary = "See plans",
                onPrimary = {
                    TimingLog.record(this, "out_of_likes_stop", 0, name)
                    blocked = true
                },
                onSecondary = {
                    TimingLog.record(this, "paywall_upsell", 0, name)
                    blocked = true
                },
            )
            return
        }

        SwipeLog.record(this, name, action, index)
        TimingLog.record(this, "swipe_$action", SystemClock.elapsedRealtime() - t0, name)
        if (action != "pass") {
            likes += 1
            MatchStore.add(this, name)
        }
        val likedIndex = index
        index += 1
        getSharedPreferences("deck_progress", MODE_PRIVATE)
            .edit()
            .putInt("index", index)
            .putInt("likes", likes)
            .commit()

        // Upsell mid-deck
        if (likedIndex + 1 == 25 && action != "pass") {
            showDialog(
                "Get more likes",
                "Upgrade for unlimited likes",
                primary = "Maybe later",
                secondary = "See plans",
                onPrimary = { showProfile() },
                onSecondary = { showProfile() },
            )
            return
        }
        // It's a match every 10th like
        if (action != "pass" && likes % 10 == 0) {
            showDialog(
                "It's a match!",
                "You and $name liked each other",
                primary = "Keep swiping",
                secondary = "Send message",
                onPrimary = { showProfile() },
                onSecondary = {
                    startActivity(
                        Intent(this, ConversationActivity::class.java)
                            .putExtra(ConversationActivity.EXTRA_CONTACT, name),
                    )
                },
            )
            return
        }
        showProfile()
    }

    private fun showDialog(
        title: String,
        body: String,
        primary: String,
        secondary: String?,
        onPrimary: () -> Unit,
        onSecondary: (() -> Unit)? = null,
    ) {
        overlay.visibility = View.VISIBLE
        findViewById<TextView>(R.id.dialog_title).text = title
        findViewById<TextView>(R.id.dialog_title).contentDescription = title
        findViewById<TextView>(R.id.dialog_body).text = body
        val p = findViewById<Button>(R.id.dialog_primary)
        p.text = primary
        p.contentDescription = primary
        p.setOnClickListener {
            overlay.visibility = View.GONE
            onPrimary()
        }
        val s = findViewById<Button>(R.id.dialog_secondary)
        if (secondary == null) {
            s.visibility = View.GONE
        } else {
            s.visibility = View.VISIBLE
            s.text = secondary
            s.contentDescription = secondary
            s.setOnClickListener {
                overlay.visibility = View.GONE
                onSecondary?.invoke()
            }
        }
    }
}
