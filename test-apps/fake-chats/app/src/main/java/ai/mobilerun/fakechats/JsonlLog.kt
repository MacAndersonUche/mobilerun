package ai.mobilerun.fakechats

import android.content.Context
import org.json.JSONObject
import java.io.File

open class JsonlLog(private val fileName: String) {
    fun file(context: Context): File = File(context.filesDir, fileName)

    fun clear(context: Context) {
        file(context).writeText("")
    }

    fun append(context: Context, obj: JSONObject) {
        file(context).appendText(obj.toString() + "\n")
    }

    fun readAll(context: Context): List<JSONObject> {
        val f = file(context)
        if (!f.exists()) return emptyList()
        return f.readLines().filter { it.isNotBlank() }.map { JSONObject(it) }
    }
}

object SwipeLog : JsonlLog("swipes.jsonl") {
    fun record(
        context: Context,
        profile: String,
        action: String,
        index: Int,
    ) {
        append(
            context,
            JSONObject()
                .put("ts", System.currentTimeMillis())
                .put("flavor", BuildConfig.FLAVOR_KEY)
                .put("package", context.packageName)
                .put("profile", profile)
                .put("action", action)
                .put("index", index),
        )
    }
}

object TimingLog : JsonlLog("action_timings.jsonl") {
    fun record(
        context: Context,
        kind: String,
        ms: Long,
        meta: String = "",
    ) {
        append(
            context,
            JSONObject()
                .put("ts", System.currentTimeMillis())
                .put("flavor", BuildConfig.FLAVOR_KEY)
                .put("kind", kind)
                .put("ms", ms)
                .put("meta", meta),
        )
    }
}

object MatchStore {
    private const val PREF = "match_store"

    fun seedIfNeeded(context: Context) {
        val prefs = context.getSharedPreferences(PREF, Context.MODE_PRIVATE)
        if (prefs.getBoolean("seeded", false)) return
        val names =
            mutableSetOf("Precious Achalugo") +
                (1..AppCatalog.MATCH_POOL).map { i -> "Match%02d".format(i) }
        prefs.edit().putStringSet("matches", names).putBoolean("seeded", true).apply()
    }

    fun all(context: Context): List<String> {
        seedIfNeeded(context)
        val prefs = context.getSharedPreferences(PREF, Context.MODE_PRIVATE)
        val names = prefs.getStringSet("matches", emptySet())!!.toMutableList()
        // Keep Precious first so single-DM benches do not need to scroll.
        names.sort()
        val precious = "Precious Achalugo"
        if (names.remove(precious)) {
            names.add(0, precious)
        }
        return names
    }

    fun add(context: Context, name: String) {
        seedIfNeeded(context)
        val prefs = context.getSharedPreferences(PREF, Context.MODE_PRIVATE)
        val set = prefs.getStringSet("matches", emptySet())!!.toMutableSet()
        set.add(name)
        prefs.edit().putStringSet("matches", set).apply()
    }

    fun clear(context: Context) {
        context.getSharedPreferences(PREF, Context.MODE_PRIVATE).edit().clear().apply()
        seedIfNeeded(context)
    }
}
