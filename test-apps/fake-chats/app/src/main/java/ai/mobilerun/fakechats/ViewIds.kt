package ai.mobilerun.fakechats

import android.content.Context
import android.view.View

/** Remap a view's id to a flavor-specific R.id name so a11y dumps match real apps. */
fun View.remapId(context: Context, name: String) {
    val rid = context.resources.getIdentifier(name, "id", context.packageName)
    if (rid != 0) {
        id = rid
    }
}
