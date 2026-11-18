package ai.mobilerun.fakechats

import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.widget.ImageButton
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

/**
 * Chat list. Includes duplicate "Precious Achalugo" rows (tricky case) plus
 * another contact. Search opens [SearchActivity].
 */
class InboxActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_inbox)
        val ids = FlavorIds.current()

        // Clear sent log when app cold-starts (CI installs fresh each matrix case
        // can also call FakeChatsClear via adb am).
        if (intent?.getBooleanExtra("clear_log", true) == true) {
            SentLog.clear(this)
        }

        val list = findViewById<LinearLayout>(R.id.contact_list)
        val contacts =
            listOf(
                getString(R.string.contact_other),
                getString(R.string.contact_precious),
                // Duplicate exact name — agent must tap a result row, not keep typing.
                getString(R.string.contact_precious_dup),
            )
        val inflater = LayoutInflater.from(this)
        for ((index, name) in contacts.withIndex()) {
            val row = inflater.inflate(R.layout.item_contact_row, list, false)
            // Ensure clickable container uses flavor contact_row id when present
            row.findViewById<TextView>(id(ids.contactName)).text = name
            row.contentDescription = "Chat with $name"
            row.setOnClickListener {
                startActivity(
                    Intent(this, ConversationActivity::class.java)
                        .putExtra(ConversationActivity.EXTRA_CONTACT, name)
                        .putExtra(ConversationActivity.EXTRA_ROW_INDEX, index),
                )
            }
            list.addView(row)
        }

        findId<ImageButton>(ids.searchMenu).setOnClickListener {
            startActivity(Intent(this, SearchActivity::class.java))
        }
    }
}
