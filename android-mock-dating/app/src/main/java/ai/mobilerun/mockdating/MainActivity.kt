package ai.mobilerun.mockdating

import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

/**
 * Minimal fake dating UI for emulator e2e:
 * swipe/like/pass, type message, send opener/reply, visible counters.
 */
class MainActivity : AppCompatActivity() {
    private var swipes = 0
    private var openers = 0
    private var replies = 0
    private var matched = false
    private val profiles = listOf("Alex", "Jordan", "Sam", "Riley", "Casey")
    private var idx = 0

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        val name = findViewById<TextView>(R.id.profileName)
        val bio = findViewById<TextView>(R.id.profileBio)
        val stats = findViewById<TextView>(R.id.stats)
        val chat = findViewById<TextView>(R.id.chatLog)
        val input = findViewById<EditText>(R.id.messageInput)

        fun refresh() {
            name.text = profiles[idx % profiles.size]
            bio.text = "Profile #${idx + 1} — coffee, dogs, and bad jokes."
            stats.text = "Swipes: $swipes | Openers: $openers | Replies: $replies"
        }

        findViewById<Button>(R.id.btnPass).setOnClickListener {
            swipes += 1
            idx += 1
            matched = false
            refresh()
        }
        findViewById<Button>(R.id.btnLike).setOnClickListener {
            swipes += 1
            matched = true
            idx += 1
            chat.append("Matched with ${name.text}!\n")
            refresh()
        }
        findViewById<Button>(R.id.btnSend).setOnClickListener {
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
        refresh()
    }
}
