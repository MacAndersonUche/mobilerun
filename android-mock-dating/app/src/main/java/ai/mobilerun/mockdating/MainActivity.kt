package ai.mobilerun.mockdating

import android.os.Bundle
import android.view.GestureDetector
import android.view.MotionEvent
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import kotlin.math.abs

/**
 * Minimal fake dating UI for emulator e2e.
 *
 * Layout variants (intent extra layout_variant):
 * - default / v1: messageInput, btnSend, btnLike, btnPass, profileName
 * - v2: chatComposer, btnSendMessage, btnHeart, btnNope, nameLabel
 *   (different resource-ids → selector cache miss / rediscovery E2E)
 * - scroll_down / scroll_up / scroll_left / scroll_right:
 *   message input + Send (or matches list) start GONE; human-like swipe
 *   in the named direction reveals them (selector explore E2E).
 *
 * Verification overlay: --ez show_verification true
 */
class MainActivity : AppCompatActivity() {
    private var swipes = 0
    private var openers = 0
    private var replies = 0
    private var matched = false
    private val profiles = listOf("Alex", "Jordan", "Sam", "Riley", "Casey")
    private var idx = 0
    private var showingVerification = false
    private var layoutVariant = "v1"
    private var scrollRevealDirection: String? = null
    private var scrollsTowardReveal = 0
    private val scrollsNeeded = 2

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        layoutVariant = intent?.getStringExtra("layout_variant")?.lowercase() ?: "v1"
        scrollRevealDirection = when (layoutVariant) {
            "scroll_down" -> "down"
            "scroll_up" -> "up"
            "scroll_left" -> "left"
            "scroll_right" -> "right"
            else -> null
        }
        if (layoutVariant == "v2") {
            setContentView(R.layout.activity_main_v2)
        } else {
            setContentView(R.layout.activity_main)
        }

        val isV2 = layoutVariant == "v2"
        val name = findViewById<TextView>(
            if (isV2) R.id.nameLabel else R.id.profileName
        )
        val bio = findViewById<TextView>(R.id.profileBio)
        val stats = findViewById<TextView>(R.id.stats)
        val chat = findViewById<TextView>(R.id.chatLog)
        val input = findViewById<EditText>(
            if (isV2) R.id.chatComposer else R.id.messageInput
        )
        val mainContent = findViewById<LinearLayout>(R.id.mainContent)
        val verifyPanel = findViewById<LinearLayout>(R.id.verifyPanel)
        val verifyTitle = findViewById<TextView>(R.id.verifyTitle)
        val verifyBody = findViewById<TextView>(R.id.verifyBody)
        val btnPass = findViewById<Button>(
            if (isV2) R.id.btnNope else R.id.btnPass
        )
        val btnLike = findViewById<Button>(
            if (isV2) R.id.btnHeart else R.id.btnLike
        )
        val btnSend = findViewById<Button>(
            if (isV2) R.id.btnSendMessage else R.id.btnSend
        )

        title = "MockDating ($layoutVariant)"

        // Off-screen explore variants: hide composer/send (and expose a matches list stub)
        val matchesList = findViewById<TextView>(R.id.matchesList)
        if (scrollRevealDirection != null) {
            input.visibility = View.GONE
            btnSend.visibility = View.GONE
            matchesList?.visibility = View.GONE
            matchesList?.contentDescription = "Matches list"
            bio.text = "Swipe $scrollRevealDirection to reveal composer / matches [$layoutVariant]"
            // Ensure matches list view exists for scroll_left (matches off-screen)
            if (layoutVariant == "scroll_left" || layoutVariant == "scroll_right") {
                matchesList?.text = "Matches (hidden until swipe $scrollRevealDirection)"
            }
        }

        fun revealOffscreenTargets() {
            input.visibility = View.VISIBLE
            btnSend.visibility = View.VISIBLE
            matchesList?.visibility = View.VISIBLE
            matchesList?.text = "Matches · Alex, Jordan, Sam"
            matchesList?.contentDescription = "Matches list"
            bio.text = "Composer revealed after scroll $scrollRevealDirection"
        }

        fun refresh() {
            name.text = profiles[idx % profiles.size]
            if (scrollRevealDirection == null) {
                bio.text = "Profile #${idx + 1} — coffee, dogs, and bad jokes. [$layoutVariant]"
            }
            stats.text = "Swipes: $swipes | Openers: $openers | Replies: $replies | Scrolls: $scrollsTowardReveal"
        }

        fun showVerification(show: Boolean) {
            showingVerification = show
            if (show) {
                mainContent.visibility = View.GONE
                verifyPanel.visibility = View.VISIBLE
                verifyTitle.text = "Verify your identity"
                verifyBody.text =
                    "We noticed unusual activity on your account. " +
                        "Take a selfie to continue photo verification. " +
                        "This looks automated — complete the challenge to confirm it's you."
                verifyTitle.contentDescription = "Verify your identity"
                verifyBody.contentDescription = verifyBody.text
            } else {
                verifyPanel.visibility = View.GONE
                mainContent.visibility = View.VISIBLE
            }
        }

        btnPass.setOnClickListener {
            swipes += 1
            idx += 1
            matched = false
            refresh()
        }
        btnLike.setOnClickListener {
            swipes += 1
            matched = true
            idx += 1
            chat.append("Matched with ${name.text}!\n")
            refresh()
        }
        btnSend.setOnClickListener {
            val text = input.text?.toString()?.trim().orEmpty()
            if (text.isEmpty()) return@setOnClickListener
            if (!matched || openers == 0) {
                openers += 1
                chat.append("Opener → $text\n")
            } else {
                replies += 1
                chat.append("Reply → $text\n")
            }
            input.setText("")
            refresh()
        }
        findViewById<Button>(R.id.btnShowVerify).setOnClickListener {
            showVerification(true)
        }
        findViewById<Button>(R.id.btnDismissVerify).setOnClickListener {
            showVerification(false)
        }

        // Human-like swipe → reveal off-screen targets for explore E2E
        if (scrollRevealDirection != null) {
            val detector = GestureDetector(
                this,
                object : GestureDetector.SimpleOnGestureListener() {
                    override fun onDown(e: MotionEvent): Boolean = true

                    override fun onFling(
                        e1: MotionEvent?,
                        e2: MotionEvent,
                        velocityX: Float,
                        velocityY: Float,
                    ): Boolean {
                        if (e1 == null) return false
                        val dx = e2.x - e1.x
                        val dy = e2.y - e1.y
                        val detected = when {
                            abs(dy) > abs(dx) && dy < -80 -> "down" // finger up → content down
                            abs(dy) > abs(dx) && dy > 80 -> "up"
                            abs(dx) > abs(dy) && dx < -80 -> "right"
                            abs(dx) > abs(dy) && dx > 80 -> "left"
                            else -> null
                        }
                        if (detected == scrollRevealDirection) {
                            scrollsTowardReveal += 1
                            refresh()
                            if (scrollsTowardReveal >= scrollsNeeded) {
                                revealOffscreenTargets()
                            }
                        }
                        return true
                    }
                },
            )
            findViewById<View>(R.id.root).setOnTouchListener { _, ev ->
                detector.onTouchEvent(ev)
                true
            }
        }

        val wantVerify = intent?.getBooleanExtra("show_verification", false) == true
        showVerification(wantVerify)
        refresh()
    }
}
