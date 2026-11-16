package ai.mobilerun.mockdating

import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

/**
 * Minimal fake dating UI for emulator e2e.
 *
 * Layout variants (intent extra layout_variant):
 * - default / v1: messageInput, btnSend, btnLike, btnPass, profileName
 * - v2: chatComposer, btnSendMessage, btnHeart, btnNope, nameLabel
 *   (different resource-ids → selector cache miss / rediscovery E2E)
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

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        layoutVariant = intent?.getStringExtra("layout_variant")?.lowercase() ?: "v1"
        if (layoutVariant == "v2") {
            setContentView(R.layout.activity_main_v2)
        } else {
            setContentView(R.layout.activity_main)
        }

        val name = findViewById<TextView>(
            if (layoutVariant == "v2") R.id.nameLabel else R.id.profileName
        )
        val bio = findViewById<TextView>(R.id.profileBio)
        val stats = findViewById<TextView>(R.id.stats)
        val chat = findViewById<TextView>(R.id.chatLog)
        val input = findViewById<EditText>(
            if (layoutVariant == "v2") R.id.chatComposer else R.id.messageInput
        )
        val mainContent = findViewById<LinearLayout>(R.id.mainContent)
        val verifyPanel = findViewById<LinearLayout>(R.id.verifyPanel)
        val verifyTitle = findViewById<TextView>(R.id.verifyTitle)
        val verifyBody = findViewById<TextView>(R.id.verifyBody)
        val btnPass = findViewById<Button>(
            if (layoutVariant == "v2") R.id.btnNope else R.id.btnPass
        )
        val btnLike = findViewById<Button>(
            if (layoutVariant == "v2") R.id.btnHeart else R.id.btnLike
        )
        val btnSend = findViewById<Button>(
            if (layoutVariant == "v2") R.id.btnSendMessage else R.id.btnSend
        )

        // Expose variant for a11y / dumpsys debugging
        title = "MockDating ($layoutVariant)"

        fun refresh() {
            name.text = profiles[idx % profiles.size]
            bio.text = "Profile #${idx + 1} — coffee, dogs, and bad jokes. [$layoutVariant]"
            stats.text = "Swipes: $swipes | Openers: $openers | Replies: $replies"
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

        val wantVerify = intent?.getBooleanExtra("show_verification", false) == true
        showVerification(wantVerify)
        refresh()
    }
}
