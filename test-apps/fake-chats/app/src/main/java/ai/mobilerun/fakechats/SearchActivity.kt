package ai.mobilerun.fakechats

import android.content.Intent
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.LayoutInflater
import android.view.inputmethod.EditorInfo
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

/**
 * Search screen. Keeps focus on the search field after typing (tricky case).
 * Result rows are distinct from the search EditText so the agent must tap a row.
 */
class SearchActivity : AppCompatActivity() {
    private val allContacts by lazy {
        listOf(
            getString(R.string.contact_other),
            getString(R.string.contact_precious),
            getString(R.string.contact_precious_dup),
        )
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_search)
        val ids = FlavorIds.current()
        val input = findId<EditText>(ids.searchInput)
        val results = findViewById<LinearLayout>(R.id.search_results)

        fun render(query: String) {
            results.removeAllViews()
            val q = query.trim().lowercase()
            val matches =
                if (q.isEmpty()) {
                    emptyList()
                } else {
                    allContacts.filter { it.lowercase().contains(q) }
                }
            val inflater = LayoutInflater.from(this)
            for ((index, name) in matches.withIndex()) {
                val row = inflater.inflate(R.layout.item_contact_row, results, false)
                row.findViewById<TextView>(id(ids.contactName)).text = name
                row.contentDescription = "Search result $name"
                row.isClickable = true
                row.isFocusable = true
                row.setOnClickListener {
                    // Deliberately do NOT clear search focus before navigate —
                    // conversation open is the success signal.
                    startActivity(
                        Intent(this, ConversationActivity::class.java)
                            .putExtra(ConversationActivity.EXTRA_CONTACT, name)
                            .putExtra(ConversationActivity.EXTRA_FROM_SEARCH, true)
                            .putExtra(ConversationActivity.EXTRA_ROW_INDEX, index),
                    )
                }
                results.addView(row)
            }
            // Keep search focused after every keystroke (tricky case).
            input.requestFocus()
        }

        input.addTextChangedListener(
            object : TextWatcher {
                override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
                override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                    render(s?.toString().orEmpty())
                }
                override fun afterTextChanged(s: Editable?) {}
            },
        )
        input.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_SEARCH) {
                render(input.text?.toString().orEmpty())
                input.requestFocus()
                true
            } else {
                false
            }
        }
        input.requestFocus()
        render("")
    }
}
