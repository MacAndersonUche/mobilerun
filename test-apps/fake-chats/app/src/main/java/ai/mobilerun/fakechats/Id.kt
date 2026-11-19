package ai.mobilerun.fakechats

import android.app.Activity
import android.content.Context
import android.view.View

fun Context.id(name: String): Int =
    resources.getIdentifier(name, "id", packageName)

fun <T : View> Activity.findId(name: String): T =
    findViewById(id(name))
