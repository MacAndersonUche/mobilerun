#!/usr/bin/env python3
"""Generate Gradle flavors, ids.xml, and FlavorIds.kt from catalog.json."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "catalog.json").read_text())

# Per-family default resource-id stems (overridden lightly per app for uniqueness)
FAMILY_IDS = {
    "messaging": {
        "searchMenu": "menuitem_search",
        "searchInput": "search_src_text",
        "contactRow": "contact_row_container",
        "contactName": "conversations_row_contact_name",
        "header": "conversation_contact_name",
        "compose": "entry",
        "send": "send",
        "chatLog": "chat_list",
        "bubbleOut": "message_text",
        "like": "gamepad_like",
        "pass": "gamepad_pass",
        "superLike": "gamepad_superlike",
        "deckCard": "recs_card_stack",
        "profileName": "recs_card_user_name",
        "matchesTab": "tab_matches",
        "matchRow": "match_row",
        "matchName": "match_name",
    },
    "facebook_dating": {
        "searchMenu": "dating_search",
        "searchInput": "dating_search_edit",
        "contactRow": "dating_inbox_row",
        "contactName": "dating_inbox_name",
        "header": "dating_thread_title",
        "compose": "dating_composer",
        "send": "dating_send",
        "chatLog": "dating_message_list",
        "bubbleOut": "dating_bubble_text",
        "like": "dating_like",
        "pass": "dating_pass",
        "superLike": "dating_superlike",
        "deckCard": "dating_card",
        "profileName": "dating_card_name",
        "matchesTab": "dating_matches_tab",
        "matchRow": "dating_match_row",
        "matchName": "dating_match_name",
    },
    "swipe": {
        "searchMenu": "matches_search",
        "searchInput": "matches_search_input",
        "contactRow": "match_row",
        "contactName": "match_name",
        "header": "chat_header_name",
        "compose": "message_input",
        "send": "send_button",
        "chatLog": "chat_recycler",
        "bubbleOut": "bubble_text",
        "like": "gamepad_like",
        "pass": "gamepad_pass",
        "superLike": "gamepad_superlike",
        "deckCard": "recs_card_stack",
        "profileName": "recs_card_user_name",
        "matchesTab": "tab_matches",
        "matchRow": "match_row",
        "matchName": "match_name",
    },
    "secure_folder": {
        "searchMenu": "sf_search",
        "searchInput": "sf_search_input",
        "contactRow": "sf_app_row",
        "contactName": "sf_app_name",
        "header": "sf_header",
        "compose": "sf_unused_compose",
        "send": "sf_unused_send",
        "chatLog": "sf_list",
        "bubbleOut": "sf_unused_bubble",
        "like": "sf_unused_like",
        "pass": "sf_unused_pass",
        "superLike": "sf_unused_super",
        "deckCard": "sf_unused_deck",
        "profileName": "sf_unused_profile",
        "matchesTab": "sf_unused_matches",
        "matchRow": "sf_app_row",
        "matchName": "sf_app_name",
    },
}

# Distinct overrides so apps don't all share identical id strings
OVERRIDES = {
    "whatsapp": {},
    "instagram": {
        "searchMenu": "search_tab",
        "searchInput": "search_edit_text",
        "contactRow": "row_inbox_container",
        "contactName": "row_inbox_username",
        "header": "thread_title",
        "compose": "row_thread_composer_edittext",
        "send": "row_thread_composer_button_send",
        "chatLog": "thread_message_list",
        "bubbleOut": "direct_message_text",
    },
    "messenger": {
        "searchMenu": "search_button",
        "searchInput": "search_edit_text",
        "contactRow": "thread_list_item",
        "contactName": "thread_title",
        "header": "thread_title_view",
        "compose": "composer_text",
        "send": "composer_send_button",
        "chatLog": "message_list",
        "bubbleOut": "message_bubble_text",
    },
    "telegram": {
        "searchMenu": "search_item",
        "searchInput": "search_field",
        "contactRow": "dialog_row",
        "contactName": "dialog_title",
        "header": "action_bar_title",
        "compose": "chat_message_edit",
        "send": "chat_send_button",
        "chatLog": "chat_list_view",
        "bubbleOut": "message_text",
    },
    "tinder": {
        "like": "gamepad_like",
        "pass": "gamepad_pass",
        "superLike": "gamepad_superlike",
    },
    "bumble": {
        "searchMenu": "connections_search",
        "searchInput": "connections_search_input",
        "contactRow": "connection_row",
        "contactName": "connection_name",
        "header": "chat_title",
        "compose": "message_box",
        "send": "send_cta",
        "chatLog": "messages_list",
        "bubbleOut": "outgoing_text",
        "like": "encounter_like",
        "pass": "encounter_pass",
        "matchesTab": "tab_connections",
        "matchRow": "connection_row",
        "matchName": "connection_name",
    },
    "hinge": {
        "searchMenu": "likes_search",
        "searchInput": "likes_search_input",
        "contactRow": "like_row",
        "contactName": "like_name",
        "header": "conversation_title",
        "compose": "your_message",
        "send": "send_message",
        "chatLog": "conversation_list",
        "bubbleOut": "sent_text",
        "like": "like_button",
        "pass": "skip_button",
        "matchesTab": "tab_likes",
        "matchRow": "like_row",
        "matchName": "like_name",
    },
    "hily": {"like": "hily_like", "pass": "hily_pass", "profileName": "hily_card_name"},
    "breeze": {
        "like": "breeze_like",
        "pass": "breeze_pass",
        "profileName": "breeze_name",
    },
    "taimi": {"like": "taimi_like", "pass": "taimi_pass"},
    "tagged": {"like": "tagged_like", "pass": "tagged_pass"},
    "blk": {"like": "blk_like", "pass": "blk_pass"},
    "yubo": {"like": "yubo_like", "pass": "yubo_pass"},
    "pure": {"like": "pure_like", "pass": "pure_pass"},
    "boo": {"like": "boo_like", "pass": "boo_pass"},
    "jaumo": {"like": "jaumo_like", "pass": "jaumo_pass"},
    "happn": {"like": "happn_like", "pass": "happn_pass"},
    "wild": {"like": "wild_like", "pass": "wild_pass"},
    "threef": {"like": "threef_like", "pass": "threef_pass"},
    "meetme": {"like": "meetme_like", "pass": "meetme_pass"},
    "okcupid": {"like": "okc_like", "pass": "okc_pass"},
    "badoo": {"like": "badoo_like", "pass": "badoo_pass"},
    "feeld": {"like": "feeld_like", "pass": "feeld_pass"},
    "pof": {"like": "pof_like", "pass": "pof_pass"},
}


def ids_for(app: dict) -> dict:
    base = dict(FAMILY_IDS[app["family"]])
    base.update(OVERRIDES.get(app["key"], {}))
    # Prefix non-core apps' match ids lightly for uniqueness when still swipe-family defaults
    if app["family"] == "swipe" and app["key"] not in ("tinder", "bumble", "hinge"):
        base.setdefault("matchRow", f"{app['key']}_match_row")
        base.setdefault("matchName", f"{app['key']}_match_name")
        base.setdefault("matchesTab", f"{app['key']}_matches_tab")
    return base


def main() -> None:
    apps = CATALOG["apps"]
    all_id_names: set[str] = set()
    for app in apps:
        all_id_names.update(ids_for(app).values())
    # Generic layout placeholders
    all_id_names.update(
        {
            "root_inbox",
            "inbox_title",
            "contact_list",
            "root_deck",
            "deck_card",
            "deck_profile_name",
            "deck_profile_bio",
            "btn_like",
            "btn_pass",
            "btn_superlike",
            "btn_matches",
            "btn_chat_tab",
            "dialog_overlay",
            "dialog_title",
            "dialog_body",
            "dialog_primary",
            "dialog_secondary",
            "root_matches",
            "matches_list",
            "matches_title",
            "root_secure",
            "secure_title",
            "secure_unlock",
            "secure_app_list",
            "dating_home_tab",
        }
    )

    ids_xml = ROOT / "app/src/main/res/values/ids.xml"
    ids_xml.parent.mkdir(parents=True, exist_ok=True)
    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<resources>"]
    for name in sorted(all_id_names):
        lines.append(f'    <item name="{name}" type="id"/>')
    lines.append("</resources>")
    ids_xml.write_text("\n".join(lines) + "\n")

    # FlavorIds.kt
    kt_path = ROOT / "app/src/main/java/ai/mobilerun/fakechats/FlavorIds.kt"
    parts = [
        "package ai.mobilerun.fakechats",
        "",
        "/** Per-flavor resource-id names mirroring real apps / families. */",
        "object FlavorIds {",
        "    data class Ids(",
        "        val searchMenu: String,",
        "        val searchInput: String,",
        "        val contactRow: String,",
        "        val contactName: String,",
        "        val header: String,",
        "        val compose: String,",
        "        val send: String,",
        "        val chatLog: String,",
        "        val bubbleOut: String,",
        "        val like: String,",
        "        val pass: String,",
        "        val superLike: String,",
        "        val deckCard: String,",
        "        val profileName: String,",
        "        val matchesTab: String,",
        "        val matchRow: String,",
        "        val matchName: String,",
        "        val family: String,",
        "    )",
        "",
        "    fun current(): Ids =",
        "        when (BuildConfig.FLAVOR_KEY) {",
    ]
    for app in apps:
        ids = ids_for(app)
        parts.append(f'            "{app["key"]}" ->')
        parts.append("                Ids(")
        for k in [
            "searchMenu",
            "searchInput",
            "contactRow",
            "contactName",
            "header",
            "compose",
            "send",
            "chatLog",
            "bubbleOut",
            "like",
            "pass",
            "superLike",
            "deckCard",
            "profileName",
            "matchesTab",
            "matchRow",
            "matchName",
        ]:
            parts.append(f'                    {k} = "{ids[k]}",')
        parts.append(f'                    family = "{app["family"]}",')
        parts.append("                )")
    parts.append(
        '            else -> error("unknown flavor ${BuildConfig.FLAVOR_KEY}")'
    )
    parts.append("        }")
    parts.append("}")
    parts.append("")
    kt_path.write_text("\n".join(parts))

    # Gradle flavors snippet file included by build.gradle.kts
    flavors = ROOT / "app/flavors.generated.gradle.kts"
    fl = [
        "// GENERATED by scripts/generate_from_catalog.py — do not edit",
        "android {",
        "    productFlavors {",
    ]
    for app in apps:
        fl.append(f'        create("{app["key"]}") {{')
        fl.append('            dimension = "chatapp"')
        fl.append(f'            applicationId = "{app["package"]}"')
        fl.append(f'            resValue("string", "app_label", "{app["label"]}")')
        fl.append(
            f'            buildConfigField("String", "FLAVOR_KEY", "\\"{app["key"]}\\"")'
        )
        fl.append(
            f'            buildConfigField("String", "FAMILY", "\\"{app["family"]}\\"")'
        )
        fl.append("        }")
    fl.append("    }")
    fl.append("}")
    fl.append("")
    flavors.write_text("\n".join(fl))

    # Catalog.kt for runtime
    cat_kt = ROOT / "app/src/main/java/ai/mobilerun/fakechats/AppCatalog.kt"
    bulk = CATALOG["bulk"]
    swipe_apps = [a["key"] for a in apps if a["family"] in ("swipe", "facebook_dating")]
    msg_apps = [a["key"] for a in apps if a["family"] == "messaging"]
    cat_kt.write_text(
        "\n".join(
            [
                "package ai.mobilerun.fakechats",
                "",
                "object AppCatalog {",
                f"    const val SWIPE_TARGET = {bulk['swipe_count']}",
                f"    const val MESSAGE_TARGET = {bulk['message_count']}",
                f"    const val PROFILE_POOL = {bulk['profile_pool']}",
                f"    const val MATCH_POOL = {bulk['match_pool']}",
                "    val SWIPE_FLAVORS = setOf("
                + ", ".join(f'"{k}"' for k in swipe_apps)
                + ")",
                "    val MESSAGING_FLAVORS = setOf("
                + ", ".join(f'"{k}"' for k in msg_apps)
                + ")",
                "}",
                "",
            ]
        )
    )

    # Update build.gradle.kts productFlavors block — rewrite whole flavors section
    gradle = ROOT / "app/build.gradle.kts"
    text = gradle.read_text()
    start = text.index("    productFlavors {")
    # find matching close of productFlavors at same indent before buildTypes
    end = text.index("\n    buildTypes {")
    new_flavors = ["    productFlavors {"]
    for app in apps:
        new_flavors.append(f'        create("{app["key"]}") {{')
        new_flavors.append('            dimension = "chatapp"')
        new_flavors.append(f'            applicationId = "{app["package"]}"')
        new_flavors.append(
            f'            resValue("string", "app_label", "{app["label"]}")'
        )
        new_flavors.append(
            f'            buildConfigField("String", "FLAVOR_KEY", "\\"{app["key"]}\\"")'
        )
        new_flavors.append(
            f'            buildConfigField("String", "FAMILY", "\\"{app["family"]}\\"")'
        )
        new_flavors.append("        }")
    new_flavors.append("    }")
    gradle.write_text(text[:start] + "\n".join(new_flavors) + text[end:])

    print(f"apps={len(apps)} ids={len(all_id_names)}")
    print("wrote", ids_xml)
    print("wrote", kt_path)
    print("wrote", cat_kt)
    print("updated", gradle)


if __name__ == "__main__":
    main()
