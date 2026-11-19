package ai.mobilerun.fakechats

import android.content.Context
import org.json.JSONObject
import java.io.File

/** Append-only log of outgoing messages for CI assertions. */
object SentLog {
    private const val FILE = "sent_messages.jsonl"

    fun file(context: Context): File = File(context.filesDir, FILE)

    fun clear(context: Context) {
        file(context).writeText("")
    }

    fun append(
        context: Context,
        contact: String,
        text: String,
        via: String = "send_button",
    ) {
        val line =
            JSONObject()
                .put("ts", System.currentTimeMillis())
                .put("flavor", BuildConfig.FLAVOR_KEY)
                .put("package", context.packageName)
                .put("contact", contact)
                .put("text", text)
                .put("via", via)
                .toString()
        file(context).appendText(line + "\n")
    }

    fun readAll(context: Context): List<JSONObject> {
        val f = file(context)
        if (!f.exists()) return emptyList()
        return f.readLines().filter { it.isNotBlank() }.map { JSONObject(it) }
    }

    fun countExact(
        context: Context,
        contact: String,
        text: String,
    ): Int =
        readAll(context).count {
            it.optString("contact") == contact && it.optString("text") == text
        }
}
