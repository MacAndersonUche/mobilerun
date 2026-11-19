package ai.mobilerun.fakechats

import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

/** Matches / connections list used for bulk-message 50 scenarios. */
class MatchesActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_matches)
        val ids = FlavorIds.current()
        MatchStore.seedIfNeeded(this)

        findViewById<TextView>(R.id.matches_title).text = "Matches"
        val search = findViewById<EditText>(R.id.matches_search_input)
        search.remapId(this, ids.searchInput)
        search.hint = "Search matches"
        // Keep focus sticky (tricky) — tests must not type message text here.
        search.requestFocus()

        val list = findViewById<LinearLayout>(R.id.matches_list)
        val inflater = LayoutInflater.from(this)
        for (name in MatchStore.all(this)) {
            val row = inflater.inflate(R.layout.item_contact_row, list, false)
            row.remapId(this, ids.matchRow)
            val tv = row.findViewById<TextView>(id("conversations_row_contact_name"))
            tv.remapId(this, ids.matchName)
            tv.text = name
            row.contentDescription = "Match $name"
            row.setOnClickListener {
                startActivity(
                    Intent(this, ConversationActivity::class.java)
                        .putExtra(ConversationActivity.EXTRA_CONTACT, name),
                )
            }
            list.addView(row)
        }
    }
}
