package ai.mobilerun.fakechats

import android.os.Bundle
import android.view.LayoutInflater
import android.view.inputmethod.EditorInfo
import android.widget.EditText
import android.widget.ImageButton
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

/**
 * Conversation with an OLD outgoing bubble already containing the target text
 * ("hi baby"). Send appends a NEW bubble + [SentLog] entry so tests can assert
 * a new outgoing message, not the seed bubble.
 */
class ConversationActivity : AppCompatActivity() {
    companion object {
        const val EXTRA_CONTACT = "contact"
        const val EXTRA_FROM_SEARCH = "from_search"
        const val EXTRA_ROW_INDEX = "row_index"
    }

    private lateinit var contact: String
    private lateinit var bubbles: LinearLayout
    private lateinit var chatLog: ScrollView
    private var outgoingCount = 0

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_conversation)
        val ids = FlavorIds.current()
        contact = intent.getStringExtra(EXTRA_CONTACT) ?: getString(R.string.contact_precious)

        findId<TextView>(ids.header).text = contact
        bubbles = findViewById(R.id.bubbles)
        chatLog = findId(ids.chatLog)

        // Seed: old outgoing bubble with the same text we will send again.
        addOutgoingBubble(getString(R.string.old_bubble_text), seed = true)

        val compose = findId<EditText>(ids.compose)
        val send = findId<ImageButton>(ids.send)

        fun doSend() {
            val text = compose.text?.toString()?.trim().orEmpty()
            if (text.isEmpty()) return
            addOutgoingBubble(text, seed = false)
            SentLog.append(this, contact, text, via = "send_button")
            compose.setText("")
            // Keep compose focused; soft keyboard may cover send (tricky case).
            compose.requestFocus()
        }

        send.setOnClickListener { doSend() }
        compose.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_SEND) {
                doSend()
                true
            } else {
                false
            }
        }
        compose.requestFocus()
    }

    private fun addOutgoingBubble(text: String, seed: Boolean) {
        val ids = FlavorIds.current()
        val row = LayoutInflater.from(this).inflate(R.layout.item_outgoing_bubble, bubbles, false)
        val tv = row.findViewById<TextView>(id(ids.bubbleOut))
        tv.text = text
        // Distinguish seed vs new for a11y/tests without breaking text match.
        tv.contentDescription =
            if (seed) {
                "Old outgoing message: $text"
            } else {
                outgoingCount += 1
                "New outgoing message $outgoingCount: $text"
            }
        // Tag for instrumentation
        tv.tag = if (seed) "seed" else "new_$outgoingCount"
        bubbles.addView(row)
        chatLog.post { chatLog.fullScroll(ScrollView.FOCUS_DOWN) }
    }
}
