package ai.mobilerun.fakechats

import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.widget.Button
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

        if (intent?.getBooleanExtra("clear_log", true) == true) {
            SentLog.clear(this)
            SwipeLog.clear(this)
            TimingLog.clear(this)
        }

        val searchBtn = findViewById<ImageButton>(R.id.menuitem_search)
        searchBtn.remapId(this, ids.searchMenu)
        searchBtn.setOnClickListener {
            startActivity(Intent(this, SearchActivity::class.java))
        }

        val discover = findViewById<Button>(R.id.dating_home_tab)
        if (BuildConfig.FAMILY == "swipe" || BuildConfig.FAMILY == "facebook_dating") {
            discover.visibility = View.VISIBLE
            discover.setOnClickListener {
                startActivity(Intent(this, DeckActivity::class.java))
            }
        }

        val list = findViewById<LinearLayout>(R.id.contact_list)
        val contacts =
            listOf(
                getString(R.string.contact_other),
                getString(R.string.contact_precious),
                getString(R.string.contact_precious_dup),
            )
        val inflater = LayoutInflater.from(this)
        for ((index, name) in contacts.withIndex()) {
            val row = inflater.inflate(R.layout.item_contact_row, list, false)
            row.remapId(this, ids.contactRow)
            val tv = row.findViewById<TextView>(R.id.conversations_row_contact_name)
            tv.remapId(this, ids.contactName)
            tv.text = name
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
    }
}
