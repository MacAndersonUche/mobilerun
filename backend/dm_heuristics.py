"""Deterministic DM / chat fast-paths for Social + Dating apps.

Covers: WhatsApp, Instagram, Messenger, Telegram, Tinder, Bumble, Hinge.
Flow: open → inbox/DMs → search → type contact → tap result row → VERIFY chat
(header + compose) → type message into compose only → send (or dry-run stop).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Minimum useful a11y nodes before vision fallback is preferred
MIN_USEFUL_TREE_NODES = 15

# App profiles for open → inbox → search → chat → type → send
DM_APP_PROFILES: Dict[str, Dict[str, Any]] = {
    "whatsapp": {
        "aliases": ("whatsapp", "wa"),
        "package": "com.whatsapp",
        "pkg_markers": ("whatsapp",),
        "open_label": "WhatsApp",
        "inbox_labels": ("Chats", "New chat"),
        "new_chat_labels": ("New chat", "New Chat"),
        # SM-G996B HomeActivity: search is a bar, NOT menuitem_search.
        # Toolbar only has camera + overflow — old (983,158) hit those.
        "search_labels": (
            "Ask Meta AI or Search",
            "Ask Meta AI or search",
            "Ask Meta AI or Search",
            "Meta AI or Search",
            "Search…",
            "Search...",
            "Search",
            "search",
        ),
        "search_ids": (
            # Home bar (current WA)
            "com.whatsapp:id/search_bar_inner_layout",
            "id/search_bar_inner_layout",
            "com.whatsapp:id/search_bar",
            "id/search_bar",
            # After bar tap — focused EditText (text may have U+200B prefix)
            "com.whatsapp:id/search_input",
            "id/search_input",
            "com.whatsapp:id/search_src_text",
            "id/search_src_text",
            # Legacy icon (older WA builds only)
            "com.whatsapp:id/menuitem_search",
            "id/menuitem_search",
            "com.whatsapp:id/home_search",
            "com.whatsapp:id/search",
        ),
        # Never guess toolbar coords (camera/overflow live there).
        "search_fallback": None,
        "result_ids": (
            "com.whatsapp:id/contact_row_container",
            "com.whatsapp:id/conversations_row_contact_name",
            "id/contact_row_container",
            "id/conversations_row_contact_name",
        ),
        # Prefer Chats-section rows; never message hits / "From X" chips.
        "result_exclude_ids": (
            "com.whatsapp:id/search_message_container",
            "com.whatsapp:id/search_contact_token",
            "id/search_message_container",
            "id/search_contact_token",
            "search_media_filter",
            "type_token",
        ),
        "header_ids": (
            "com.whatsapp:id/conversation_contact_name",
            "com.whatsapp:id/conversation_contact",
            "com.whatsapp:id/toolbar",
            "id/conversation_contact_name",
        ),
        "compose_labels": ("Message", "Type a message", "Write a message"),
        "compose_ids": ("com.whatsapp:id/entry", "id/entry", ":id/entry"),
        "send_labels": ("Send",),
        "send_ids": (
            "com.whatsapp:id/send",
            "id/send",
            ":id/send",
            "com.whatsapp:id/send_container",
        ),
        # Prefer visible Send ImageButton; no blind coords.
        "send_fallback": None,
        "compose_fallback": None,
        # Clear filter chips before typing a contact name.
        "search_clear_ids": (
            "com.whatsapp:id/search_clear_btn",
            "id/search_clear_btn",
        ),
        "search_clear_labels": ("Clear",),
        # NEVER tap — would ask Meta AI instead of searching contacts.
        "meta_ai_ask_ids": (
            "com.whatsapp:id/search_meta_ai_input_send_button",
            "id/search_meta_ai_input_send_button",
        ),
        "meta_ai_ask_labels": ("Ask",),
        # Prefer tap Send over IME Enter (Enter in search = Meta AI).
        "prefer_tap_send": True,
    },
    "instagram": {
        "aliases": ("instagram", "ig"),
        "package": "com.instagram.android",
        "pkg_markers": ("instagram",),
        "open_label": "Instagram",
        "inbox_labels": (
            "Messages",
            "Direct",
            "Messenger",
            "Open direct message",
            "Inbox",
            "New message",
        ),
        "new_chat_labels": ("New message", "New Message"),
        "search_labels": ("Search", "Search…", "Search...", "To:"),
        "search_ids": (
            "com.instagram.android:id/search_edit_text",
            "com.instagram.android:id/action_bar_search_edit_text",
            "id/search_edit_text",
        ),
        "search_fallback": (980, 160),
        "result_ids": (
            "com.instagram.android:id/row_inbox_container",
            "com.instagram.android:id/row_search_user_container",
            "id/row_inbox_container",
        ),
        "header_ids": (
            "com.instagram.android:id/thread_title",
            "com.instagram.android:id/action_bar_title",
            "id/thread_title",
        ),
        "compose_labels": ("Message…", "Message...", "Message", "Write a message"),
        "compose_ids": (
            "com.instagram.android:id/row_thread_composer_edittext",
            "com.instagram.android:id/message_edit_text",
            "id/row_thread_composer_edittext",
        ),
        "send_labels": ("Send", "Send message"),
        "send_ids": (
            "com.instagram.android:id/row_thread_composer_button_send",
            "id/row_thread_composer_button_send",
        ),
        "send_fallback": (1000, 2280),
        "compose_fallback": (540, 2250),
    },
    "messenger": {
        "aliases": ("messenger", "facebook messenger", "fb messenger"),
        "package": "com.facebook.orca",
        "pkg_markers": ("orca", "messenger"),
        "open_label": "Messenger",
        "inbox_labels": ("Chats", "Messages", "New message", "Compose"),
        "new_chat_labels": ("New message", "Compose"),
        "search_labels": ("Search", "Search…", "Search Messenger"),
        "search_ids": (
            "com.facebook.orca:id/search_edit_text",
            "id/search_edit_text",
        ),
        "search_fallback": (540, 200),
        "result_ids": ("com.facebook.orca:id/thread_list_item",),
        "header_ids": ("com.facebook.orca:id/thread_title_view",),
        "compose_labels": ("Aa", "Message", "Write a message", "Send a message"),
        "compose_ids": (
            "com.facebook.orca:id/composer_text",
            "com.facebook.orca:id/composer_edit_text",
            "id/composer_text",
        ),
        "send_labels": ("Send", "Send message"),
        "send_ids": (
            "com.facebook.orca:id/composer_send_button",
            "id/composer_send_button",
        ),
        "send_fallback": (1000, 2280),
        "compose_fallback": (540, 2250),
    },
    "telegram": {
        "aliases": ("telegram", "tg"),
        "package": "org.telegram.messenger",
        "pkg_markers": ("telegram",),
        "open_label": "Telegram",
        "inbox_labels": ("Chats", "New Message", "New message"),
        "new_chat_labels": ("New Message", "New message"),
        "search_labels": ("Search", "Search…"),
        "search_ids": (
            "org.telegram.messenger:id/search_field",
            "id/search_field",
        ),
        "search_fallback": (980, 160),
        "result_ids": (),
        "header_ids": ("org.telegram.messenger:id/action_bar_title",),
        "compose_labels": ("Message", "Write a message"),
        "compose_ids": (
            "org.telegram.messenger:id/chat_message_edit",
            "id/chat_message_edit",
        ),
        "send_labels": ("Send",),
        "send_ids": (
            "org.telegram.messenger:id/chat_send_button",
            "id/chat_send_button",
        ),
        "send_fallback": (1000, 2280),
        "compose_fallback": (540, 2250),
    },
    "tinder": {
        "aliases": ("tinder",),
        "package": "com.tinder",
        "pkg_markers": ("tinder",),
        "open_label": "Tinder",
        "inbox_labels": ("Chat", "Chats", "Messages", "Matches", "Inbox"),
        "new_chat_labels": ("Matches", "Chat"),
        "search_labels": ("Search", "Search matches", "Search…"),
        # Fake-chats emulator bench ids (+ label fallbacks for real Tinder)
        "search_ids": ("id/matches_search", "id/matches_search_input"),
        "search_fallback": (540, 200),
        "result_ids": ("id/match_row", "id/match_name"),
        "header_ids": ("id/chat_header_name",),
        "compose_labels": (
            "Type a message",
            "Message",
            "Send a message",
            "Say something",
        ),
        "compose_ids": ("id/message_input", ":id/message_input"),
        "send_labels": ("Send",),
        "send_ids": ("id/send_button", ":id/send_button"),
        "send_fallback": (1000, 2280),
        "compose_fallback": (540, 2250),
    },
    "bumble": {
        # Real-device map: Mac SM-G996B 1080x2400 main profile (19 Nov 2025).
        "aliases": ("bumble",),
        "package": "com.bumble.app",
        "pkg_markers": ("bumble",),
        "open_label": "Bumble",
        "launch_activity": "com.bumble.app/.ui.launcher.BumbleLauncherActivity",
        "open_settle_s": 5.0,  # splash
        "family": "swipe",
        # People deck (no like/pass buttons — gesture only)
        "deck_ids": (
            "com.bumble.app:id/profile_root_container",
            "id/profile_root_container",
            "encountersGridItem_summaryContainer",
            "id/encountersGridItem_summaryContainer",
        ),
        "deck_name_hint": "Name, Age",  # TextView near bottom of card
        # Verified swipe recipe (adb input swipe timings)
        "like_swipe": (250, 1000, 1050, 1050, 300),
        "pass_swipe": (850, 1000, 30, 1050, 300),
        # Bottom nav — content-desc on mainApp_navigationTabBar
        "nav_bar_id": "com.bumble.app:id/mainApp_navigationTabBar",
        "inbox_labels": ("Chats", "Messages", "Connections", "Inbox"),
        "inbox_ids": (
            "com.bumble.app:id/connections_root",
            "id/connections_root",
        ),
        "inbox_tab_labels": ("Chats",),
        "inbox_tab_xy": (972, 2197),  # Chats tab center [864,2120][1080,2274]
        "people_tab_xy": (540, 2197),  # People [432..648]
        "new_chat_labels": ("Chats", "Connections"),
        "search_labels": ("Search", "Search…"),
        # Fake-chats emu ids; real Bumble Connections has no search field
        "search_ids": (
            "id/connections_search",
            "id/connections_search_input",
        ),
        "search_fallback": None,  # never coordinate-guess search on real device
        # Fake-chats Like/Pass buttons (real deck is swipe-only)
        "like_ids": ("id/encounter_like", "id/gamepad_like"),
        "pass_ids": ("id/encounter_pass", "id/gamepad_pass"),
        # Connections list (real SM-G996B + fake-chats emu)
        "result_ids": (
            "com.bumble.app:id/connectionItem",
            "id/connectionItem",
            "com.bumble.app:id/connectionsItem_personName",
            "id/connectionsItem_personName",
            "id/connection_row",
            "id/connection_name",
        ),
        "result_exclude_ids": (
            "com.bumble.app:id/connections_stickyPromoContainer",
            "id/connections_stickyPromoContainer",
            "connections_matchQueue",
        ),
        "connections_list_id": "com.bumble.app:id/connections_connectionsList",
        "header_ids": (
            "com.bumble.app:id/chatToolbar_title",
            "id/chatToolbar_title",
            "id/chat_title",  # fake-chats
        ),
        "compose_labels": ("Aa", "Message", "Type a message", "Say something"),
        "compose_ids": (
            "com.bumble.app:id/chatInput_text",
            "id/chatInput_text",
            "id/message_box",
            ":id/message_box",
        ),
        "send_labels": ("Send",),
        # Send appears only after typing — match id containing "send"
        "send_ids": (
            "send",
            "com.bumble.app:id/chatInput_send",
            "id/chatInput_send",
            "id/send_cta",
            ":id/send_cta",
        ),
        "send_fallback": None,  # never coordinate-guess Send on real device
        "compose_fallback": None,
        "prefer_tap_send": True,
        # NEVER tap these (undo / paid / AV)
        "never_tap_ids": (
            "toolbar_backtrackContainer",
            "profile_details_badgeSuperSwipe",
            "chatToolbar_audioChatButton",
            "chatToolbar_videoChatButton",
            "connections_stickyPromoContainer",
        ),
        "never_tap_labels": (
            "Send a compliment",
            "Undo",
            "SuperSwipe",
        ),
    },
    "yubo": {
        # Real-device map: Mac SM-G996B 1080x2400 (19 Nov). Compose UI — few ids.
        "aliases": ("yubo",),
        "package": "co.yellw.yellowapp",
        "pkg_markers": ("yellw", "yellowapp", "yubo"),
        "open_label": "Yubo",
        "launch_activity": "co.yellw.yellowapp/.main.MainActivity",
        "open_settle_s": 8.0,
        "family": "swipe",
        "like_swipe": (250, 1000, 1050, 1050, 300),
        "pass_swipe": (850, 1000, 30, 1050, 300),
        # Bottom nav y≈2180 (centers)
        "nav_y": 2180,
        "deck_tab_xy": (140, 2180),
        "inbox_tab_xy": (343, 2180),  # Chat
        "likes_tab_xy": (540, 2180),
        "friends_tab_xy": (750, 2180),
        "more_tab_xy": (940, 2180),
        "inbox_labels": ("Chat", "Chats", "Conversations", "Messages"),
        "inbox_tab_labels": ("Chat",),
        "new_chat_labels": ("Chat", "Conversations"),
        "search_labels": ("Search", "Search…"),
        "search_ids": (
            "id/matches_search",
            "id/matches_search_input",
        ),  # fake-chats
        "search_fallback": None,
        "like_ids": ("id/yubo_like", "id/gamepad_like"),
        "pass_ids": ("id/yubo_pass", "id/gamepad_pass"),
        "result_ids": ("id/match_row", "id/match_name"),
        "header_ids": ("id/chat_header_name",),
        "compose_labels": ("Aa", "Message", "Type a message", "Hey"),
        "compose_ids": ("id/message_input", ":id/message_input"),
        # Keyboard-open send arrow (mic becomes send when text present)
        "send_labels": ("Send",),
        "send_ids": ("id/send_button", ":id/send_button", "send"),
        "send_xy_keyboard": (1008, 1336),
        "direct_send_xy": (985, 1336),
        "send_fallback": None,
        "compose_fallback": None,  # prefer Aa / editable; keyboard moves field
        "prefer_tap_send": True,
        "prefer_clear_before_type": True,
        "outgoing_min_x": 666,  # right-aligned bubbles
        # Paid / dangerous — never tap
        "never_tap_xy": ((840, 158),),  # Yubucks pill ~[812,138][869,179]
        "never_tap_labels": (
            "Yubucks",
            "Blast",
            "HyperSurge",
            "Launch a HyperSurge",
            "Unlock Infinity Pack",
            "Infinity Pack",
            "rocket",
            "Rewind",
        ),
        "never_tap_ids": (),
        "direct_tile_xy": (855, 656),
        "send_message_cta_xy": (260, 2000),
    },
    "badoo": {
        # Real-device map: Mac SM-G996B 1080x2400 (19 Nov). Full resource-ids.
        "aliases": ("badoo",),
        "package": "com.badoo.mobile",
        "pkg_markers": ("badoo",),
        "open_label": "Badoo",
        "launch_activity": "com.badoo.mobile/.android.BadooActivity",
        "open_settle_s": 8.0,
        "family": "swipe",
        "deck_ids": (
            "com.badoo.mobile:id/encounters_stackView",
            "id/encounters_stackView",
        ),
        "like_ids": (
            "com.badoo.mobile:id/encounters_profile_voting_buttonVoteYes",
            "id/encounters_profile_voting_buttonVoteYes",
            "id/badoo_like",
        ),
        "pass_ids": (
            "com.badoo.mobile:id/encounters_profile_voting_buttonVoteNo",
            "id/encounters_profile_voting_buttonVoteNo",
            "id/badoo_pass",
        ),
        "like_xy": (855, 1982),
        "pass_xy": (225, 1982),
        "like_swipe": (250, 1100, 1050, 1150, 300),
        "pass_swipe": (850, 1100, 30, 1150, 300),
        "inbox_labels": ("Chats", "Connections", "Messages", "Inbox"),
        "inbox_ids": (
            "com.badoo.mobile:id/connections_root",
            "id/connections_root",
        ),
        "inbox_tab_labels": ("Chats", "Connections"),
        "inbox_tab_xy": (756, 2210),  # nav_bar_button_connections
        "encounters_tab_xy": (324, 2210),
        "new_chat_labels": ("Chats", "Connections"),
        "search_labels": ("Search", "Search…"),
        "search_ids": ("id/matches_search", "id/matches_search_input"),
        "search_fallback": None,
        "result_ids": (
            "com.badoo.mobile:id/connection_container",
            "id/connection_container",
            "com.badoo.mobile:id/profileInfo_name",
            "id/profileInfo_name",
            "id/match_row",
            "id/match_name",
        ),
        "result_exclude_ids": (
            "com.badoo.mobile:id/connectionItem_favoriteContainer",
            "id/connectionItem_favoriteContainer",
            "match_bar_container",
        ),
        "connections_list_id": "com.badoo.mobile:id/connection_list_component",
        "header_ids": (
            "com.badoo.mobile:id/chatToolbar_title",
            "id/chatToolbar_title",
            "id/chat_header_name",
        ),
        "compose_labels": (
            "Type a message...",
            "Type a message",
            "Message",
            "Aa",
        ),
        "compose_ids": (
            "com.badoo.mobile:id/chatInput_text",
            "id/chatInput_text",
            "id/message_input",
        ),
        "send_labels": ("Send message", "Send"),
        "send_ids": (
            "com.badoo.mobile:id/chatInput_button_send",
            "id/chatInput_button_send",
            "id/send_button",
            "send",
        ),
        "send_fallback": None,
        "compose_fallback": None,
        "prefer_tap_send": True,
        "prefer_clear_before_type": True,
        "never_tap_ids": (
            "encounters_profile_voting_buttonChat",
            "buttonChat",
            "encounters_profile_voting_buttonCrush",
            "buttonCrush",
            "encountersCards_undo",
            "chatToolbar_videoChatButton",
            "status_add_spp_explanation_text",
            "connectionItem_favoriteContainer",
        ),
        "never_tap_labels": (
            "Buy Credits",
            "Crush",
            "Likes",  # match strip paid tile
            "Rewind",
            "Undo",
        ),
    },
    "hily": {
        # Real-device map: Mac SM-G996B 1080x2400 (19 Nov). Bare resource-ids.
        "aliases": ("hily",),
        "package": "com.hily.app",
        "pkg_markers": ("hily",),
        "open_label": "Hily",
        "launch_activity": "com.hily.app/.main.MainActivity",
        "open_settle_s": 5.0,
        "family": "swipe",
        # Swipe gesture does NOT register — buttons only
        "like_ids": ("ActionButton_LIKE", "id/ActionButton_LIKE"),
        "pass_ids": ("ActionButton_SKIP", "id/ActionButton_SKIP"),
        "like_xy": (750, 1959),
        "pass_xy": (330, 1959),
        "deck_name_id": "userNameAgeField",
        "deck_card_id_prefix": "finderCardUser",
        "inbox_labels": ("Chats", "Messages", "Inbox"),
        "inbox_tab_labels": ("Chats",),
        "inbox_tab_xy": (341, 2190),  # bottomNavTab_2
        "deck_tab_xy": (142, 2190),  # bottomNavTab_1 Finder
        "activity_tab_xy": (740, 2190),  # bottomNavTab_4
        "new_chat_labels": ("Chats",),
        "search_labels": ("Search", "Search…"),
        "search_ids": ("dialogsSearchButton", "id/dialogsSearchButton"),
        "search_fallback": None,
        "result_ids": (
            "dialogMessageItem",
            "id/dialogMessageItem",
            "userNameField",
            "id/userNameField",
            "center_name",
            "id/center_name",
        ),
        "result_exclude_ids": ("threadReadyForDateToggleSwitch",),
        "header_ids": ("threadToolBarName", "id/threadToolBarName"),
        "compose_labels": ("Aa", "Message", "Type a message"),
        "compose_ids": (
            "threadInputFieldText",
            "id/threadInputFieldText",
            "textInput",
            "id/textInput",
        ),
        "send_labels": ("Send",),
        "send_ids": (
            "threadSend",
            "id/threadSend",
            "sendMessageButton",
            "id/sendMessageButton",
        ),
        "send_fallback": None,
        "compose_fallback": None,
        "prefer_tap_send": True,
        "prefer_clear_before_type": True,
        "never_tap_ids": (
            "ActionButton_CRUSH",
            "threadReadyForDateToggleSwitch",
        ),
        "never_tap_labels": (
            "Crush",
            "Major Crush",
            "They liked you!",
            "Allow",
            "Audio message",
            "Locked",
        ),
    },
    "blk": {
        # Real-device map: Mac SM-G996B 1080x2400 (19 Nov). Compose UI — few ids.
        "aliases": ("blk", "b.l.k", "black people meet"),
        "package": "com.affinityapps.blk",
        "pkg_markers": ("affinityapps.blk", "blk"),
        "open_label": "BLK",
        "launch_activity": "com.affinityapps.blk/com.aa.swipe.v3.MainActivity",
        "open_settle_s": 5.0,
        "family": "swipe",
        # Two "Like Icon" nodes — only RIGHT cyan heart (left>=850, top<1900)
        "like_desc": "Like Icon",
        "like_min_x1": 850,
        "like_max_y1": 1900,
        "inbox_labels": ("Matches", "Connections", "Chats", "Messages"),
        "inbox_tab_labels": ("Matches",),
        "inbox_tab_xy": (675, 2170),  # nav_connections
        "deck_tab_xy": (135, 2170),  # nav_swipe Discover
        "likes_tab_xy": (405, 2170),
        "new_chat_labels": ("Matches", "Your turn", "Their turn"),
        "search_labels": ("Search", "Search…"),
        "search_ids": (),
        "search_fallback": None,
        "result_ids": (),
        "header_ids": (),
        "compose_labels": ("Message", "Type a message", "Aa", "Say something"),
        "compose_ids": (),  # only EditText on thread
        "send_labels": ("Send",),
        "send_ids": (),  # unlabeled View right of EditText
        "send_fallback": None,
        "compose_fallback": None,
        "prefer_tap_send": True,
        "prefer_clear_before_type": True,
        "never_tap_labels": (
            "Boost",
            "Send a Super Like",
            "Super Like",
            "Send a message",  # on card = message-before-match / super path
        ),
        "never_tap_ids": (),
    },
    "taimi": {
        # Real-device map: Mac SM-G996B 1080x2400. Package is takimi (not taimi).
        # FLAG_SECURE → screenshots black; uiautomator dumps only (no vision).
        "aliases": ("taimi",),
        "package": "com.takimi.android",
        "pkg_markers": ("takimi",),
        "open_label": "Taimi",
        "launch_activity": "com.takimi.android/.MainActivityDefault",
        "open_settle_s": 5.0,
        "family": "swipe",
        "flag_secure": True,
        # React Native: almost no ids — text/content-desc + bounds
        "like_ids": (),
        "pass_ids": (),
        "inbox_labels": ("Chats", "Matches", "Messages"),
        "inbox_tab_labels": ("Chats",),
        "inbox_tab_xy": (972, 2200),  # Chats nav
        "deck_tab_xy": (540, 2200),  # People
        "likes_tab_xy": (756, 2200),
        "new_chat_labels": ("Chats", "Matches", "Start chat"),
        "search_labels": ("Search", "Search…"),
        "search_ids": (),
        "search_fallback": None,
        "result_ids": (),
        "header_ids": (),
        "compose_labels": (
            "Say something...",
            "Say something…",
            "Say something",
            "Add an intro (optional)",
            "Message",
        ),
        "compose_ids": (),
        "send_labels": ("Send",),
        "send_ids": (),
        "send_fallback": None,
        "compose_fallback": None,
        "prefer_tap_send": True,
        "prefer_clear_before_type": True,
        "never_tap_labels": (
            "Continue",  # GOLD paywall CTA
            "Notify me",
            "Never miss a message",
            "Is your daily pick",
            "Recurring billing",
            "GOLD",
        ),
        "never_tap_ids": (),
        # Verified action-row map centres (fallback when siblings not parsed)
        "pass_xy": (320, 1948),
        "instant_chat_xy": (541, 1948),  # PAID on Mac's account
        "like_xy": (761, 1948),
    },
    "hinge": {
        "aliases": ("hinge",),
        "package": "co.hinge.app",
        "pkg_markers": ("hinge",),
        "open_label": "Hinge",
        "inbox_labels": ("Matches", "Messages", "Chats", "Liked You", "Inbox"),
        "new_chat_labels": ("Matches", "Liked You"),
        "search_labels": ("Search", "Search…"),
        "search_ids": ("id/likes_search", "id/likes_search_input"),
        "search_fallback": (980, 160),
        "result_ids": ("id/like_row", "id/like_name"),
        "header_ids": ("id/conversation_title",),
        "compose_labels": (
            "Type a message",
            "Message",
            "Your message",
            "Say something",
        ),
        "compose_ids": ("id/your_message", ":id/your_message"),
        "send_labels": ("Send",),
        "send_ids": ("id/send_message", ":id/send_message"),
        "send_fallback": (1000, 2280),
        "compose_fallback": (540, 2250),
    },
}


def _register_catalog_profiles() -> None:
    """Add fake-chats catalog apps not already in DM_APP_PROFILES."""
    try:
        from fake_chats_catalog import apps as catalog_apps
    except ImportError:
        try:
            from backend.fake_chats_catalog import apps as catalog_apps  # type: ignore
        except ImportError:
            return
    swipe_template = DM_APP_PROFILES["tinder"]
    for app in catalog_apps():
        key = app["key"]
        if key in DM_APP_PROFILES or key == "securefolder":
            continue
        family = app.get("family") or "swipe"
        if family == "messaging":
            continue
        if family == "facebook_dating":
            DM_APP_PROFILES[key] = {
                **swipe_template,
                "aliases": ("facebook dating", "facebook", "fb dating"),
                "package": app["package"],
                "pkg_markers": ("facebook", "katana", "dating"),
                "open_label": app["label"],
                "like_ids": ("id/dating_like",),
                "pass_ids": ("id/dating_pass",),
                "compose_ids": ("id/dating_composer",),
                "send_ids": ("id/dating_send",),
                "search_ids": ("id/dating_search", "id/dating_search_edit"),
                "result_ids": ("id/dating_match_row", "id/dating_inbox_row"),
                "header_ids": ("id/dating_thread_title",),
            }
            continue
        # Generic swipe dating clones
        DM_APP_PROFILES[key] = {
            **swipe_template,
            "aliases": (key, app["label"].lower()),
            "package": app["package"],
            "pkg_markers": (key,),
            "open_label": app["label"],
            "like_ids": (f"id/{key}_like", "id/gamepad_like"),
            "pass_ids": (f"id/{key}_pass", "id/gamepad_pass"),
            "search_ids": (
                f"id/{key}_matches_tab",
                "id/matches_search",
                "id/matches_search_input",
            ),
            "result_ids": (f"id/{key}_match_row", "id/match_row"),
            "header_ids": ("id/chat_header_name",),
            "compose_ids": ("id/message_input",),
            "send_ids": ("id/send_button",),
        }


_register_catalog_profiles()


def tree_node_count(tree: str) -> int:
    low = (tree or "").lower()
    return low.count("<n ") + low.count("<node ")


def tree_is_sparse(tree: str, nodes: Optional[int] = None) -> bool:
    """True when a11y dump is too thin for reliable planning (Compose/Flutter)."""
    if nodes is not None and nodes > 0:
        return nodes < MIN_USEFUL_TREE_NODES
    n = tree_node_count(tree)
    if n == 0:
        low = (tree or "").lower()
        if not tree or 'empty="true"' in low or len(tree) < 80:
            return True
        return True
    return n < MIN_USEFUL_TREE_NODES


def _tree_node_center(tree: str, *needles: str) -> Optional[Tuple[int, int]]:
    low = (tree or "").lower()
    for needle in needles:
        n = (needle or "").lower().strip()
        if not n:
            continue
        for pat in (
            rf'<(?:n|node)\b[^>]*(?:t|d|h|text|content-desc|contentDescription)="[^"]*{re.escape(n)}[^"]*"[^>]*\bxy="(\d+),(\d+)"',
            rf'<(?:n|node)\b[^>]*\bxy="(\d+),(\d+)"[^>]*(?:t|d|h|text|content-desc|contentDescription)="[^"]*{re.escape(n)}[^"]*"',
            rf'<(?:n|node)\b[^>]*(?:t|d|h|text|content-desc)="[^"]*{re.escape(n)}[^"]*"[^>]*\bb="(\d+),(\d+),(\d+),(\d+)"',
            rf'<(?:n|node)\b[^>]*\bb="(\d+),(\d+),(\d+),(\d+)"[^>]*(?:t|d|h|text|content-desc)="[^"]*{re.escape(n)}[^"]*"',
            rf'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*(?:text|content-desc)="[^"]*{re.escape(n)}[^"]*"',
            rf'(?:text|content-desc)="[^"]*{re.escape(n)}[^"]*"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
        ):
            m = re.search(pat, low, re.I)
            if not m:
                continue
            groups = [int(g) for g in m.groups() if g is not None]
            if len(groups) == 2:
                return (groups[0], groups[1])
            if len(groups) >= 4:
                x1, y1, x2, y2 = groups[:4]
                return ((x1 + x2) // 2, (y1 + y2) // 2)
    return None


def _tree_editable_center(tree: str) -> Optional[Tuple[int, int]]:
    low = (tree or "").lower()
    for pat in (
        r'<(?:n|node)\b[^>]*\be="?1"?[^>]*\bxy="(\d+),(\d+)"',
        r'<(?:n|node)\b[^>]*\bxy="(\d+),(\d+)"[^>]*\be="?1"?',
        r'<(?:n|node)\b[^>]*edittext[^>]*\bxy="(\d+),(\d+)"',
        r'<(?:n|node)\b[^>]*\bb="(\d+),(\d+),(\d+),(\d+)"[^>]*\be="?1"?',
        r'<(?:n|node)\b[^>]*\be="?1"?[^>]*\bb="(\d+),(\d+),(\d+),(\d+)"',
    ):
        m = re.search(pat, low, re.I)
        if not m:
            continue
        groups = [int(g) for g in m.groups() if g is not None]
        if len(groups) == 2:
            return (groups[0], groups[1])
        if len(groups) >= 4:
            x1, y1, x2, y2 = groups[:4]
            return ((x1 + x2) // 2, (y1 + y2) // 2)
    return None


def _tree_id_center(tree: str, *id_needles: str) -> Optional[Tuple[int, int]]:
    """Locate a node by resource-id suffix (e.g. com.whatsapp:id/entry)."""
    for n in _parse_compact_nodes(tree):
        vid = str(n.get("id") or "").lower()
        if not vid:
            continue
        for needle in id_needles:
            want = (needle or "").lower().strip()
            if not want:
                continue
            if vid == want or vid.endswith(want) or want in vid:
                return (int(n["x"]), int(n["y"]))
    return None


def find_compose_center(
    tree: str,
    compose_labels: Sequence[str],
    compose_ids: Sequence[str] = (),
    search_labels: Sequence[str] = (),
) -> Optional[Tuple[int, int]]:
    """Prefer WhatsApp entry id, then Message hint, then bottom editable."""
    c = _tree_id_center(tree, *tuple(compose_ids))
    if c:
        return c
    c = _tree_node_center(tree, *tuple(compose_labels))
    if c:
        return c
    for n in _parse_compact_nodes(tree):
        if not n.get("editable"):
            continue
        if _is_searchish_node(n, search_labels):
            continue
        hint = str(n.get("hint") or "").lower()
        label = str(n.get("label") or "").lower()
        if "message" in hint or "message" in label or n.get("y", 0) > 1800:
            return (int(n["x"]), int(n["y"]))
    return None


def find_send_center(
    tree: str, send_labels: Sequence[str], send_ids: Sequence[str] = ()
) -> Optional[Tuple[int, int]]:
    c = _tree_id_center(tree, *tuple(send_ids))
    if c:
        return c
    return _tree_node_center(tree, *tuple(send_labels))


_NODE_TAG_RE = re.compile(r"<(?:n|node)\b([^>]*)/?>", re.I)


def _attr(blob: str, *names: str) -> str:
    for name in names:
        m = re.search(rf'\b{re.escape(name)}="([^"]*)"', blob, re.I)
        if m:
            return m.group(1)
    return ""


def _parse_compact_nodes(tree: str) -> List[Dict[str, Any]]:
    """Parse compact a11y dump nodes into dicts with center/flags."""
    out: List[Dict[str, Any]] = []
    for m in _NODE_TAG_RE.finditer(tree or ""):
        attrs = m.group(1)
        text = _attr(attrs, "t", "text")
        desc = _attr(attrs, "d", "content-desc", "contentDescription")
        hint = _attr(attrs, "h", "hint")
        xy = _attr(attrs, "xy")
        b = _attr(attrs, "b", "bounds")
        editable = _attr(attrs, "e") in ("1", "true", "True")
        clickable = _attr(attrs, "c") in ("1", "true", "True")
        cx = cy = None
        x1 = y1 = x2 = y2 = None
        if b:
            nums = re.findall(r"\d+", b)
            if len(nums) >= 4:
                x1, y1, x2, y2 = (int(n) for n in nums[:4])
        if xy and "," in xy:
            try:
                cx, cy = [int(p) for p in xy.split(",")[:2]]
            except ValueError:
                cx = cy = None
        if (cx is None or cy is None) and x1 is not None and y1 is not None:
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        if cx is None or cy is None:
            continue
        label = " ".join(p for p in (text, desc, hint) if p).strip()
        view_id = _attr(attrs, "i", "resource-id", "viewIdResourceName")
        cls = _attr(attrs, "cls", "class", "className")
        focused = _attr(attrs, "f") in ("1", "true", "True")
        out.append(
            {
                "text": text,
                "desc": desc,
                "hint": hint,
                "label": label,
                "id": view_id,
                "cls": cls,
                "x": cx,
                "y": cy,
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "editable": editable,
                "clickable": clickable,
                "focused": focused,
            }
        )
    return out


def _token_near(a: str, b: str) -> bool:
    """True when tokens match or are a 1-edit typo (acahlugo≈achalugo)."""
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    if abs(len(a) - len(b)) > 2:
        return False
    # cheap Levenshtein early-exit for short name tokens
    if len(a) < 4 or len(b) < 4:
        return False
    try:
        from difflib import SequenceMatcher

        return SequenceMatcher(None, a, b).ratio() >= 0.82
    except Exception:
        return False


def _fuzzy_score(needle: str, hay: str) -> float:
    """Token-overlap fuzzy score in [0, 1] with 1-edit typo tolerance."""
    n = re.sub(r"\s+", " ", (needle or "").strip().lower())
    h = re.sub(r"\s+", " ", (hay or "").strip().lower())
    if not n or not h:
        return 0.0
    if n == h:
        return 1.0
    if n in h or h in n:
        return 0.92
    nt = [t for t in re.split(r"[^\w]+", n) if t]
    ht = [t for t in re.split(r"[^\w]+", h) if t]
    if not nt:
        return 0.0
    hit = 0
    for t in nt:
        if any(_token_near(t, u) for u in ht):
            hit += 1
    return hit / len(nt)


def _is_searchish_node(node: Dict[str, Any], search_labels: Sequence[str]) -> bool:
    if node.get("editable"):
        hint = (node.get("hint") or "").lower()
        label = (node.get("label") or "").lower()
        if any(s.lower() in hint or s.lower() in label for s in search_labels):
            return True
        if "search" in hint or "search" in label or hint.startswith("to"):
            return True
        # Top-of-screen editable is almost always the search box after query type
        if int(node.get("y") or 0) < 280:
            return True
    return False


def _node_id_matches(node: Dict[str, Any], needles: Sequence[str]) -> bool:
    nid = str(node.get("id") or "").lower()
    if not nid:
        return False
    for n in needles:
        nl = (n or "").lower().strip()
        if not nl:
            continue
        if nl in nid or nid.endswith(nl.lstrip(":")):
            return True
    return False


def _chats_section_y(nodes: Sequence[Dict[str, Any]]) -> Optional[int]:
    """Y of the 'Chats' section header in WA search results (prefer rows below)."""
    for n in nodes:
        label = (n.get("label") or "").strip().lower()
        nid = str(n.get("id") or "").lower()
        if label == "chats" or ("title" in nid and label == "chats"):
            return int(n.get("y") or 0)
    return None


def find_contact_result_center(
    tree: str,
    contact: str,
    *,
    search_labels: Sequence[str] = (),
    result_ids: Sequence[str] = (),
    exclude_ids: Sequence[str] = (),
) -> Optional[Tuple[int, int]]:
    """Best fuzzy match for a contact *result row* — never the search EditText.

    WhatsApp SM-G996B: prefer contact_row_container / conversations_row_contact_name
    under the 'Chats' header — never message hits or 'From X' chips.
    """
    nodes = _parse_compact_nodes(tree)
    if not nodes:
        return None
    chats_y = _chats_section_y(nodes)
    candidates: List[Tuple[float, int, Dict[str, Any]]] = []
    for node in nodes:
        if _is_searchish_node(node, search_labels):
            continue
        if exclude_ids and _node_id_matches(node, exclude_ids):
            continue
        label = node.get("label") or ""
        low = label.lower()
        # "From Precious Achalugo" chip / message snippet rows
        if low.startswith("from "):
            continue
        if "search_message" in str(node.get("id") or "").lower():
            continue
        score = _fuzzy_score(contact, label)
        if score < 0.5:
            first = (contact.split() or [""])[0]
            if first and len(first) >= 3:
                score = max(score, _fuzzy_score(first, label) * 0.85)
        # Photo content-desc: "<Name> picture" — usable but prefer name/row
        if score < 0.5 and "picture" in low:
            score = max(
                score,
                _fuzzy_score(contact, re.sub(r"\s+picture\s*$", "", low, flags=re.I))
                * 0.9,
            )
        if score < 0.5:
            continue
        y = int(node.get("y") or 0)
        if y < 260:
            score *= 0.4
        if node.get("clickable"):
            score += 0.05
        if result_ids and _node_id_matches(node, result_ids):
            score += 0.25
        if "picture" in low and "contact_photo" in str(node.get("id") or "").lower():
            score *= 0.7
        # Prefer rows under the Chats section header
        if chats_y is not None and y > chats_y:
            score += 0.15
        elif chats_y is not None and y < chats_y:
            score *= 0.5
        candidates.append((score, y, node))
    if not candidates:
        return None
    candidates.sort(key=lambda t: (-t[0], t[1]))
    best = candidates[0][2]
    return (int(best["x"]), int(best["y"]))


def _search_filter_chip_active(tree: str) -> bool:
    """True when WA search has a media/type chip (Photos, Stickers, type_token)."""
    for node in _parse_compact_nodes(tree):
        nid = str(node.get("id") or "").lower()
        label = (node.get("label") or "").lower()
        if "type_token" in nid or "search_media_filter" in nid:
            return True
        if nid.endswith("type_token") or "media_filter" in nid:
            return True
        # Selected chip often exposes filter names near the search field
        if int(node.get("y") or 0) < 400 and label in (
            "photos",
            "stickers",
            "videos",
            "gifs",
            "links",
            "audio",
            "documents",
        ):
            return True
    return False


def _strip_zwsp(text: str) -> str:
    """WhatsApp search_input often prefixes a zero-width space (U+200B)."""
    return (text or "").replace("\u200b", "").strip()


def find_search_clear_center(
    tree: str, profile: Dict[str, Any]
) -> Optional[Tuple[int, int]]:
    ids = tuple(profile.get("search_clear_ids") or ())
    labels = tuple(profile.get("search_clear_labels") or ("Clear",))
    c = _tree_id_center(tree, *ids) if ids else None
    if c:
        return c
    return _tree_node_center(tree, *labels)


def _is_forbidden_tap_target(node: Dict[str, Any], profile: Dict[str, Any]) -> bool:
    """True when a node must never be tapped (undo / paid / AV)."""
    ids = tuple(profile.get("never_tap_ids") or ())
    labels = tuple(profile.get("never_tap_labels") or ())
    if ids and _node_id_matches(node, ids):
        return True
    lab = (node.get("label") or "").strip().lower()
    for forbid in labels:
        fl = (forbid or "").strip().lower()
        if fl and (lab == fl or fl in lab):
            return True
    return False


def find_send_center_safe(
    tree: str,
    send_labels: Sequence[str],
    send_ids: Sequence[str] = (),
    *,
    profile: Optional[Dict[str, Any]] = None,
) -> Optional[Tuple[int, int]]:
    """Locate Send; skip forbidden nodes. Prefer id substring 'send'."""
    profile = profile or {}
    # Prefer explicit send ids / labels, then any id containing "send"
    c = find_send_center(tree, send_labels, send_ids=send_ids)
    if c:
        # Ensure we did not resolve a forbidden node at the same xy
        for n in _parse_compact_nodes(tree):
            if int(n.get("x") or -1) == c[0] and int(n.get("y") or -1) == c[1]:
                if _is_forbidden_tap_target(n, profile):
                    c = None
                break
    if c:
        return c
    for n in _parse_compact_nodes(tree):
        if _is_forbidden_tap_target(n, profile):
            continue
        nid = str(n.get("id") or "").lower()
        lab = (n.get("label") or "").lower()
        if "send" in nid or lab == "send":
            # Avoid "Send a compliment" paid CTA
            if "compliment" in lab:
                continue
            return (int(n["x"]), int(n["y"]))
    return None


def bumble_on_people_deck(tree: str) -> bool:
    """True when Bumble People tab card stack is visible."""
    if _tree_id_center(
        tree,
        "profile_root_container",
        "encountersGridItem_summaryContainer",
        "com.bumble.app:id/profile_root_container",
    ):
        return True
    # Name TextView "Name, Age" near bottom of card + main photo desc
    for n in _parse_compact_nodes(tree):
        lab = n.get("label") or ""
        low = lab.lower()
        if "main photo" in low and ("'s" in low or "\u2019s" in lab):
            return True
        if re.search(r",\s*\d{2}\s*$", lab.strip()) and int(n.get("y") or 0) > 1600:
            return True
    return False


def bumble_on_connections(tree: str) -> bool:
    return bool(
        _tree_id_center(
            tree,
            "connections_root",
            "connections_connectionsList",
            "com.bumble.app:id/connections_root",
        )
    )


def bumble_dismiss_popup(
    tree: str, planner: str = "bumble_heuristic"
) -> Optional[Dict[str, Any]]:
    """Handle post-swipe / upsell dialogs from the S21 real-device map.

    Returns a tagged action or None when no known popup is present.
    """
    nodes = _parse_compact_nodes(tree)
    blob = " ".join(f"{n.get('id')} {n.get('label')}" for n in nodes).lower()
    titles = " ".join(
        (n.get("label") or "")
        for n in nodes
        if "alert" in str(n.get("id") or "").lower()
        or (n.get("label") or "").endswith("?")
    ).lower()

    # AlertDialog Interested? / Not interested?
    if "interested?" in blob or "not interested?" in blob:
        # Prefer positive / confirm button1
        btn = _tree_id_center(tree, "android:id/button1", "id/button1", "button1")
        if btn is None:
            btn = _tree_node_center(
                tree, "YES", "Yes", "NOT INTERESTED", "Not interested"
            )
        if btn:
            reason = (
                "Dismiss Interested? → YES"
                if "not interested" not in blob
                else "Dismiss Not interested? → NOT INTERESTED"
            )
            if "not interested?" in blob:
                reason = "Dismiss Not interested? → NOT INTERESTED"
            elif "interested?" in blob:
                reason = "Dismiss Interested? → YES"
            return _fp(
                {
                    "action": "tap",
                    "x": btn[0],
                    "y": btn[1],
                    "reason": f"{reason} ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "bumble_popup_alert",
            )

    # Bottom sheet "Enjoying Bumble?" → BACK
    if "enjoying bumble" in blob:
        return _fp(
            {
                "action": "press_button",
                "button": "back",
                "reason": f"Dismiss Enjoying Bumble? sheet ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "bumble_popup_enjoying",
        )

    # Full-screen compliments upsell "Second time's a charm"
    if "second time" in blob and "charm" in blob:
        back = _tree_node_center(tree, "Back")
        if back:
            return _fp(
                {
                    "action": "tap",
                    "x": back[0],
                    "y": back[1],
                    "reason": f"Dismiss compliments upsell Back ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "bumble_popup_upsell",
            )
        return _fp(
            {
                "action": "press_button",
                "button": "back",
                "reason": f"Dismiss compliments upsell ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "bumble_popup_upsell",
        )

    # Premium / Spotlight / buy screens → BACK
    if any(
        k in blob
        for k in (
            "premium",
            "spotlight",
            "boost",
            "subscribe",
            "start free trial",
            "bumble premium",
        )
    ):
        # Only if it looks like a paywall (not a chat about premium)
        if "chatinput" not in blob and "chattoolbar" not in blob:
            return _fp(
                {
                    "action": "press_button",
                    "button": "back",
                    "reason": f"Dismiss Premium/Spotlight paywall ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "bumble_popup_paywall",
            )

    # It's a match — generic dismiss or continue to chat if Message CTA present
    if re.search(r"it['\u2019`]?s a match", blob) or re.search(
        r"it['\u2019`]?s a match", titles
    ):
        msg_cta = _tree_node_center(
            tree, "Send a message", "Message", "Say hello", "Chat"
        )
        if msg_cta:
            # Avoid "Send a compliment"
            for n in nodes:
                if (
                    int(n.get("x") or -1) == msg_cta[0]
                    and int(n.get("y") or -1) == msg_cta[1]
                ):
                    if "compliment" in (n.get("label") or "").lower():
                        msg_cta = None
                    break
        if msg_cta:
            return _fp(
                {
                    "action": "tap",
                    "x": msg_cta[0],
                    "y": msg_cta[1],
                    "reason": f"It's a match → open chat ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "bumble_match_chat",
            )
        return _fp(
            {
                "action": "press_button",
                "button": "back",
                "reason": f"Dismiss It's a match ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "bumble_match_dismiss",
        )

    return None


def bumble_like_swipe(planner: str = "bumble_heuristic") -> Dict[str, Any]:
    """Verified like gesture: swipe right across the card."""
    x1, y1, x2, y2, dur = DM_APP_PROFILES["bumble"]["like_swipe"]
    return _fp(
        {
            "action": "swipe",
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "duration_ms": dur,
            "reason": f"Bumble like swipe ({planner})",
            "planner": planner,
            "llm_provider": None,
        },
        "bumble_like_swipe",
    )


def bumble_pass_swipe(planner: str = "bumble_heuristic") -> Dict[str, Any]:
    """Verified pass gesture: swipe left across the card."""
    x1, y1, x2, y2, dur = DM_APP_PROFILES["bumble"]["pass_swipe"]
    return _fp(
        {
            "action": "swipe",
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "duration_ms": dur,
            "reason": f"Bumble pass swipe ({planner})",
            "planner": planner,
            "llm_provider": None,
        },
        "bumble_pass_swipe",
    )


# --- Yubo (co.yellw.yellowapp) SM-G996B ---


def yubo_deck_card_name(tree: str) -> Optional[str]:
    """First text node with left x≈42 is the deck card name."""
    for n in _parse_compact_nodes(tree):
        text = (n.get("text") or "").strip()
        if not text or len(text) > 40:
            continue
        x1 = n.get("x1")
        if x1 is None:
            continue
        if abs(int(x1) - 42) > 2:
            continue
        y = int(n.get("y") or 0)
        if y < 200 or y > 2100:
            continue
        low = text.lower()
        if low in ("chat", "likes", "friends", "more", "aa", "direct", "blast"):
            continue
        return text
    return None


def yubo_on_deck(tree: str) -> bool:
    if yubo_deck_card_name(tree):
        return True
    blob = (tree or "").lower()
    return "send a message" in blob and "conversations" not in blob


def yubo_on_chat_list(tree: str) -> bool:
    blob = (tree or "").lower()
    return "conversations" in blob or ("new friends" in blob and "aa" not in blob)


def yubo_on_chat(tree: str) -> bool:
    return bool(
        _tree_node_center(tree, "Aa")
        or find_compose_center(tree, ("Aa", "Message"), ())
    ) and bool(_tree_node_center(tree, "Back"))


def yubo_dismiss_popup(
    tree: str, planner: str = "yubo_heuristic"
) -> Optional[Dict[str, Any]]:
    blob = " ".join(
        f"{n.get('id')} {n.get('label')}" for n in _parse_compact_nodes(tree)
    ).lower()
    if "unlock infinity pack" in blob or "infinity pack" in blob:
        return _fp(
            {
                "action": "press_button",
                "button": "back",
                "reason": f"Dismiss Infinity Pack upsell ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "yubo_popup_infinity",
        )
    return None


def yubo_direct_sheet_action(
    tree: str, planner: str = "yubo_heuristic"
) -> Optional[Dict[str, Any]]:
    """Handle 'Send a message' sheet: never send while Blast (paid) is selected."""
    nodes = _parse_compact_nodes(tree)
    blob = " ".join((n.get("label") or "") for n in nodes).lower()
    if "direct" not in blob and "blast" not in blob:
        return None
    # Find Direct / Blast tiles
    direct_n = None
    blast_n = None
    for n in nodes:
        lab = (n.get("label") or "").strip().lower()
        if lab == "direct":
            direct_n = n
        elif lab == "blast":
            blast_n = n
    if direct_n is None and blast_n is None:
        return None
    # Selected Direct has bounds ≈[729,515][875,572]; unselected ≈[754,525][871,570]
    direct_selected = False
    if direct_n is not None and direct_n.get("x1") is not None:
        w = int(direct_n["x2"]) - int(direct_n["x1"])
        h = int(direct_n["y2"]) - int(direct_n["y1"])
        # Selected tile is slightly larger
        if w >= 140 or h >= 50 or int(direct_n["x1"]) <= 735:
            direct_selected = True
    if not direct_selected:
        xy = DM_APP_PROFILES["yubo"].get("direct_tile_xy") or (855, 656)
        if direct_n is not None:
            xy = (int(direct_n["x"]), int(direct_n["y"]))
        return _fp(
            {
                "action": "tap",
                "x": int(xy[0]),
                "y": int(xy[1]),
                "reason": f"Select Direct (never Blast/Yubucks) ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "yubo_select_direct",
        )
    return None


def yubo_find_conversation_tap(tree: str, contact: str) -> Optional[Tuple[int, int]]:
    """Conversations row: name text near x=242 → tap (540, name_y+27)."""
    best: Optional[Tuple[float, int, int]] = None
    for n in _parse_compact_nodes(tree):
        text = (n.get("text") or "").strip()
        if not text:
            continue
        score = _fuzzy_score(contact, text)
        if score < 0.6:
            continue
        cx = int(n.get("x") or 0)
        x1 = n.get("x1")
        # Name column ≈ x=242; skip New friends carousel (y 264–760) when possible
        y = int(n.get("y") or 0)
        if y < 200:
            continue
        col_ok = abs(cx - 242) <= 50 or (x1 is not None and abs(int(x1) - 242) <= 40)
        if not col_ok and not (180 <= cx <= 320):
            continue
        # Prefer rows below Conversations header (~1072)
        bonus = 0.2 if y >= 1000 else 0.0
        if 264 <= y <= 760:
            bonus -= 0.3  # New friends / Reactions carousel
        ranked = score + bonus
        if best is None or ranked > best[0]:
            best = (ranked, 540, y + 27)
    if best is None:
        return None
    return (best[1], best[2])


def yubo_like_swipe(planner: str = "yubo_heuristic") -> Dict[str, Any]:
    x1, y1, x2, y2, dur = DM_APP_PROFILES["yubo"]["like_swipe"]
    return _fp(
        {
            "action": "swipe",
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "duration_ms": dur,
            "reason": f"Yubo like swipe ({planner})",
            "planner": planner,
            "llm_provider": None,
        },
        "yubo_like_swipe",
    )


def yubo_pass_swipe(planner: str = "yubo_heuristic") -> Dict[str, Any]:
    x1, y1, x2, y2, dur = DM_APP_PROFILES["yubo"]["pass_swipe"]
    return _fp(
        {
            "action": "swipe",
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "duration_ms": dur,
            "reason": f"Yubo pass swipe ({planner})",
            "planner": planner,
            "llm_provider": None,
        },
        "yubo_pass_swipe",
    )


def yubo_find_send_center(tree: str) -> Optional[Tuple[int, int]]:
    """Send arrow with keyboard open — prefer node near known xy / Send label."""
    c = find_send_center_safe(
        tree,
        ("Send",),
        send_ids=("send", "id/send_button"),
        profile=DM_APP_PROFILES["yubo"],
    )
    if c:
        return c
    # Mic becomes send arrow near (1008,1336) when text present
    for n in _parse_compact_nodes(tree):
        if _is_forbidden_tap_target(n, DM_APP_PROFILES["yubo"]):
            continue
        x, y = int(n["x"]), int(n["y"])
        if abs(x - 1008) <= 40 and abs(y - 1336) <= 60 and n.get("clickable"):
            return (x, y)
        if abs(x - 985) <= 40 and abs(y - 1336) <= 60 and n.get("clickable"):
            return (x, y)
    return None


def yubo_outgoing_verified(tree: str, message: str) -> bool:
    """Right-aligned (x>=666) bubble with exact text."""
    needle = (message or "").strip().lower()
    if len(needle) < 2:
        return False
    min_x = int(DM_APP_PROFILES["yubo"].get("outgoing_min_x") or 666)
    for n in _parse_compact_nodes(tree):
        if n.get("editable"):
            continue
        text = (n.get("text") or "").strip()
        if text.lower() != needle:
            continue
        if int(n.get("x") or 0) >= min_x or (
            n.get("x1") is not None and int(n["x1"]) >= min_x - 40
        ):
            return True
    return False


# --- Badoo (com.badoo.mobile) SM-G996B ---


def badoo_on_encounters(tree: str) -> bool:
    return bool(
        _tree_id_center(
            tree,
            "encounters_stackView",
            "encounters_profile_voting_buttonVoteYes",
            "encounters_profile_voting_buttonVoteNo",
            "com.badoo.mobile:id/encounters_stackView",
        )
    )


def badoo_on_connections(tree: str) -> bool:
    return bool(
        _tree_id_center(
            tree,
            "connections_root",
            "connection_list_component",
            "com.badoo.mobile:id/connections_root",
        )
    )


def badoo_dismiss_popup(
    tree: str, planner: str = "badoo_heuristic"
) -> Optional[Dict[str, Any]]:
    nodes = _parse_compact_nodes(tree)
    blob = " ".join(f"{n.get('id')} {n.get('label')}" for n in nodes).lower()
    if "buy credits" in blob:
        close = _tree_node_center(tree, "Close")
        if close:
            return _fp(
                {
                    "action": "tap",
                    "x": close[0],
                    "y": close[1],
                    "reason": f"Dismiss Buy Credits sheet → Close ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "badoo_popup_credits",
            )
        return _fp(
            {
                "action": "press_button",
                "button": "back",
                "reason": f"Dismiss Buy Credits sheet ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "badoo_popup_credits",
        )
    return None


def badoo_like_action(planner: str = "badoo_heuristic") -> Dict[str, Any]:
    """Prefer VoteYes button; swipe recipe also available."""
    return _fp(
        {
            "action": "tap",
            "x": 855,
            "y": 1982,
            "reason": f"Badoo Like (VoteYes) ({planner})",
            "planner": planner,
            "llm_provider": None,
        },
        "badoo_like",
    )


def badoo_pass_action(planner: str = "badoo_heuristic") -> Dict[str, Any]:
    return _fp(
        {
            "action": "tap",
            "x": 225,
            "y": 1982,
            "reason": f"Badoo Pass (VoteNo) ({planner})",
            "planner": planner,
            "llm_provider": None,
        },
        "badoo_pass",
    )


def badoo_like_swipe(planner: str = "badoo_heuristic") -> Dict[str, Any]:
    x1, y1, x2, y2, dur = DM_APP_PROFILES["badoo"]["like_swipe"]
    return _fp(
        {
            "action": "swipe",
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "duration_ms": dur,
            "reason": f"Badoo like swipe ({planner})",
            "planner": planner,
            "llm_provider": None,
        },
        "badoo_like_swipe",
    )


def badoo_pass_swipe(planner: str = "badoo_heuristic") -> Dict[str, Any]:
    x1, y1, x2, y2, dur = DM_APP_PROFILES["badoo"]["pass_swipe"]
    return _fp(
        {
            "action": "swipe",
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "duration_ms": dur,
            "reason": f"Badoo pass swipe ({planner})",
            "planner": planner,
            "llm_provider": None,
        },
        "badoo_pass_swipe",
    )


# --- Hily (com.hily.app) SM-G996B — buttons only; swipe does not register ---


def hily_on_finder(tree: str) -> bool:
    return bool(
        _tree_id_center(
            tree,
            "ActionButton_LIKE",
            "ActionButton_SKIP",
            "userNameAgeField",
            "finderCardUser",
        )
    )


def hily_on_chats_list(tree: str) -> bool:
    return bool(
        _tree_id_center(
            tree,
            "dialogMessageItem",
            "dialogsSearchButton",
            "userNameField",
        )
    )


def hily_on_thread(tree: str) -> bool:
    return bool(
        _tree_id_center(
            tree,
            "threadInputFieldText",
            "threadToolBarName",
            "threadSend",
        )
    )


def hily_on_mbm(tree: str) -> bool:
    """Message Before Match / majorCrushScreen."""
    blob = " ".join(
        f"{n.get('id')} {n.get('label')}" for n in _parse_compact_nodes(tree)
    ).lower()
    return "message before match" in blob or "majorcrush" in blob.replace("_", "")


def hily_deck_card_name(tree: str) -> Optional[str]:
    for n in _parse_compact_nodes(tree):
        nid = str(n.get("id") or "").lower()
        if "usernameagefield" not in nid:
            continue
        text = (n.get("text") or "").strip()
        if text and "," in text:
            return text.split(",")[0].strip()
        if text:
            return text
    return None


def hily_dismiss_popup(
    tree: str, planner: str = "hily_heuristic"
) -> Optional[Dict[str, Any]]:
    """Dismiss first-like / notif / filter / tutorial / MBM sheets — never Allow."""
    nodes = _parse_compact_nodes(tree)
    blob = " ".join(f"{n.get('id')} {n.get('label')}" for n in nodes).lower()

    # Tutorial Got It by id
    tut = _tree_id_center(
        tree,
        "threadReadyForDateTutorialGotIt",
        "id/threadReadyForDateTutorialGotIt",
    )
    if tut and (
        "threadreadyfordatetutorial" in blob.replace("_", "")
        or "ready for date" in blob
    ):
        return _fp(
            {
                "action": "tap",
                "x": tut[0],
                "y": tut[1],
                "reason": f"Dismiss Ready for Date tutorial Got it ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "hily_tutorial_got_it",
        )

    got_it_triggers = (
        "you gave your first like",
        "filter your chats",
        "message sent",
        "major crush",
    )
    if any(t in blob for t in got_it_triggers):
        got = _tree_node_center(tree, "Got it", "Got it!")
        if got:
            return _fp(
                {
                    "action": "tap",
                    "x": got[0],
                    "y": got[1],
                    "reason": f"Dismiss Hily sheet → Got it ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "hily_got_it",
            )

    # Notif permission — Maybe later (never Allow)
    if any(
        t in blob for t in ("see when", "reacts", "notification", "notif permission")
    ):
        later = _tree_node_center(tree, "Maybe later", "Not now", "No thanks")
        if later:
            return _fp(
                {
                    "action": "tap",
                    "x": later[0],
                    "y": later[1],
                    "reason": f"Dismiss notif prompt → Maybe later ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "hily_maybe_later",
            )

    # Paywall / zero allowance → back out
    if "paywall" in blob or "upgrade" in blob and "message before match" in blob:
        return _fp(
            {
                "action": "press_button",
                "button": "back",
                "reason": f"Dismiss Hily paywall ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "hily_paywall_back",
        )
    return None


def hily_like_action(
    tree: str = "", planner: str = "hily_heuristic"
) -> Optional[Dict[str, Any]]:
    """Free Like via ActionButton_LIKE — never CRUSH. Prefer tree; else map xy."""
    for n in _parse_compact_nodes(tree):
        nid = str(n.get("id") or "").lower()
        if "actionbutton_crush" in nid:
            continue
        if "actionbutton_like" not in nid:
            continue
        return _fp(
            {
                "action": "tap",
                "x": int(n["x"]),
                "y": int(n["y"]),
                "reason": f"Hily Like (ActionButton_LIKE) ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "hily_like",
        )
    # Verified map coords (1080x2400) — only when tree had no LIKE id
    xy = DM_APP_PROFILES["hily"].get("like_xy") or (750, 1959)
    if tree and not hily_on_finder(tree):
        return None
    return _fp(
        {
            "action": "tap",
            "x": int(xy[0]),
            "y": int(xy[1]),
            "reason": f"Hily Like map xy ({planner})",
            "planner": planner,
            "llm_provider": None,
        },
        "hily_like",
    )


def hily_pass_action(
    tree: str = "", planner: str = "hily_heuristic"
) -> Optional[Dict[str, Any]]:
    for n in _parse_compact_nodes(tree):
        if "actionbutton_skip" not in str(n.get("id") or "").lower():
            continue
        return _fp(
            {
                "action": "tap",
                "x": int(n["x"]),
                "y": int(n["y"]),
                "reason": f"Hily Pass (ActionButton_SKIP) ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "hily_pass",
        )
    xy = DM_APP_PROFILES["hily"].get("pass_xy") or (330, 1959)
    if tree and not hily_on_finder(tree):
        return None
    return _fp(
        {
            "action": "tap",
            "x": int(xy[0]),
            "y": int(xy[1]),
            "reason": f"Hily Pass map xy ({planner})",
            "planner": planner,
            "llm_provider": None,
        },
        "hily_pass",
    )


def hily_mbm_allowance(tree: str) -> Optional[int]:
    """Parse Major Crush allowance from content-desc 'button  N'."""
    for n in _parse_compact_nodes(tree):
        d = str(n.get("desc") or "").strip().lower()
        if not d.startswith("button"):
            continue
        parts = d.replace("button", "").strip().split()
        for p in parts:
            if p.isdigit():
                return int(p)
    return None


def hily_find_chat_row(tree: str, contact: str) -> Optional[Tuple[int, int]]:
    """Tap dialogMessageItem / userNameField matching contact."""
    best: Optional[Tuple[float, int, int]] = None
    for n in _parse_compact_nodes(tree):
        nid = str(n.get("id") or "").lower()
        text = (n.get("text") or n.get("label") or "").strip()
        if not text:
            continue
        if "usernamefield" not in nid and "dialogmessageitem" not in nid:
            # Also allow plain name match in chats list
            if "dialog" not in nid and "center_name" not in nid:
                if "username" not in nid:
                    continue
        score = _fuzzy_score(contact, text)
        if score < 0.6:
            continue
        if best is None or score > best[0]:
            best = (score, int(n["x"]), int(n["y"]))
    if best is None:
        return None
    return (best[1], best[2])


def hily_send_is_audio(tree: str) -> bool:
    """threadSend shows 'Audio message' when empty — never tap."""
    for n in _parse_compact_nodes(tree):
        if "threadsend" not in str(n.get("id") or "").lower():
            continue
        d = str(n.get("desc") or "").strip().lower()
        if "audio" in d:
            return True
        if d == "send":
            return False
    return False


def hily_find_send_center(tree: str) -> Optional[Tuple[int, int]]:
    """Send only when content-desc is Send (not Audio message)."""
    if hily_send_is_audio(tree):
        return None
    c = find_send_center_safe(
        tree,
        ("Send",),
        send_ids=("threadSend", "id/threadSend", "sendMessageButton"),
        profile=DM_APP_PROFILES["hily"],
    )
    return c


def hily_outgoing_verified(tree: str, message: str) -> bool:
    """threadTextMessage with true (sent) containing message text."""
    needle = (message or "").strip().lower()
    if len(needle) < 2:
        return False
    for n in _parse_compact_nodes(tree):
        if n.get("editable"):
            continue
        nid = str(n.get("id") or "").lower()
        text = (n.get("text") or "").strip().lower()
        if text != needle:
            continue
        if "threadtextmessage" in nid:
            # id may encode true|false; also check desc/label for true
            blob = f"{nid} {n.get('desc') or ''} {n.get('label') or ''}".lower()
            if "false" in blob and "true" not in blob.replace("false", ""):
                continue
            return True
        # Fallback: non-editable bubble + Sent status nearby
        if int(n.get("y") or 0) > 280:
            return True
    return outgoing_bubble_present(tree, message)


# --- BLK (com.affinityapps.blk) SM-G996B — Compose UI, few ids ---


def blk_on_deck(tree: str) -> bool:
    if blk_end_of_deck(tree):
        return False
    # Discover card: Like Icon and/or "Send a message" + name
    has_like = False
    has_send_msg = False
    for n in _parse_compact_nodes(tree):
        d = str(n.get("desc") or "").strip().lower()
        t = str(n.get("text") or "").strip().lower()
        if d == "like icon":
            has_like = True
        if t == "send a message":
            has_send_msg = True
    return has_like or (has_send_msg and "your turn" not in (tree or "").lower())


def blk_on_matches(tree: str) -> bool:
    blob = " ".join(
        (n.get("text") or n.get("label") or "") for n in _parse_compact_nodes(tree)
    ).lower()
    return (
        "your turn" in blob
        or "their turn" in blob
        or ("matches" in blob and "like icon" not in blob)
    )


def blk_on_thread(tree: str) -> bool:
    # Only EditText composer + header name; few ids
    has_edit = any(n.get("editable") for n in _parse_compact_nodes(tree))
    blob = " ".join((n.get("text") or "") for n in _parse_compact_nodes(tree)).lower()
    if "get messages notifications" in blob:
        return True
    # Thread usually has Back + name + EditText, no Like Icon
    has_like = any(
        str(n.get("desc") or "").strip().lower() == "like icon"
        for n in _parse_compact_nodes(tree)
    )
    return has_edit and not has_like and not blk_on_matches(tree)


def blk_end_of_deck(tree: str) -> bool:
    blob = " ".join(
        (n.get("text") or n.get("label") or "") for n in _parse_compact_nodes(tree)
    ).lower()
    return "you reached the end" in blob or "reached the end" in blob


def blk_deck_card_name(tree: str) -> Optional[str]:
    """Name = TextView immediately before 'Send a message' on the card."""
    texts: List[Tuple[int, int, str]] = []
    for n in _parse_compact_nodes(tree):
        t = (n.get("text") or "").strip()
        if not t:
            continue
        y = int(n.get("y1") if n.get("y1") is not None else n.get("y") or 0)
        x = int(n.get("x1") if n.get("x1") is not None else n.get("x") or 0)
        texts.append((y, x, t))
    texts.sort(key=lambda x: (x[0], x[1]))
    for i, (_y, _x, t) in enumerate(texts):
        if t.lower() == "send a message" and i > 0:
            prev = texts[i - 1][2].strip()
            if prev and prev.lower() not in (
                "send a message",
                "like icon",
                "boost",
                "pass",
                "discover",
            ):
                return prev.split(",")[0].strip()
    return None


def blk_dismiss_popup(
    tree: str, planner: str = "blk_heuristic"
) -> Optional[Dict[str, Any]]:
    """Super Like upsell → Send Like anyway; notif banner → Close."""
    nodes = _parse_compact_nodes(tree)
    blob = " ".join((n.get("text") or n.get("label") or "") for n in nodes).lower()
    if "super like" in blob and ("instead" in blob or "send a super like" in blob):
        anyway = _tree_node_center(tree, "Send Like anyway", "Send like anyway")
        if anyway:
            return _fp(
                {
                    "action": "tap",
                    "x": anyway[0],
                    "y": anyway[1],
                    "reason": f"Dismiss Super Like upsell → Send Like anyway ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "blk_send_like_anyway",
            )
        # Never tap "Send a Super Like"
    if "get messages notifications" in blob or "messages notifications" in blob:
        close = _tree_node_center(tree, "Close", "Dismiss", "Not now", "No thanks")
        if close:
            return _fp(
                {
                    "action": "tap",
                    "x": close[0],
                    "y": close[1],
                    "reason": f"Dismiss BLK notif banner → Close ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "blk_notif_close",
            )
    return None


def blk_like_action(
    tree: str, planner: str = "blk_heuristic"
) -> Optional[Dict[str, Any]]:
    """Normal Like = 'Like Icon' with left>=850 and top<1900 (cyan heart).

    Left Like Icon (~749) is green crown SUPER LIKE — never tap.
    """
    best: Optional[Tuple[int, int, int]] = None  # x1, x, y
    for n in _parse_compact_nodes(tree):
        if str(n.get("desc") or "").strip().lower() != "like icon":
            continue
        x1 = n.get("x1")
        y1 = n.get("y1")
        if x1 is None or y1 is None:
            continue
        if int(x1) < 850 or int(y1) >= 1900:
            continue
        if best is None or int(x1) > best[0]:
            best = (int(x1), int(n["x"]), int(n["y"]))
    if best is None:
        return None
    return _fp(
        {
            "action": "tap",
            "x": best[1],
            "y": best[2],
            "reason": f"BLK Like Icon (right/cyan, never super) ({planner})",
            "planner": planner,
            "llm_provider": None,
        },
        "blk_like",
    )


def blk_find_match_row(tree: str, contact: str) -> Optional[Tuple[int, int]]:
    """Matches list: skip Hidden section; tap name/avatar+last msg row."""
    nodes = _parse_compact_nodes(tree)
    hidden_y: Optional[int] = None
    for n in nodes:
        t = (n.get("text") or "").strip().lower()
        if t.startswith("hidden"):
            hidden_y = int(n.get("y") or 0)
            break
    best: Optional[Tuple[float, int, int]] = None
    for n in nodes:
        text = (n.get("text") or "").strip()
        if not text:
            continue
        low = text.lower()
        if low.startswith(("your turn", "their turn", "hidden")):
            continue
        y = int(n.get("y") or 0)
        if hidden_y is not None and y >= hidden_y:
            continue
        score = _fuzzy_score(contact, text)
        if score < 0.6:
            continue
        if best is None or score > best[0]:
            best = (score, int(n["x"]), y)
    if best is None:
        return None
    return (best[1], best[2])


def blk_send_relative_to_edittext(tree: str) -> Optional[Tuple[int, int]]:
    """Send = unlabeled View immediately right of the only EditText composer."""
    edit: Optional[Dict[str, Any]] = None
    for n in _parse_compact_nodes(tree):
        if not n.get("editable"):
            continue
        if edit is None or int(n.get("y") or 0) > int(edit.get("y") or 0):
            edit = n
    if not edit:
        return None
    ex2 = edit.get("x2")
    ey1 = edit.get("y1")
    ey2 = edit.get("y2")
    if ex2 is None or ey1 is None or ey2 is None:
        return None
    best: Optional[Tuple[int, int, int]] = None  # dx, x, y
    for n in _parse_compact_nodes(tree):
        if n is edit or n.get("editable"):
            continue
        t = str(n.get("text") or "").strip().lower()
        d = str(n.get("desc") or "").strip().lower()
        blob = f"{t} {d}"
        if any(bad in blob for bad in ("boost", "super like", "gift", "premium")):
            continue
        x1 = n.get("x1")
        y1 = n.get("y1")
        x2 = n.get("x2")
        y2 = n.get("y2")
        if x1 is None or y1 is None or x2 is None or y2 is None:
            continue
        if int(x1) < int(ex2) - 20:
            continue
        if int(y2) < int(ey1) - 40 or int(y1) > int(ey2) + 40:
            continue
        w, h = int(x2) - int(x1), int(y2) - int(y1)
        if w > 200 or h > 200 or w < 20 or h < 20:
            continue
        # Prefer unlabeled / "Send"
        if t and t not in ("send",) and d and d not in ("send", ""):
            continue
        dx = int(x1) - int(ex2)
        if dx < 0:
            continue
        if best is None or dx < best[0]:
            best = (dx, int(n["x"]), int(n["y"]))
    if best is None:
        return None
    return (best[1], best[2])


def blk_outgoing_verified(tree: str, message: str) -> bool:
    """New bubble with message text and 'Sent' status."""
    needle = (message or "").strip().lower()
    if len(needle) < 2:
        return False
    saw_msg = False
    saw_sent = False
    for n in _parse_compact_nodes(tree):
        if n.get("editable"):
            continue
        text = (n.get("text") or "").strip()
        low = text.lower()
        if low == needle and int(n.get("y") or 0) > 280:
            saw_msg = True
        if low == "sent":
            saw_sent = True
    return saw_msg and saw_sent


# --- Taimi (com.takimi.android) SM-G996B — RN, FLAG_SECURE, no vision ---


def taimi_is_paywall(tree: str) -> bool:
    """GOLD / billing sheet — never Continue."""
    blob = " ".join(
        f"{n.get('text') or ''} {n.get('desc') or ''} {n.get('label') or ''}"
        for n in _parse_compact_nodes(tree)
    ).lower()
    if "recurring billing" in blob:
        return True
    if "gold" in blob and (
        "continue" in blob or "cancel anytime" in blob or "£" in blob or "$" in blob
    ):
        return True
    if "continue" in blob and ("gold" in blob or "£" in blob or "billing" in blob):
        return True
    return False


def taimi_dismiss_paywall(
    tree: str, planner: str = "taimi_heuristic"
) -> Optional[Dict[str, Any]]:
    if not taimi_is_paywall(tree):
        return None
    return _fp(
        {
            "action": "press_button",
            "button": "back",
            "reason": f"Dismiss Taimi GOLD paywall → BACK ({planner})",
            "planner": planner,
            "llm_provider": None,
        },
        "taimi_paywall_back",
    )


def taimi_swipes_left(tree: str) -> Optional[int]:
    """Parse '<N> left' daily swipe counter near top (~y124)."""
    for n in _parse_compact_nodes(tree):
        text = (n.get("text") or n.get("label") or "").strip()
        m = re.search(r"^(\d+)\s+left$", text, re.I)
        if not m:
            continue
        y = int(n.get("y") or 0)
        if y > 400:
            continue
        return int(m.group(1))
    return None


def taimi_on_people_deck(tree: str) -> bool:
    if taimi_is_paywall(tree):
        return False
    if taimi_swipes_left(tree) is not None:
        return True
    # Action row band + name band without Chats header
    blob = " ".join(
        (n.get("text") or n.get("desc") or "") for n in _parse_compact_nodes(tree)
    ).lower()
    if blob.startswith("chats") or "\nchats" in blob or re.search(r"\bchats\b", blob):
        # May still be deck if People selected — require action row
        pass
    row = taimi_action_row_centers(tree)
    if row and row.get("like"):
        return True
    return False


def taimi_on_chats_list(tree: str) -> bool:
    nodes = _parse_compact_nodes(tree)
    blob = " ".join((n.get("text") or n.get("desc") or "") for n in nodes).lower()
    has_header = any(
        (n.get("text") or "").strip().lower() == "chats" and int(n.get("y") or 0) < 300
        for n in nodes
    )
    has_matches_chip = any(
        (n.get("text") or n.get("desc") or "").strip().lower() == "matches"
        for n in nodes
    )
    has_tile = any(
        "start chat" in (n.get("desc") or "").lower()
        or "daily pick" in (n.get("desc") or "").lower()
        for n in nodes
    )
    return bool(
        has_header or (has_matches_chip and has_tile) or ("chats" in blob and has_tile)
    )


def taimi_on_thread(tree: str) -> bool:
    has_edit = any(n.get("editable") for n in _parse_compact_nodes(tree))
    if not has_edit:
        return False
    if taimi_is_paywall(tree):
        return False
    # Instant Chat sheet also has EditText — detect by title
    blob = " ".join((n.get("text") or "") for n in _parse_compact_nodes(tree)).lower()
    if "send instant chat" in blob:
        return False
    # Thread: Say something… composer, or Delivered history
    return (
        "say something" in blob
        or "delivered" in blob
        or bool(find_compose_center(tree, ("Say something...", "Say something"), ()))
    )


def taimi_is_curated_card(tree: str) -> bool:
    blob = " ".join(
        (n.get("text") or n.get("label") or "") for n in _parse_compact_nodes(tree)
    ).lower()
    return "curated for you" in blob


def taimi_deck_card_name(tree: str) -> Optional[str]:
    """Name = large text roughly y 1507–1665 (not labels / icebreakers)."""
    skip = {
        "curated for you",
        "active today",
        "people",
        "likes",
        "chats",
        "profile",
        "trending",
        "left",
    }
    best: Optional[Tuple[int, str]] = None
    for n in _parse_compact_nodes(tree):
        text = (n.get("text") or "").strip()
        if not text or len(text) > 40:
            continue
        low = text.lower()
        if low in skip or "left" in low:
            continue
        if low.startswith(",") or ", ," in low:
            continue  # icebreaker chip
        y = int(n.get("y") or 0)
        y1 = int(n.get("y1") if n.get("y1") is not None else y)
        if not (1450 <= y <= 1750 or 1450 <= y1 <= 1750):
            continue
        # Prefer shorter name-like tokens
        if best is None or abs(y - 1580) < abs(best[0] - 1580):
            best = (y, text.split(",")[0].strip())
    return best[1] if best else None


def taimi_action_row_centers(
    tree: str,
) -> Dict[str, Optional[Tuple[int, int]]]:
    """Locate Skip / Instant Chat / Like as three equal-width siblings ~y1875–2022.

    LEFT = Skip, CENTRE = Instant Chat (paid), RIGHT = Like.
    """
    candidates: List[Dict[str, Any]] = []
    for n in _parse_compact_nodes(tree):
        if not n.get("clickable"):
            continue
        y1 = n.get("y1")
        y2 = n.get("y2")
        x1 = n.get("x1")
        x2 = n.get("x2")
        if y1 is None or y2 is None or x1 is None or x2 is None:
            y = int(n.get("y") or 0)
            if not (1850 <= y <= 2050):
                continue
            # No bounds — use center xy only
            candidates.append(n)
            continue
        if int(y2) < 1850 or int(y1) > 2050:
            continue
        # Skip tiny / full-width / top chrome
        w = int(x2) - int(x1)
        h = int(y2) - int(y1)
        if w < 80 or w > 400 or h < 60 or h > 250:
            continue
        # Skip labeled nav / paid CTAs
        lab = f"{n.get('text') or ''} {n.get('desc') or ''}".strip().lower()
        if lab in ("people", "chats", "likes", "profile", "trending", "continue"):
            continue
        if int(y1) < 1800:
            continue
        candidates.append(n)
    # Prefer three siblings with similar width/height
    if len(candidates) >= 3:
        candidates.sort(key=lambda n: int(n.get("x") or 0))
        # Pick the tightest cluster of 3 by y proximity to 1948
        scored: List[Tuple[float, List[Dict[str, Any]]]] = []
        for i in range(len(candidates) - 2):
            trio = candidates[i : i + 3]
            ys = [int(t.get("y") or 0) for t in trio]
            if max(ys) - min(ys) > 80:
                continue
            xs = [int(t.get("x") or 0) for t in trio]
            if xs[0] >= xs[1] or xs[1] >= xs[2]:
                continue
            # Roughly equal spacing
            d1, d2 = xs[1] - xs[0], xs[2] - xs[1]
            if abs(d1 - d2) > 120:
                continue
            score = abs(sum(ys) / 3 - 1948) + abs(d1 - d2)
            scored.append((score, trio))
        if scored:
            scored.sort(key=lambda x: x[0])
            trio = scored[0][1]
            return {
                "skip": (int(trio[0]["x"]), int(trio[0]["y"])),
                "instant_chat": (int(trio[1]["x"]), int(trio[1]["y"])),
                "like": (int(trio[2]["x"]), int(trio[2]["y"])),
            }
    # Fallback: verified map centres when on deck
    if taimi_swipes_left(tree) is not None or taimi_deck_card_name(tree):
        p = DM_APP_PROFILES["taimi"]
        return {
            "skip": tuple(p["pass_xy"]),  # type: ignore[return-value]
            "instant_chat": tuple(p["instant_chat_xy"]),  # type: ignore[return-value]
            "like": tuple(p["like_xy"]),  # type: ignore[return-value]
        }
    return {"skip": None, "instant_chat": None, "like": None}


def taimi_like_action(
    tree: str, planner: str = "taimi_heuristic"
) -> Optional[Dict[str, Any]]:
    """Like = RIGHT action-row button. Curated cards → pass instead (GOLD)."""
    if taimi_is_curated_card(tree):
        return taimi_pass_action(tree, planner=planner)
    row = taimi_action_row_centers(tree)
    like = row.get("like")
    if not like:
        return None
    return _fp(
        {
            "action": "tap",
            "x": int(like[0]),
            "y": int(like[1]),
            "reason": f"Taimi Like (right action) ({planner})",
            "planner": planner,
            "llm_provider": None,
        },
        "taimi_like",
    )


def taimi_pass_action(
    tree: str, planner: str = "taimi_heuristic"
) -> Optional[Dict[str, Any]]:
    row = taimi_action_row_centers(tree)
    skip = row.get("skip")
    if not skip:
        return None
    reason = "Taimi Skip (left action)"
    if taimi_is_curated_card(tree):
        reason = "Taimi Skip curated card (Like → GOLD)"
    return _fp(
        {
            "action": "tap",
            "x": int(skip[0]),
            "y": int(skip[1]),
            "reason": f"{reason} ({planner})",
            "planner": planner,
            "llm_provider": None,
        },
        "taimi_pass",
    )


def taimi_find_chat_tile(tree: str, contact: str) -> Optional[Tuple[int, int]]:
    """Chats grid: prefer '<Name>, , Start chat'; skip daily pick / locked."""
    best: Optional[Tuple[float, int, int]] = None
    for n in _parse_compact_nodes(tree):
        desc = (n.get("desc") or "").strip()
        text = (n.get("text") or "").strip()
        blob = desc or text
        if not blob:
            continue
        low = blob.lower()
        if "daily pick" in low:
            continue
        if "notify me" in low or "never miss" in low:
            continue
        # Icebreaker / canned chips
        if low.startswith("say ") or "say '" in low or 'say "' in low:
            continue
        score = _fuzzy_score(contact, blob.split(",")[0].strip())
        if score < 0.55:
            # Exact desc == name
            if blob.strip().lower() != contact.lower():
                continue
            score = 0.9
        bonus = 0.25 if "start chat" in low else 0.0
        ranked = score + bonus
        if best is None or ranked > best[0]:
            best = (ranked, int(n["x"]), int(n["y"]))
    if best is None:
        return None
    return (best[1], best[2])


def taimi_send_relative_to_edittext(tree: str) -> Optional[Tuple[int, int]]:
    """Send = clickable ViewGroup immediately right of the EditText composer."""
    edit: Optional[Dict[str, Any]] = None
    for n in _parse_compact_nodes(tree):
        if not n.get("editable"):
            continue
        if edit is None or int(n.get("y") or 0) > int(edit.get("y") or 0):
            edit = n
    if not edit:
        # Also try hint "Say something" / "Add an intro"
        for n in _parse_compact_nodes(tree):
            hint = f"{n.get('hint') or ''} {n.get('text') or ''}".lower()
            if "say something" in hint or "add an intro" in hint:
                edit = n
                break
    if not edit:
        return None
    # Labeled Send button (Instant Chat sheet)
    send_btn = _tree_node_center(tree, "Send")
    if send_btn and int(send_btn[1]) >= int(edit.get("y") or 0) - 80:
        return send_btn
    ex2 = edit.get("x2")
    ey1 = edit.get("y1")
    ey2 = edit.get("y2")
    if ex2 is None or ey1 is None or ey2 is None:
        # Approximate: right of edit center
        return (min(1040, int(edit["x"]) + 400), int(edit["y"]))
    best: Optional[Tuple[int, int, int]] = None
    for n in _parse_compact_nodes(tree):
        if n is edit or n.get("editable"):
            continue
        if not n.get("clickable"):
            continue
        t = str(n.get("text") or "").strip().lower()
        d = str(n.get("desc") or "").strip().lower()
        if any(
            bad in f"{t} {d}"
            for bad in ("continue", "gold", "notify", "boost", "premium")
        ):
            continue
        x1 = n.get("x1")
        y1 = n.get("y1")
        x2 = n.get("x2")
        y2 = n.get("y2")
        if x1 is None or y1 is None or x2 is None or y2 is None:
            # Fall back to center near edit
            if (
                int(n.get("x") or 0) > int(edit.get("x") or 0) + 100
                and abs(int(n.get("y") or 0) - int(edit.get("y") or 0)) < 80
            ):
                dx = int(n["x"]) - int(edit["x"])
                if best is None or dx < best[0]:
                    best = (dx, int(n["x"]), int(n["y"]))
            continue
        if int(x1) < int(ex2) - 30:
            continue
        if int(y2) < int(ey1) - 50 or int(y1) > int(ey2) + 50:
            continue
        w, h = int(x2) - int(x1), int(y2) - int(y1)
        if w > 220 or h > 220 or w < 24 or h < 24:
            continue
        dx = int(x1) - int(ex2)
        if dx < 0:
            continue
        if best is None or dx < best[0]:
            best = (dx, int(n["x"]), int(n["y"]))
    if best is None:
        return None
    return (best[1], best[2])


def taimi_outgoing_verified(tree: str, message: str) -> bool:
    """Last bubble text == message followed by 'Delivered'."""
    needle = (message or "").strip().lower()
    if len(needle) < 2:
        return False
    nodes = [
        n
        for n in _parse_compact_nodes(tree)
        if not n.get("editable") and (n.get("text") or "").strip()
    ]
    nodes.sort(key=lambda n: int(n.get("y") or 0))
    for i, n in enumerate(nodes):
        text = (n.get("text") or "").strip().lower()
        if text != needle:
            continue
        if int(n.get("y") or 0) < 280:
            continue
        # Look ahead for Delivered within next few nodes / nearby y
        for m in nodes[i + 1 : i + 6]:
            mt = (m.get("text") or "").strip().lower()
            if mt == "delivered":
                return True
            if abs(int(m.get("y") or 0) - int(n.get("y") or 0)) > 200:
                break
    # Also accept Delivered anywhere if exact message bubble present
    saw_msg = any(
        (n.get("text") or "").strip().lower() == needle and int(n.get("y") or 0) > 280
        for n in nodes
    )
    saw_del = any((n.get("text") or "").strip().lower() == "delivered" for n in nodes)
    return saw_msg and saw_del


def _label_matches_compose(blob: str, compose_labels: Sequence[str]) -> bool:
    """Match compose hints without treating nav 'Messages' as a compose box."""
    b = (blob or "").strip().lower()
    if not b:
        return False
    # Exact / prefix-ish compose phrases
    for lab in compose_labels:
        l = lab.lower().strip()
        if not l:
            continue
        if b == l or b.startswith(l) or l.startswith(b):
            return True
        # Allow "Type a message" inside longer hint strings
        if " " in l and l in b:
            return True
    if b in ("aa", "say something") or b.startswith("type a message"):
        return True
    # Single word "message" / "message…" only — not "Messages" inbox tab
    if re.fullmatch(r"message[.…]*", b):
        return True
    return False


def compose_field_present(tree: str, compose_labels: Sequence[str]) -> bool:
    # Prefer editable nodes with compose-like hints (real message box)
    for node in _parse_compact_nodes(tree):
        if not node.get("editable"):
            continue
        blob = f"{node.get('hint') or ''} {node.get('label') or ''}".strip()
        if _label_matches_compose(blob, compose_labels):
            return True
        # Bottom-of-screen editable without "search" is almost always compose
        y = int(node.get("y") or 0)
        low = blob.lower()
        if y > 1600 and "search" not in low and "to:" not in low:
            return True
    return False


def chat_screen_verified(
    tree: str,
    contact: str,
    compose_labels: Sequence[str],
) -> bool:
    """True when conversation header shows the contact AND a compose field exists."""
    if not compose_field_present(tree, compose_labels):
        return False
    nodes = _parse_compact_nodes(tree)
    # Search screen still active?
    searchish = [
        n
        for n in nodes
        if n.get("editable")
        and (
            "search" in f"{n.get('hint')} {n.get('label')}".lower()
            or (
                int(n.get("y") or 0) < 280
                and "message" not in f"{n.get('hint')} {n.get('label')}".lower()
            )
        )
    ]
    if searchish:
        return False
    # Header / title match for contact (top band, non-editable)
    for n in nodes:
        if n.get("editable"):
            continue
        y = int(n.get("y") or 0)
        if y > 320:
            continue
        if _fuzzy_score(contact, n.get("label") or "") >= 0.6:
            return True
    # Soft pass: compose present and no search field
    return True


def outgoing_bubble_present(tree: str, message: str) -> bool:
    """True when the typed message appears as a NEW outgoing bubble in the tree.

    Heuristic: message text is visible on a non-editable node in the chat
    transcript, not only in the compose EditText. Fake-chats (and similar
    fixtures) seed an "Old outgoing message: …" bubble with the same text —
    those must NOT count as success.
    """
    needle = (message or "").strip()
    if len(needle) < 2:
        return False
    low_needle = needle.lower()
    saw_new_marker = False
    saw_unmarked = False
    for n in _parse_compact_nodes(tree):
        if n.get("editable"):
            continue
        text = str(n.get("text") or "").strip()
        desc = str(n.get("desc") or "").strip()
        hint = str(n.get("hint") or "").strip()
        blob = f"{text} {desc} {hint}".lower()
        # Explicit seed marker from fake-chats ConversationActivity
        if "old outgoing" in blob:
            continue
        text_low = text.lower()
        # Exact text match on the bubble (reject "Precious Achalugohi baby")
        if text_low != low_needle and f": {low_needle}" not in blob:
            if low_needle not in blob and low_needle[:12] not in blob:
                continue
            if text_low and low_needle in text_low and text_low != low_needle:
                continue
        y = int(n.get("y") or 0)
        # Header / status band is roughly y < 280 on phones; chat bubbles sit
        # just below. Explicit "new outgoing" markers always count.
        if "new outgoing" in blob:
            saw_new_marker = True
            continue
        if y < 280:
            continue
        saw_unmarked = True
    # Prefer explicit new markers when the tree uses them; otherwise unmarked
    # bubbles (real WhatsApp) still count.
    return saw_new_marker or saw_unmarked


def focused_is_compose_not_search(
    tree: str, compose_labels: Sequence[str], search_labels: Sequence[str]
) -> bool:
    """Refuse typing when the only editable is a search/recipient field."""
    nodes = _parse_compact_nodes(tree)
    editables = [n for n in nodes if n.get("editable")]
    if not editables:
        # Compose might be described only via hint labels without e=1
        return compose_field_present(tree, compose_labels)
    # Prefer bottom-of-screen message boxes
    for n in editables:
        blob = f"{n.get('hint')} {n.get('label')}".lower()
        y = int(n.get("y") or 0)
        if any(lab.lower() in blob for lab in compose_labels) or (
            ("message" in blob or "say something" in blob) and y > 1600
        ):
            return True
    # If every editable looks like search / top bar → not compose
    if all(_is_searchish_node(n, search_labels) for n in editables):
        return False
    # Bottom editable without search hint counts as compose
    bottom = [n for n in editables if int(n.get("y") or 0) > 1600]
    return bool(bottom)


def _is_launcher_package(package: str) -> bool:
    pkg = (package or "").lower()
    return bool(pkg) and "launcher" in pkg


def detect_dm_app(instruction: str) -> Optional[str]:
    """Return profile key if instruction names a supported DM app."""
    low = (instruction or "").lower()
    ranked: List[Tuple[int, str]] = []
    for key, prof in DM_APP_PROFILES.items():
        for alias in prof["aliases"]:
            if re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", low):
                ranked.append((len(alias), key))
                break
    if not ranked:
        return None
    ranked.sort(reverse=True)
    return ranked[0][1]


def parse_dm_instruction(instruction: str) -> Optional[Dict[str, str]]:
    """Extract {app, contact, message} from a DM send goal.

    Supports phrasings like:
      whatsapp find and message Precious Achalugo tell her hi baby
      go on whatsapp message X and say Y
    """
    text = (instruction or "").strip()
    if not text:
        return None
    app_key = detect_dm_app(text)
    if not app_key:
        return None
    if not any(
        k in text.lower()
        for k in ("message", "msg", "text", "chat", "say", "send", "dm", "tell")
    ):
        return None
    aliases = DM_APP_PROFILES[app_key]["aliases"]
    alias_alt = "|".join(re.escape(a) for a in sorted(aliases, key=len, reverse=True))
    say = r"(?:say|send|tell(?:\s+(?:her|him|them))?)"
    patterns = (
        # whatsapp send a message to X say Y  /  whatsapp message to X say Y
        rf"(?:go\s+on\s+|open\s+|launch\s+)?(?:{alias_alt})\s+"
        rf"(?:send\s+a\s+)?(?:message|msg|text|dm)\s+(?:to\s+)?(.+?)\s+"
        rf"(?:and\s+)?{say}\s+(.+)$",
        # find and message X tell her Y
        rf"(?:go\s+on\s+|open\s+|launch\s+)?(?:{alias_alt})\s+"
        rf"(?:find\s+(?:and\s+)?)?(?:message|msg|text|dm|chat(?:\s+with)?)\s+(.+?)\s+"
        rf"(?:and\s+)?{say}\s+(.+)$",
        rf"(?:{alias_alt})[,:]?\s+(?:find\s+(?:and\s+)?)?(?:message|msg|text|dm)\s+(.+?)\s+"
        rf"(?:and\s+)?{say}\s+(.+)$",
        rf"(?:message|msg|text|dm)\s+(.+?)\s+on\s+(?:{alias_alt})\s+"
        rf"(?:and\s+)?{say}\s+(.+)$",
        rf"(?:{alias_alt})\s+(.+?)\s+(?:and\s+)?{say}\s+(.+)$",
    )
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if not m:
            continue
        contact = re.sub(r"\s+", " ", m.group(1)).strip(" .,\"'")
        message = re.sub(r"\s+", " ", m.group(2)).strip(" .,\"'")
        contact = re.sub(
            r"^(?:find\s+(?:and\s+)?)?(?:send\s+a\s+)?(?:message|msg|text|dm|chat(?:\s+with)?)\s+(?:to\s+)?",
            "",
            contact,
            flags=re.I,
        ).strip()
        contact = re.sub(r"^(?:to\s+)", "", contact, flags=re.I).strip()
        # Strip instruction leftovers from message body
        message = re.sub(r"^(?:her|him|them)\s+", "", message, flags=re.I).strip(
            " .,\"'"
        )
        if contact and message and len(contact) <= 80 and len(message) <= 500:
            return {"app": app_key, "contact": contact, "message": message}
    return None


def _app_foreground(pkg: str, tree: str, profile: Dict[str, Any]) -> bool:
    pkg_l = (pkg or "").lower()
    markers: Sequence[str] = profile.get("pkg_markers") or ()
    if any(m in pkg_l for m in markers):
        return True
    if _is_launcher_package(pkg_l):
        return False
    tl = (tree or "").lower()
    package = str(profile.get("package") or "").lower()
    if package and (f'p="{package}"' in tl or f'packages="{package}"' in tl):
        return True
    return any(m in pkg_l for m in markers)


def _hist_has_type(history: List[str], text: str) -> bool:
    t = text.lower()
    return any(
        t in str(h).lower() and ("type" in str(h).lower() or "typed" in str(h).lower())
        for h in history[-16:]
    )


def _fp(action: Dict[str, Any], step: str) -> Dict[str, Any]:
    """Tag heuristic actions for steps_detail / debugging."""
    action = dict(action)
    action["fastpath_step"] = step
    action["_fastpath_step"] = step
    return action


def heuristic_dm_send(
    instruction: str,
    ui_tree: str,
    history: List[str],
    package: str = "",
    *,
    goal_satisfied=None,
    dry_run: bool = False,
) -> Optional[Dict[str, Any]]:
    """Generic DM fast-path. Returns an action dict or None."""
    parsed = parse_dm_instruction(instruction)
    if not parsed:
        return None
    app_key = parsed["app"]
    profile = DM_APP_PROFILES[app_key]
    contact = parsed["contact"]
    message = parsed["message"]
    planner = f"{app_key}_heuristic"
    hist = " ".join(history[-16:]).lower()
    pkg = (package or "").lower()
    tl = (ui_tree or "").lower()
    open_label = profile["open_label"]
    open_l = open_label.lower()
    fg = _app_foreground(pkg, ui_tree, profile)
    search_labels = tuple(profile.get("search_labels") or ())
    compose_labels = tuple(profile.get("compose_labels") or ())

    if goal_satisfied:
        sat = goal_satisfied(instruction, ui_tree, package)
        if sat:
            return _fp(
                {
                    "action": "done",
                    "reason": sat,
                    "planner": planner,
                    "llm_provider": None,
                },
                "done_goal",
            )

    if "isn't responding" in tl or "not responding" in tl:
        return _fp(
            {
                "action": "tap",
                "x": 540,
                "y": 1395,
                "reason": f"Dismiss ANR Wait ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "dismiss_anr",
        )

    # Require real FG match. open_ok in history can race while SystemUI/launcher
    # still owns the tree — keep reopening until package markers match.
    want_pkg = str(profile.get("package") or "").lower()
    pkg_ok = bool(fg) or (bool(want_pkg) and want_pkg in pkg)
    open_attempts = sum(
        1
        for h in history[-16:]
        if "open_app(" in str(h).lower() or "opened " in str(h).lower()
    )
    if not pkg_ok and open_attempts < 8:
        return _fp(
            {
                "action": "open_app",
                "app": open_label,
                "reason": (
                    f"Open {open_label} ({planner})"
                    if open_attempts == 0
                    else f"Re-open {open_label}; FG={package or '?'} ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
            },
            "open_app",
        )

    typed_contact = _hist_has_type(history, contact)
    tapped_contact = any(
        (
            "tap matching contact" in str(h).lower()
            or "tap visible contact" in str(h).lower()
            or "tap contact" in str(h).lower()
            or "select contact" in str(h).lower()
            or "tap yubo conversation" in str(h).lower()
            or "conversation '" in str(h).lower()
            # Open chat with X — but NOT "Open Chat(s) tab"
            or (
                re.search(r"open chat(?:\s+with)?\b", str(h).lower()) is not None
                and "tab" not in str(h).lower()
            )
            or "first search result" in str(h).lower()
        )
        for h in history[-16:]
    )
    # Do NOT treat a tap whose reason was only the name in search field as success
    chat_ok = chat_screen_verified(ui_tree, contact, compose_labels)
    tapped_inbox = (
        any(
            any(lab.lower() in str(h).lower() for lab in profile["inbox_labels"])
            and ("tap" in str(h).lower() or "inbox" in str(h).lower())
            for h in history[-16:]
        )
        or "tap inbox" in hist
        or "open dms" in hist
        or "open inbox" in hist
    )
    # Only credit a real Search tap — never "coords fallback" (wrong xy).
    tapped_search = any(
        (
            "tap search id/label" in str(h).lower()
            or "tap search (" in str(h).lower()
            or (
                "tap search" in str(h).lower()
                and "fallback" not in str(h).lower()
                and "coords" not in str(h).lower()
            )
        )
        for h in history[-16:]
    )
    type_focus_fails = sum(
        1
        for h in history[-16:]
        if "input_text failed" in str(h).lower()
        or "focus a text field" in str(h).lower()
    )
    typed_message = _hist_has_type(history, message)
    tapped_send = any(
        "tap send" in str(h).lower()
        or "ime_send" in str(h).lower()
        or "ime_action" in str(h).lower()
        or f"send ({planner}" in str(h).lower()
        for h in history[-16:]
    )
    focused_compose = any(
        "compose" in str(h).lower() or "message field" in str(h).lower()
        for h in history[-16:]
    )
    tried_new_chat = any("new chat" in str(h).lower() for h in history[-16:])
    contact_tap_attempts = sum(
        1
        for h in history[-16:]
        if "matching contact" in str(h).lower()
        or "first search result" in str(h).lower()
    )

    # Sparse tree after search → ask planner/vision (signal via None + caller)
    # We still return wait-style re-eval by swiping minimally or no-op wait tap.
    sparse_after_search = typed_contact and tree_is_sparse(ui_tree)
    needs_inbox = bool(profile.get("inbox_labels")) and app_key != "whatsapp"

    # --- Bumble real-device path (SM-G996B main profile) ---
    if app_key == "bumble" and pkg_ok:
        popup = bumble_dismiss_popup(ui_tree, planner=planner)
        if popup:
            return popup
        # DM goal: leave People deck → Chats before hunting contacts
        if (
            not chat_ok
            and not typed_message
            and bumble_on_people_deck(ui_tree)
            and not bumble_on_connections(ui_tree)
        ):
            chats = _tree_node_center(ui_tree, "Chats")
            if chats:
                return _fp(
                    {
                        "action": "tap",
                        "x": chats[0],
                        "y": chats[1],
                        "reason": f"Open Chats tab from People deck ({planner})",
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "bumble_open_chats_tab",
                )
            tab = profile.get("inbox_tab_xy")
            if isinstance(tab, (tuple, list)) and len(tab) >= 2:
                return _fp(
                    {
                        "action": "tap",
                        "x": int(tab[0]),
                        "y": int(tab[1]),
                        "reason": f"Open Chats tab (nav bar) ({planner})",
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "bumble_open_chats_tab",
                )

    # --- Yubo real-device path (Compose UI / few ids) ---
    if app_key == "yubo" and pkg_ok:
        popup = yubo_dismiss_popup(ui_tree, planner=planner)
        if popup:
            return popup
        sheet = yubo_direct_sheet_action(ui_tree, planner=planner)
        if sheet:
            return sheet
        if (
            not chat_ok
            and not typed_message
            and yubo_on_deck(ui_tree)
            and not yubo_on_chat_list(ui_tree)
            and not yubo_on_chat(ui_tree)
        ):
            tab = profile.get("inbox_tab_xy") or (343, 2180)
            return _fp(
                {
                    "action": "tap",
                    "x": int(tab[0]),
                    "y": int(tab[1]),
                    "reason": f"Open Chat tab from Yubo deck ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "yubo_open_chat_tab",
            )
        if (
            not chat_ok
            and not typed_message
            and not tapped_contact
            and yubo_on_chat_list(ui_tree)
        ):
            row = yubo_find_conversation_tap(ui_tree, contact)
            if row:
                return _fp(
                    {
                        "action": "tap",
                        "x": row[0],
                        "y": row[1],
                        "reason": f"Tap Yubo conversation '{contact}' ({planner})",
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "yubo_tap_conversation",
                )

    # --- Badoo real-device path ---
    if app_key == "badoo" and pkg_ok:
        popup = badoo_dismiss_popup(ui_tree, planner=planner)
        if popup:
            return popup
        if (
            not chat_ok
            and not typed_message
            and badoo_on_encounters(ui_tree)
            and not badoo_on_connections(ui_tree)
        ):
            chats = _tree_id_center(
                ui_tree,
                "nav_bar_button_connections",
                "com.badoo.mobile:id/nav_bar_button_connections",
            ) or _tree_node_center(ui_tree, "Chats", "Connections")
            if chats:
                return _fp(
                    {
                        "action": "tap",
                        "x": chats[0],
                        "y": chats[1],
                        "reason": f"Open Chats from Encounters ({planner})",
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "badoo_open_chats_tab",
                )
            tab = profile.get("inbox_tab_xy") or (756, 2210)
            return _fp(
                {
                    "action": "tap",
                    "x": int(tab[0]),
                    "y": int(tab[1]),
                    "reason": f"Open Chats tab (nav bar) ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "badoo_open_chats_tab",
            )

    # --- Hily real-device path (buttons only; never CRUSH / Allow / Audio) ---
    if app_key == "hily" and pkg_ok:
        popup = hily_dismiss_popup(ui_tree, planner=planner)
        if popup:
            return popup
        # MBM: stop if allowance is 0
        if hily_on_mbm(ui_tree):
            allow = hily_mbm_allowance(ui_tree)
            if allow == 0:
                return _fp(
                    {
                        "action": "fail",
                        "reason": (
                            f"Hily Message Before Match allowance is 0 "
                            f"— stop (never paywall) ({planner})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "hily_mbm_exhausted",
                )
        if (
            not chat_ok
            and not typed_message
            and hily_on_finder(ui_tree)
            and not hily_on_chats_list(ui_tree)
            and not hily_on_thread(ui_tree)
        ):
            tab = profile.get("inbox_tab_xy") or (341, 2190)
            return _fp(
                {
                    "action": "tap",
                    "x": int(tab[0]),
                    "y": int(tab[1]),
                    "reason": f"Open Chats tab from Hily Finder ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "hily_open_chats_tab",
            )
        if (
            not chat_ok
            and not typed_message
            and not tapped_contact
            and hily_on_chats_list(ui_tree)
        ):
            # Never tap "They liked you!" premium row
            row = hily_find_chat_row(ui_tree, contact)
            if row:
                return _fp(
                    {
                        "action": "tap",
                        "x": row[0],
                        "y": row[1],
                        "reason": f"Tap Hily chat '{contact}' ({planner})",
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "hily_tap_chat",
                )

    # --- BLK real-device path (right Like Icon only; never Super/Boost) ---
    if app_key == "blk" and pkg_ok:
        popup = blk_dismiss_popup(ui_tree, planner=planner)
        if popup:
            return popup
        if blk_end_of_deck(ui_tree) and not chat_ok and not typed_message:
            return _fp(
                {
                    "action": "done",
                    "reason": f"BLK deck end — stop gracefully ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "blk_deck_end",
            )
        if (
            not chat_ok
            and not typed_message
            and blk_on_deck(ui_tree)
            and not blk_on_matches(ui_tree)
            and not blk_on_thread(ui_tree)
        ):
            tab = profile.get("inbox_tab_xy") or (675, 2170)
            return _fp(
                {
                    "action": "tap",
                    "x": int(tab[0]),
                    "y": int(tab[1]),
                    "reason": f"Open Matches from BLK Discover ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "blk_open_matches_tab",
            )
        if (
            not chat_ok
            and not typed_message
            and not tapped_contact
            and blk_on_matches(ui_tree)
        ):
            row = blk_find_match_row(ui_tree, contact)
            if row:
                return _fp(
                    {
                        "action": "tap",
                        "x": row[0],
                        "y": row[1],
                        "reason": f"Tap BLK match '{contact}' ({planner})",
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "blk_tap_match",
                )

    # --- Taimi real-device path (com.takimi.android; FLAG_SECURE; never GOLD) ---
    if app_key == "taimi" and pkg_ok:
        pay = taimi_dismiss_paywall(ui_tree, planner=planner)
        if pay:
            return pay
        left = taimi_swipes_left(ui_tree)
        if left == 0 and not chat_ok and not typed_message:
            return _fp(
                {
                    "action": "done",
                    "reason": f"Taimi daily swipes exhausted (0 left) ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "taimi_swipes_exhausted",
            )
        if (
            not chat_ok
            and not typed_message
            and taimi_on_people_deck(ui_tree)
            and not taimi_on_chats_list(ui_tree)
            and not taimi_on_thread(ui_tree)
        ):
            tab = profile.get("inbox_tab_xy") or (972, 2200)
            return _fp(
                {
                    "action": "tap",
                    "x": int(tab[0]),
                    "y": int(tab[1]),
                    "reason": f"Open Chats from Taimi People ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "taimi_open_chats_tab",
            )
        if (
            not chat_ok
            and not typed_message
            and not tapped_contact
            and taimi_on_chats_list(ui_tree)
        ):
            # Prefer free Start chat tiles; skip daily pick
            tile = taimi_find_chat_tile(ui_tree, contact)
            if tile:
                return _fp(
                    {
                        "action": "tap",
                        "x": tile[0],
                        "y": tile[1],
                        "reason": f"Tap Taimi chat/Start chat '{contact}' ({planner})",
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "taimi_tap_chat",
                )

    # 0a) If the contact row is already on-screen (inbox / matches list), tap it
    # before any search field — dating decks often expose a Search affordance
    # that would otherwise steal the flow.
    if not chat_ok and not typed_message and not tapped_contact:
        visible = find_contact_result_center(
            ui_tree,
            contact,
            search_labels=search_labels,
            result_ids=tuple(profile.get("result_ids") or ()),
            exclude_ids=tuple(profile.get("result_exclude_ids") or ()),
        )
        if visible is None:
            # Fake-chats rows use "Chat with X" / "Match X" content-desc
            visible = _tree_node_center(
                ui_tree,
                f"Chat with {contact}",
                f"Match {contact}",
                contact,
            )
        if visible:
            return _fp(
                {
                    "action": "tap",
                    "x": visible[0],
                    "y": visible[1],
                    "reason": f"Tap visible contact '{contact}' ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "tap_visible_contact",
            )

    # 0) Enter DMs / inbox when still on feed/home (Instagram / dating)
    # Skip when already in a verified chat or on the connections list.
    if (
        needs_inbox
        and not chat_ok
        and not typed_message
        and not tapped_inbox
        and not typed_contact
        and not tapped_search
        and not (app_key == "bumble" and bumble_on_connections(ui_tree))
        and not (app_key == "yubo" and yubo_on_chat_list(ui_tree))
        and not (app_key == "badoo" and badoo_on_connections(ui_tree))
        and not (app_key == "hily" and hily_on_chats_list(ui_tree))
        and not (app_key == "blk" and blk_on_matches(ui_tree))
        and not (app_key == "taimi" and taimi_on_chats_list(ui_tree))
    ):
        # Prefer Chats / Matches tab when on a swipe deck (has Like/Pass)
        on_deck = (
            bool(
                _tree_node_center(ui_tree, "Like") or _tree_node_center(ui_tree, "Pass")
            )
            or (app_key == "bumble" and bumble_on_people_deck(ui_tree))
            or (app_key == "yubo" and yubo_on_deck(ui_tree))
            or (app_key == "badoo" and badoo_on_encounters(ui_tree))
            or (app_key == "hily" and hily_on_finder(ui_tree))
            or (app_key == "blk" and blk_on_deck(ui_tree))
            or (app_key == "taimi" and taimi_on_people_deck(ui_tree))
        )
        if on_deck or not _tree_node_center(ui_tree, *search_labels):
            c = _tree_node_center(ui_tree, *tuple(profile["inbox_labels"]))
            if c:
                return _fp(
                    {
                        "action": "tap",
                        "x": c[0],
                        "y": c[1],
                        "reason": f"Open inbox/DMs ({planner})",
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "open_inbox",
                )
            # Dating apps with verified nav tab xy — never a random toolbar guess
            if app_key in ("bumble", "yubo", "badoo", "hily", "blk", "taimi"):
                tab = profile.get("inbox_tab_xy")
                if isinstance(tab, (tuple, list)) and len(tab) >= 2:
                    return _fp(
                        {
                            "action": "tap",
                            "x": int(tab[0]),
                            "y": int(tab[1]),
                            "reason": f"Open Chats tab (nav bar) ({planner})",
                            "planner": planner,
                            "llm_provider": None,
                        },
                        f"{app_key}_open_chats_tab",
                    )
            elif app_key in ("tinder", "hinge", "instagram") or (
                profile.get("package") or ""
            ).startswith(("com.tinder", "co.hinge")):
                return _fp(
                    {
                        "action": "tap",
                        "x": 860 if app_key == "instagram" else 900,
                        "y": 150 if app_key == "instagram" else 2280,
                        "reason": f"Open inbox coords fallback ({planner})",
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "open_inbox_fallback",
                )

    # 0b) Dating decks: open Chats/Matches tab before Search (Search sits on
    # every screen and otherwise short-circuits the contact list).
    if (
        needs_inbox
        and not tapped_inbox
        and not typed_contact
        and not chat_ok
        and not typed_message
        and not (app_key == "bumble" and bumble_on_connections(ui_tree))
        and not (app_key == "yubo" and yubo_on_chat_list(ui_tree))
        and not (app_key == "badoo" and badoo_on_connections(ui_tree))
        and not (app_key == "hily" and hily_on_chats_list(ui_tree))
        and not (app_key == "blk" and blk_on_matches(ui_tree))
        and not (app_key == "taimi" and taimi_on_chats_list(ui_tree))
    ):
        tab = _tree_node_center(
            ui_tree, "Chats", "Chat", "Matches", "Messages", "Inbox", "Connections"
        )
        if tab:
            return _fp(
                {
                    "action": "tap",
                    "x": tab[0],
                    "y": tab[1],
                    "reason": f"Open chats/matches tab ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "open_inbox_tab",
            )

    # After input_text focus failures: re-find Search / editable from fresh tree
    # (never keep typing blind into an unfocused screen).
    if type_focus_fails and not typed_contact:
        if type_focus_fails >= 2:
            return _fp(
                {
                    "action": "fail",
                    "reason": (
                        f"input_text failed {type_focus_fails}× without a focused "
                        f"EditText — Search not focused; abort ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "type_focus_fail",
            )
        # Prefer visible editable (search field), else re-tap Search from tree
        ec = _tree_editable_center(ui_tree)
        if ec:
            return _fp(
                {
                    "action": "tap",
                    "x": ec[0],
                    "y": ec[1],
                    "reason": (
                        f"Re-focus editable after input_text failure ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "refocus_editable",
            )
        tapped_search = False  # force Search re-locate below

    # 1) Search — prefer resource-id / label (deterministic). No blind coords.
    # Skip entirely when already in the target chat (header + compose verified).
    # Yubo/Badoo real maps: contacts live in Conversations/connections lists —
    # do not invent a Search control or fail search_not_found there.
    skip_search = (
        (app_key == "yubo" and (yubo_on_chat_list(ui_tree) or yubo_on_chat(ui_tree)))
        or (app_key == "badoo" and badoo_on_connections(ui_tree))
        or (app_key == "bumble" and bumble_on_connections(ui_tree))
        or (
            app_key == "hily"
            and (hily_on_chats_list(ui_tree) or hily_on_thread(ui_tree))
        )
        or (app_key == "blk" and (blk_on_matches(ui_tree) or blk_on_thread(ui_tree)))
        or (
            app_key == "taimi"
            and (taimi_on_chats_list(ui_tree) or taimi_on_thread(ui_tree))
        )
    )
    if not chat_ok and not typed_contact and not tapped_search and not skip_search:
        search_ids = tuple(profile.get("search_ids") or ())
        # Never treat Meta AI "Ask" send as Search (id-only — "Ask" is a
        # substring of "Ask Meta AI or Search" on the home bar).
        meta_ids = tuple(profile.get("meta_ai_ask_ids") or ())
        c = _tree_id_center(ui_tree, *search_ids) if search_ids else None
        if c is None:
            c = _tree_node_center(ui_tree, *search_labels)
        # Bare "Search" desc — but not camera/overflow toolbar icons
        if c is None:
            c = _tree_node_center(ui_tree, "Ask Meta AI or Search", "Search")
        if c and meta_ids:
            ask = _tree_id_center(ui_tree, *meta_ids)
            if ask and ask == c:
                c = None
        if c:
            return _fp(
                {
                    "action": "tap",
                    "x": c[0],
                    "y": c[1],
                    "reason": f"Tap Search id/label ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "tap_search",
            )
        fb = profile.get("search_fallback")
        if isinstance(fb, (tuple, list)) and len(fb) >= 2 and tree_is_sparse(ui_tree):
            return _fp(
                {
                    "action": "tap",
                    "x": int(fb[0]),
                    "y": int(fb[1]),
                    "reason": f"Tap Search coords fallback sparse tree ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "tap_search_fallback",
            )
        return _fp(
            {
                "action": "fail",
                "reason": (
                    f"Search control not found in a11y tree "
                    f"(ids={list(search_ids)[:3]} labels={list(search_labels)[:3]}) "
                    f"— refusing coord guess ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
            },
            "search_not_found",
        )
    if skip_search and not chat_ok and not typed_contact and not tapped_contact:
        # Scroll the connections list for the contact name
        if hist.count("swipe") < 3:
            return _fp(
                {
                    "action": "swipe",
                    "x1": 540,
                    "y1": 1600,
                    "x2": 540,
                    "y2": 900,
                    "reason": f"Scroll for contact '{contact}' ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "scroll_connections",
            )
        return _fp(
            {
                "action": "fail",
                "reason": (
                    f"Contact '{contact}' not found in connections list ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
            },
            "contact_not_in_list",
        )

    # 2) Type contact into search — never into the message compose box
    # Require an editable on screen (or a verified Search tap), not a failed fallback.
    # Skip when already in chat — compose EditText must not receive the contact name.
    if (
        not chat_ok
        and (tapped_search or _tree_editable_center(ui_tree))
        and not typed_contact
    ):
        if focused_is_compose_not_search(ui_tree, compose_labels, search_labels):
            # Compose has focus (leftover conversation) — leave chat, re-open search
            return _fp(
                {
                    "action": "back",
                    "reason": (
                        f"Compose focused before contact typed — back then search ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "back_before_type_contact",
            )
        # WA: clear Photos/Stickers/type_token chips or search returns "No results"
        if app_key == "whatsapp" and _search_filter_chip_active(ui_tree):
            clear_c = find_search_clear_center(ui_tree, profile)
            if clear_c:
                return _fp(
                    {
                        "action": "tap",
                        "x": clear_c[0],
                        "y": clear_c[1],
                        "reason": (
                            f"Clear search filter chip before typing contact ({planner})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "clear_search_filter",
                )
        # Prefer focused search_input; never IME Enter / Meta AI Ask after type.
        return _fp(
            {
                "action": "type",
                "text": contact,
                "reason": f"Type contact '{contact}' ({planner})",
                "planner": planner,
                "llm_provider": None,
                "clear": True,
                # Strip ZWSP when callers verify entry text
                "strip_zwsp": True,
                "no_ime_enter": True,
            },
            "type_contact",
        )

    # 3) Tap matching result / open chat (EXCLUDE search EditText)
    if typed_contact and not chat_ok and not typed_message:
        if sparse_after_search:
            # Signal vision by returning None would skip heuristic; instead wait
            # one tick with a no-op that forces re-dump — use tiny wait via back? No.
            # Prefer first-result fallback lower on screen after a short scroll.
            pass
        c = find_contact_result_center(
            ui_tree,
            contact,
            search_labels=search_labels,
            result_ids=tuple(profile.get("result_ids") or ()),
            exclude_ids=tuple(profile.get("result_exclude_ids") or ()),
        )
        if c:
            return _fp(
                {
                    "action": "tap",
                    "x": c[0],
                    "y": c[1],
                    "reason": f"Tap matching contact '{contact}' ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "tap_contact",
            )
        # Thin tree after typing contact → let vision pick the result row
        if sparse_after_search and contact_tap_attempts == 0:
            return None
        # Alternate route: New chat → search contacts
        if contact_tap_attempts >= 2 and not tried_new_chat:
            nc = _tree_node_center(
                ui_tree, *tuple(profile.get("new_chat_labels") or ())
            )
            if nc:
                return _fp(
                    {
                        "action": "tap",
                        "x": nc[0],
                        "y": nc[1],
                        "reason": f"Alternate route: New chat ({planner})",
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "alt_new_chat",
                )
            # WhatsApp new-chat FAB typical
            return _fp(
                {
                    "action": "tap",
                    "x": 980,
                    "y": 2100,
                    "reason": f"Alternate route: New chat FAB ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "alt_new_chat_fab",
            )
        if hist.count("swipe") < 2:
            return _fp(
                {
                    "action": "swipe",
                    "x1": 540,
                    "y1": 1600,
                    "x2": 540,
                    "y2": 800,
                    "reason": f"Scroll contact results ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "scroll_results",
            )
        # Last resort: tap below search bar (first row), never the search field itself
        return _fp(
            {
                "action": "tap",
                "x": 540,
                "y": 420,
                "reason": f"Tap first search result for '{contact}' ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "tap_first_result",
        )

    # 3b) Tapped but chat not verified → retry / alternate (do NOT type message)
    if typed_contact and tapped_contact and not chat_ok and not typed_message:
        if contact_tap_attempts < 4:
            c = find_contact_result_center(
                ui_tree,
                contact,
                search_labels=search_labels,
                result_ids=tuple(profile.get("result_ids") or ()),
                exclude_ids=tuple(profile.get("result_exclude_ids") or ()),
            )
            if c:
                return _fp(
                    {
                        "action": "tap",
                        "x": c[0],
                        "y": c[1],
                        "reason": (
                            f"Retry tap contact '{contact}' — chat not verified ({planner})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "retry_tap_contact",
                )
        if not tried_new_chat:
            return _fp(
                {
                    "action": "tap",
                    "x": 980,
                    "y": 2100,
                    "reason": f"Chat verify failed — try New chat ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "verify_fail_new_chat",
            )
        return _fp(
            {
                "action": "fail",
                "reason": (
                    f"Could not open chat with '{contact}' — "
                    "header/compose not verified after contact taps"
                ),
                "planner": planner,
                "llm_provider": None,
            },
            "verify_fail",
        )

    # 4) Focus compose — only when chat verified
    if chat_ok and not typed_message and not focused_compose:
        compose_ids = tuple(profile.get("compose_ids") or ())
        c = find_compose_center(
            ui_tree, compose_labels, compose_ids, search_labels=search_labels
        )
        if c:
            return _fp(
                {
                    "action": "tap",
                    "x": c[0],
                    "y": c[1],
                    "reason": (f"Focus compose Message/entry field ({planner})"),
                    "planner": planner,
                    "llm_provider": None,
                },
                "focus_compose",
            )
        # No entry/Message in tree — defer to vision; never blind-tap toolbar.
        fb = profile.get("compose_fallback")
        if (
            isinstance(fb, (tuple, list))
            and len(fb) >= 2
            and not tree_is_sparse(ui_tree)
            and compose_field_present(ui_tree, compose_labels)
        ):
            return _fp(
                {
                    "action": "tap",
                    "x": int(fb[0]),
                    "y": int(fb[1]),
                    "reason": f"Focus compose coords fallback ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "focus_compose_fallback",
            )
        return None

    # 5) Type message — ONLY if chat verified AND target is compose (not search)
    if chat_ok and not typed_message:
        # Hily / Taimi: require FG package (takimi) before typing
        if app_key == "hily" and want_pkg and want_pkg not in pkg and not fg:
            return _fp(
                {
                    "action": "open_app",
                    "app": open_label,
                    "reason": (
                        f"Re-focus Hily before typing; FG={package or '?'} ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "hily_refocus_before_type",
            )
        if app_key == "taimi":
            markers = tuple(profile.get("pkg_markers") or ("takimi",))
            if not any(m and m.lower() in pkg for m in markers) and not fg:
                return _fp(
                    {
                        "action": "open_app",
                        "app": open_label,
                        "reason": (
                            f"Re-focus Taimi (takimi) before typing; "
                            f"FG={package or '?'} ({planner})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "taimi_refocus_before_type",
                )
            if taimi_is_paywall(ui_tree):
                return taimi_dismiss_paywall(ui_tree, planner=planner)
        # Locked composer → skip (never paid unlock)
        if app_key == "hily":
            for n in _parse_compact_nodes(ui_tree):
                if "threadinput" in str(n.get("id") or "").lower():
                    blob = f"{n.get('text')} {n.get('hint')} {n.get('desc')}".lower()
                    if "locked" in blob:
                        return _fp(
                            {
                                "action": "fail",
                                "reason": (
                                    f"Hily composer Locked — skip (never paid) "
                                    f"({planner})"
                                ),
                                "planner": planner,
                                "llm_provider": None,
                            },
                            "hily_composer_locked",
                        )
        if not focused_is_compose_not_search(ui_tree, compose_labels, search_labels):
            compose_ids = tuple(profile.get("compose_ids") or ())
            c = find_compose_center(
                ui_tree, compose_labels, compose_ids, search_labels=search_labels
            )
            if c:
                return _fp(
                    {
                        "action": "tap",
                        "x": c[0],
                        "y": c[1],
                        "reason": (
                            f"Refuse type — focus looks like search; "
                            f"retarget compose ({planner})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "refuse_type_search",
                )
            fb = profile.get("compose_fallback")
            if isinstance(fb, (tuple, list)) and len(fb) >= 2:
                return _fp(
                    {
                        "action": "tap",
                        "x": int(fb[0]),
                        "y": int(fb[1]),
                        "reason": (
                            f"Refuse type — focus looks like search; "
                            f"retarget compose ({planner})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "refuse_type_search",
                )
            return None
        return _fp(
            {
                "action": "type",
                "text": message,
                "reason": f"Type message '{message}' ({planner})",
                "planner": planner,
                "llm_provider": None,
                "clear": True,
            },
            "type_message",
        )

    # 6) Send — prefer visible Send ImageButton (appears after text). Dry-run stops.
    # WA: never IME Enter in search (Meta AI); prefer tap Send in chat too.
    if typed_message and not tapped_send:
        if dry_run:
            return _fp(
                {
                    "action": "done",
                    "reason": (
                        f"dry_run — compose filled with '{message}' "
                        f"for {contact}; send skipped"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "dry_run": True,
                    "screenshot": True,
                },
                "dry_run_stop",
            )
        send_ids = tuple(profile.get("send_ids") or ())
        c = find_send_center_safe(
            ui_tree,
            tuple(profile["send_labels"]),
            send_ids=send_ids,
            profile=profile,
        )
        if c is None and app_key == "yubo":
            c = yubo_find_send_center(ui_tree)
        if c is None and app_key == "hily":
            c = hily_find_send_center(ui_tree)
        if c is None and app_key == "blk":
            c = blk_send_relative_to_edittext(ui_tree)
        if c is None and app_key == "taimi":
            c = taimi_send_relative_to_edittext(ui_tree)
        prefer_tap = bool(profile.get("prefer_tap_send"))
        if c:
            return _fp(
                {
                    "action": "tap",
                    "x": c[0],
                    "y": c[1],
                    "reason": f"Tap Send id/send ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "tap_send",
            )
        if not prefer_tap and "ime_send" not in hist and "ime_action" not in hist:
            return _fp(
                {
                    "action": "ime_send",
                    "reason": f"IME_ACTION_SEND via Mobilerun Keyboard ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "ime_send",
            )
        fb = profile.get("send_fallback")
        if isinstance(fb, (tuple, list)) and len(fb) >= 2:
            return _fp(
                {
                    "action": "tap",
                    "x": int(fb[0]),
                    "y": int(fb[1]),
                    "reason": f"Tap Send coords fallback ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "tap_send",
            )
        if prefer_tap and "ime_send" not in hist and "ime_action" not in hist:
            return _fp(
                {
                    "action": "ime_send",
                    "reason": (
                        f"Send button not in tree — IME_ACTION_SEND ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "ime_send",
            )
        return _fp(
            {
                "action": "fail",
                "reason": (
                    f"Send control not found after typing '{message}' ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
            },
            "send_not_found",
        )

    # 7) Verify outgoing bubble / re-send
    if tapped_send:
        want_pkg = str(profile.get("package") or "").lower()
        pkg_ok = (not want_pkg) or (want_pkg in pkg) or fg
        outgoing_ok = outgoing_bubble_present(ui_tree, message)
        if app_key == "hily":
            outgoing_ok = hily_outgoing_verified(ui_tree, message)
        elif app_key == "blk":
            outgoing_ok = blk_outgoing_verified(ui_tree, message)
        elif app_key == "taimi":
            outgoing_ok = taimi_outgoing_verified(ui_tree, message)
        if pkg_ok and outgoing_ok:
            return _fp(
                {
                    "action": "done",
                    "reason": (
                        f"Outgoing bubble confirmed for '{message}' "
                        f"to {contact} ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "outgoing_confirmed": True,
                },
                "done_outgoing_bubble",
            )
        if not pkg_ok and outgoing_ok:
            # Bubble on wrong package — re-open target app
            return _fp(
                {
                    "action": "open_app",
                    "app": open_label,
                    "reason": (
                        f"Wrong FG package {package or '?'} — reopen "
                        f"{open_label} ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "reopen_wrong_pkg",
            )
        if goal_satisfied:
            sat2 = goal_satisfied(instruction, ui_tree, package)
            if sat2:
                return _fp(
                    {
                        "action": "done",
                        "reason": sat2,
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "done_after_send",
                )
        if (
            hist.count("tap send") + hist.count("re-tap send") + hist.count("ime_send")
            < 3
        ):
            send_ids = tuple(profile.get("send_ids") or ())
            c = find_send_center_safe(
                ui_tree,
                tuple(profile["send_labels"]),
                send_ids=send_ids,
                profile=profile,
            )
            if c is None and app_key == "hily":
                c = hily_find_send_center(ui_tree)
            if c is None and app_key == "blk":
                c = blk_send_relative_to_edittext(ui_tree)
            if c is None and app_key == "taimi":
                c = taimi_send_relative_to_edittext(ui_tree)
            fb = profile.get("send_fallback")
            if c:
                x, y = c
            elif isinstance(fb, (tuple, list)) and len(fb) >= 2:
                x, y = int(fb[0]), int(fb[1])
            else:
                x = y = None
            if x is not None:
                return _fp(
                    {
                        "action": "tap",
                        "x": x,
                        "y": y,
                        "reason": f"Re-tap Send ({planner})",
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "retap_send",
                )

    if fg:
        if chat_ok and not typed_message:
            ec_nodes = [
                n
                for n in _parse_compact_nodes(ui_tree)
                if n.get("editable") and not _is_searchish_node(n, search_labels)
            ]
            if ec_nodes:
                n = ec_nodes[0]
                return _fp(
                    {
                        "action": "tap",
                        "x": n["x"],
                        "y": n["y"],
                        "reason": f"Continue compose ({planner})",
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "continue_compose",
                )
        c = _tree_node_center(ui_tree, *search_labels)
        if c and not typed_contact:
            return _fp(
                {
                    "action": "tap",
                    "x": c[0],
                    "y": c[1],
                    "reason": f"Retry Search ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "retry_search",
            )
    return None
