package ai.mobilerun.fakechats

/**
 * Per-flavor resource-id names that mirror real apps (matched by
 * dm_heuristics via suffix / `id/…` containment).
 */
object FlavorIds {
    data class Ids(
        val searchMenu: String,
        val searchInput: String,
        val contactRow: String,
        val contactName: String,
        val header: String,
        val compose: String,
        val send: String,
        val chatLog: String,
        val bubbleOut: String,
    )

    fun current(): Ids =
        when (BuildConfig.FLAVOR_KEY) {
            "whatsapp" ->
                Ids(
                    searchMenu = "menuitem_search",
                    searchInput = "search_src_text",
                    contactRow = "contact_row_container",
                    contactName = "conversations_row_contact_name",
                    header = "conversation_contact_name",
                    compose = "entry",
                    send = "send",
                    chatLog = "chat_list",
                    bubbleOut = "message_text",
                )
            "instagram" ->
                Ids(
                    searchMenu = "search_tab",
                    searchInput = "search_edit_text",
                    contactRow = "row_inbox_container",
                    contactName = "row_inbox_username",
                    header = "thread_title",
                    compose = "row_thread_composer_edittext",
                    send = "row_thread_composer_button_send",
                    chatLog = "thread_message_list",
                    bubbleOut = "direct_message_text",
                )
            "messenger" ->
                Ids(
                    searchMenu = "search_button",
                    searchInput = "search_edit_text",
                    contactRow = "thread_list_item",
                    contactName = "thread_title",
                    header = "thread_title_view",
                    compose = "composer_text",
                    send = "composer_send_button",
                    chatLog = "message_list",
                    bubbleOut = "message_bubble_text",
                )
            "telegram" ->
                Ids(
                    searchMenu = "search_item",
                    searchInput = "search_field",
                    contactRow = "dialog_row",
                    contactName = "dialog_title",
                    header = "action_bar_title",
                    compose = "chat_message_edit",
                    send = "chat_send_button",
                    chatLog = "chat_list_view",
                    bubbleOut = "message_text",
                )
            "tinder" ->
                Ids(
                    searchMenu = "matches_search",
                    searchInput = "matches_search_input",
                    contactRow = "match_row",
                    contactName = "match_name",
                    header = "chat_header_name",
                    compose = "message_input",
                    send = "send_button",
                    chatLog = "chat_recycler",
                    bubbleOut = "bubble_text",
                )
            "bumble" ->
                Ids(
                    searchMenu = "connections_search",
                    searchInput = "connections_search_input",
                    contactRow = "connection_row",
                    contactName = "connection_name",
                    header = "chat_title",
                    compose = "message_box",
                    send = "send_cta",
                    chatLog = "messages_list",
                    bubbleOut = "outgoing_text",
                )
            "hinge" ->
                Ids(
                    searchMenu = "likes_search",
                    searchInput = "likes_search_input",
                    contactRow = "like_row",
                    contactName = "like_name",
                    header = "conversation_title",
                    compose = "your_message",
                    send = "send_message",
                    chatLog = "conversation_list",
                    bubbleOut = "sent_text",
                )
            else -> error("unknown flavor ${BuildConfig.FLAVOR_KEY}")
        }
}
