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
        # CA-4: coordinate like-swipe is opt-in via instruction/state mode "fixed".
        "fixed_swipe": False,
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
        "people_tab_xy": (540, 2197),  # People [432..648] — photo GRID, not deck
        # Discover card stack (pass/like) — left of People on S21 (22 Nov dry-run)
        "discover_tab_xy": (324, 2197),
        "deck_tab_xy": (324, 2197),
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
        # NEVER tap these (undo / paid / AV / photo browser SuperSwipe)
        "never_tap_ids": (
            "toolbar_backtrackContainer",
            "profile_details_badgeSuperSwipe",
            "chatToolbar_audioChatButton",
            "chatToolbar_videoChatButton",
            "connections_stickyPromoContainer",
            "photoBrowser_superswipe",
            "id/photoBrowser_superswipe",
            "com.bumble.app:id/photoBrowser_superswipe",
        ),
        "never_tap_labels": (
            "Send a compliment",
            "Undo",
            "SuperSwipe",
            "Send SuperSwipe",
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
        # Bottom nav: no text/desc on real device — map by index (22 Nov)
        # x≈341/540/739/938 y≈2194 (Chat / Likes / Friends / More); deck left of these
        "nav_y": 2194,
        "deck_tab_xy": (140, 2194),
        "inbox_tab_xy": (341, 2194),  # Chat — index 0 of unlabeled row
        "likes_tab_xy": (540, 2194),
        "friends_tab_xy": (739, 2194),
        "more_tab_xy": (938, 2194),
        "tab_xy_by_index": ((341, 2194), (540, 2194), (739, 2194), (938, 2194)),
        "inbox_tab_index": 0,
        "inbox_labels": ("Chat", "Chats", "Conversations", "Messages"),
        "inbox_tab_labels": ("Chat",),
        "allow_index_tab_fallback": True,
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
        # CA-4: coordinate like-swipe is opt-in via instruction/state mode "fixed".
        "fixed_swipe": False,
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
            "Treasure",  # promo / freebie row — not a person chat
            "Open Treasure",
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
        # Real-device map: Mac SM-G996B / S21+ 1080x2400 (22 Nov).
        # Discover + Matches LIST have NO a11y — screenshot/vision for taps there.
        # Like sheet, Rose sheet, thread, Play review ARE in a11y tree.
        "aliases": ("hinge",),
        "package": "co.hinge.app",
        "pkg_markers": ("hinge",),
        "open_label": "Hinge",
        "launch_activity": "co.hinge.app/.ui.AppActivity",
        "open_settle_s": 5.0,
        "family": "swipe",
        "intent_only_open": True,  # never home_drawer_search
        "sparse_main_tabs": True,  # Discover/Matches list → vision
        "inbox_labels": ("Matches", "Messages", "Chats", "Liked You", "Inbox"),
        "inbox_tab_labels": ("Matches",),
        # Bottom nav centres (x, y≈2195): Discover / Standouts / Likes You / Matches / Profile
        "deck_tab_xy": (110, 2195),  # Discover
        "standouts_tab_xy": (323, 2195),
        "likes_tab_xy": (539, 2195),  # Likes You
        "inbox_tab_xy": (754, 2195),  # Matches
        # First "Your turn" row centre on SM-G996B 1080x2400 (empty-tree fallback)
        "top_chat_xy": (540, 480),
        "profile_tab_xy": (970, 2195),
        # Discover: skip / rewind (vision); heart x≈937; Dating Intent chip PAID
        "skip_xy": (115, 2000),
        "rewind_xy": (115, 1830),  # PAID
        "dating_intent_chip_xy": (960, 160),  # Hinge+ paywall — NEVER
        "like_heart_x": 937,
        # Like sheet (a11y)
        "like_comment_bounds": (95, 1015, 985, 1190),
        "rose_button_bounds": (95, 1225, 355, 1330),  # PAID left
        "send_like_xy": (686, 1277),
        "friends_interstitial_close_xy": (989, 201),  # wait 3s before tap
        "paywall_close_xy": (77, 134),
        "dating_prefs_back_xy": (63, 154),
        "new_chat_labels": ("Matches", "Your turn", "Their turn"),
        "search_labels": ("Search", "Search…"),
        "search_ids": ("id/likes_search", "id/likes_search_input"),
        "search_fallback": None,
        "result_ids": ("id/like_row", "id/like_name"),
        "header_ids": ("id/conversation_title",),
        "compose_labels": (
            "Send a message",
            "Type a message",
            "Message",
            "Your message",
            "Say something",
            "Add a comment",
        ),
        "compose_ids": ("id/your_message", ":id/your_message"),
        "send_labels": ("Send Like", "Send message", "Send", "Send Like anyway"),
        "send_ids": ("id/send_message", ":id/send_message"),
        "send_message_desc": "Send message",
        "send_fallback": None,
        "compose_fallback": None,
        "prefer_tap_send": True,
        "prefer_clear_before_type": True,
        "never_tap_labels": (
            "Rose",
            "Send a Rose",
            "Boost",
            "Super Boost",
            "Preferred",
            "HingeX",
            "Hinge X",
            "Hinge+",
            "HingeOne",
            "Hinge One",
            "Dating Intent",
            "Super Like",
            "Send Super Like",
            "Standouts",
            "Enable for",
            "Rewind",
        ),
        "never_tap_ids": (),
        "notif_dismiss_xy": (985, 396),
        "thread_back_xy": (69, 130),
    },
    "tagged": {
        # Real-device map: Mac S21+ 1080x2400 (22 Nov).
        "aliases": ("tagged",),
        "package": "com.taggedapp",
        "pkg_markers": ("tagged",),
        "open_label": "Tagged",
        "open_settle_s": 5.0,
        "family": "swipe",
        "nav_y": 2200,
        "deck_tab_xy": (108, 2200),  # tab_nearby
        "live_tab_xy": (324, 2200),  # tab_live — never Go Live FAB
        "match_game_tab_xy": (540, 2200),  # tab_match_game
        "inbox_tab_xy": (756, 2200),  # tab_chats
        "notif_tab_xy": (972, 2200),  # tab_notification
        "inbox_tab_ids": ("tab_chats", "id/tab_chats"),
        "deck_tab_ids": ("tab_nearby", "id/tab_nearby"),
        "like_ids": ("likeBtn", "id/likeBtn", "id/tagged_like"),
        "pass_ids": ("dislikeBtn", "id/dislikeBtn", "id/tagged_pass"),
        "chat_btn_ids": ("chatBtn", "id/chatBtn"),
        "like_xy": (860, 1908),
        "pass_xy": (220, 1908),
        "chat_btn_xy": (540, 1911),
        "username_ids": ("tvUsername", "id/tvUsername"),
        "age_ids": ("tvUserAge", "id/tvUserAge"),
        "inbox_labels": ("Messages", "Chats", "Matches", "Inbox"),
        "inbox_tab_labels": ("Chats", "Messages"),
        "new_chat_labels": ("Messages", "Chats", "Matches"),
        "search_labels": ("Search", "Search…"),
        "search_ids": (),
        "search_fallback": None,
        "result_ids": (
            "clConversationContainer",
            "id/clConversationContainer",
            "conversationList",
        ),
        "header_ids": (),
        "compose_labels": ("Message", "Type a message", "Say something", "Aa"),
        "compose_ids": ("id/message_input",),
        "send_labels": ("Send",),
        "send_ids": ("id/send_button",),
        "send_fallback": None,
        "compose_fallback": None,
        "prefer_tap_send": True,
        "never_tap_labels": (
            "Boost",
            "Super Like",
            "Premium",
            "TAGGED PREMIUM",
            "Gold",
            "Subscribe",
            "Buy credits",
            "Go Live",
        ),
        "never_tap_ids": (
            "sns_fab_go_live",
            "id/sns_fab_go_live",
        ),
        "location_continue_ids": ("dcButtonContinue", "id/dcButtonContinue"),
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


def _register_facebook_dating_fallback() -> None:
    """Lambda has no fake-chats catalog — still know Facebook Dating."""
    if "facebook" in DM_APP_PROFILES:
        return
    DM_APP_PROFILES["facebook"] = {
        **DM_APP_PROFILES["tinder"],
        "aliases": ("facebook dating", "facebook", "fb dating"),
        "package": "com.facebook.katana",
        "pkg_markers": ("facebook", "katana", "dating"),
        "open_label": "Facebook Dating",
        "like_ids": ("id/dating_like",),
        "pass_ids": ("id/dating_pass",),
        "compose_ids": ("id/dating_composer",),
        "send_ids": ("id/dating_send",),
        "search_ids": ("id/dating_search", "id/dating_search_edit"),
        "result_ids": ("id/dating_match_row", "id/dating_inbox_row"),
        "header_ids": ("id/dating_thread_title",),
    }


_register_catalog_profiles()
_register_facebook_dating_fallback()


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


def _exact_label_center(
    tree: str,
    label: str,
    *,
    y_min: Optional[int] = None,
    y_max: Optional[int] = None,
) -> Optional[Tuple[int, int]]:
    """Exact text/content-desc match (case-insensitive) — never substring."""
    want = (label or "").strip().lower()
    if not want:
        return None
    for n in _parse_compact_nodes(tree):
        y = int(n.get("y") or 0)
        if y_min is not None and y < y_min:
            continue
        if y_max is not None and y > y_max:
            continue
        for field in ("text", "desc", "label"):
            val = str(n.get(field) or "").strip().lower()
            if val == want:
                return (int(n["x"]), int(n["y"]))
    return None


def _nav_tab_center(
    tree: str,
    *labels: str,
    ids: Sequence[str] = (),
    bottom_y_min: int = 2000,
) -> Optional[Tuple[int, int]]:
    """Bottom-nav tab by resource-id or exact content-desc/text (never guessed xy).

    Prefer nodes in the bottom band so screen titles like Yubo 'Chat' / Hily
    'Chats' at y≈160 are never mistaken for the tab.
    """
    if ids:
        c = _tree_id_center(tree, *tuple(ids))
        if c and int(c[1]) >= bottom_y_min - 200:
            return c
        # Id hit above the nav band is still OK for genuine tab ids
        if c and ids:
            return c
    # 1) Exact label in bottom nav band
    for lab in labels:
        c = _exact_label_center(tree, lab, y_min=bottom_y_min)
        if c:
            return c
        c = _tree_node_center(tree, lab)
        if c and int(c[1]) >= bottom_y_min:
            return c
    # 2) Soften band to y>=1800 for shorter phones
    for lab in labels:
        c = _exact_label_center(tree, lab, y_min=1800)
        if c:
            return c
    # 3) Never fall back to header-height titles for Chat/Chats/Matches/etc.
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


def _resource_id_matches(vid: str, needle: str) -> bool:
    """True when ``vid`` is exactly ``needle`` or ends with ``/needle`` / ``:id/needle``.

    Never use bare substring — ``likeBtn`` must not match ``dislikeBtn``.
    """
    want = (needle or "").lower().strip()
    have = (vid or "").lower().strip()
    if not want or not have:
        return False
    if have == want:
        return True
    # Strip leading id/ or :id/ from needle for suffix checks
    want_tail = want
    for pref in ("id/", ":id/"):
        if want_tail.startswith(pref):
            want_tail = want_tail[len(pref) :]
    if not want_tail:
        return False
    if have.endswith("/" + want_tail) or have.endswith(":id/" + want_tail):
        return True
    # Final path segment equality (com.app:id/likeBtn ↔ likeBtn)
    seg = have.rsplit("/", 1)[-1]
    if ":" in seg:
        seg = seg.rsplit(":", 1)[-1]
    return seg == want_tail


def _tree_id_center(tree: str, *id_needles: str) -> Optional[Tuple[int, int]]:
    """Locate a node by resource-id suffix (e.g. com.whatsapp:id/entry)."""
    for n in _parse_compact_nodes(tree):
        vid = str(n.get("id") or "").lower()
        if not vid:
            continue
        for needle in id_needles:
            if _resource_id_matches(vid, needle):
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
_WINDOW_OR_NODE_RE = re.compile(
    r"(</?w\b[^>]*/?>)|(<(?:n|node)\b([^>]*)/?>)",
    re.I,
)


def _attr(blob: str, *names: str) -> str:
    for name in names:
        m = re.search(rf'\b{re.escape(name)}="([^"]*)"', blob, re.I)
        if m:
            return m.group(1)
    return ""


def _parse_one_node(
    attrs: str, *, package: str = "", window_active: bool = False
) -> Optional[Dict[str, Any]]:
    text = _attr(attrs, "t", "text")
    desc = _attr(attrs, "d", "content-desc", "contentDescription")
    hint = _attr(attrs, "h", "hint")
    xy = _attr(attrs, "xy")
    b = _attr(attrs, "b", "bounds")
    editable = _attr(attrs, "e") in ("1", "true", "True")
    clickable = _attr(attrs, "c") in ("1", "true", "True")
    # v="0" marks isVisibleToUser=false (OEM invisible parents still dump children)
    vis_attr = _attr(attrs, "v", "visible")
    visible = vis_attr not in ("0", "false", "False")
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
        return None
    # Off-screen: negative/huge coords or zero-area bounds
    off_screen = bool(
        cx < 0
        or cy < 0
        or cx > 2000
        or cy > 2800
        or (
            x1 is not None
            and y1 is not None
            and x2 is not None
            and y2 is not None
            and (int(x2) <= int(x1) or int(y2) <= int(y1))
        )
    )
    label = " ".join(p for p in (text, desc, hint) if p).strip()
    view_id = _attr(attrs, "i", "resource-id", "viewIdResourceName")
    cls = _attr(attrs, "cls", "class", "className")
    focused = _attr(attrs, "f") in ("1", "true", "True")
    return {
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
        "visible": visible,
        "off_screen": off_screen,
        "package": package,
        "window_active": window_active,
    }


_SYSTEM_UI_PKGS = (
    "com.android.systemui",
    "com.samsung.android.app.cocktailbarservice",
    "com.android.launcher",
    "com.sec.android.app.launcher",
    "com.google.android.apps.nexuslauncher",
    "com.android.permissioncontroller",
    # Samsung Pay quick-access overlay stole FG trees on S21 (APK 530)
    "com.samsung.android.spay",
    "samsung.android.spay",
)


def _is_system_chrome_package(package: str) -> bool:
    p = (package or "").lower()
    if not p:
        return False
    return (
        any(s in p for s in _SYSTEM_UI_PKGS)
        or p.endswith(".systemui")
        or "spay" in p
        or "samsungpay" in p
    )


def _parse_compact_nodes(
    tree: str,
    *,
    package_filter: Optional[str] = None,
    active_window_only: bool = False,
    include_systemui: bool = False,
    include_invisible: bool = False,
    with_window_order: bool = False,
) -> List[Dict[str, Any]]:
    """Parse compact a11y dump nodes into dicts with center/flags.

    When ``package_filter`` is set (e.g. ``com.bumble.app``), only nodes inside
    matching ``<w p="…">`` windows are returned — Samsung launcher overlays
    like Edge panels must not count as Bumble deck content.

    By default SystemUI / launcher / permissioncontroller windows are excluded
    so status-bar icons never look like chat threads or deck cards.

    By default ``v="0"`` (invisible) and off-screen nodes are excluded from
    detectors and tap targets (covered overlays must not leak through).
    """
    out: List[Dict[str, Any]] = []
    pkg_want = (package_filter or "").lower().strip()
    has_windows = bool(re.search(r"<w\b", tree or "", re.I))
    cur_pkg = ""
    cur_active = False
    window_index = -1
    node_index = 0
    # Prefer window-aware scan so multi-window dumps are scoped correctly
    for m in _WINDOW_OR_NODE_RE.finditer(tree or ""):
        wtag = m.group(1)
        if wtag:
            low = wtag.lower().lstrip()
            if low.startswith("</w"):
                cur_pkg = ""
                cur_active = False
                continue
            # '<w id="active" p="com.bumble.app" f="1">' → attrs only
            attrs = wtag[2:]  # drop '<w'
            if attrs.endswith("/>"):
                attrs = attrs[:-2]
            elif attrs.endswith(">"):
                attrs = attrs[:-1]
            cur_pkg = _attr(attrs, "p", "package")
            wid = _attr(attrs, "id").lower()
            cur_active = wid == "active" or _attr(attrs, "f") in ("1", "true", "True")
            window_index += 1
            node_index = 0
            continue
        node_attrs = m.group(3) or ""
        if not include_systemui and _is_system_chrome_package(cur_pkg):
            continue
        if pkg_want:
            if has_windows and pkg_want not in (cur_pkg or "").lower():
                continue
        if active_window_only and has_windows and not cur_active:
            continue
        node = _parse_one_node(
            node_attrs,
            package=cur_pkg,
            window_active=cur_active or not has_windows,
        )
        if node:
            if not include_invisible and (
                not node.get("visible", True) or node.get("off_screen")
            ):
                continue
            if with_window_order:
                node["window_index"] = window_index
                node["node_index"] = node_index
                node_index += 1
            out.append(node)
    if out:
        return out
    # Fallback: legacy flat parse (no <w> tags)
    for m in _NODE_TAG_RE.finditer(tree or ""):
        node = _parse_one_node(m.group(1))
        if not node:
            continue
        if not include_invisible and (
            not node.get("visible", True) or node.get("off_screen")
        ):
            continue
        out.append(node)
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


def _name_exact_or_whole_word(contact: str, label: str) -> bool:
    """True when label equals contact or contains it as a whole word (not substring)."""
    c = re.sub(r"\s+", " ", (contact or "").strip().lower())
    lab = re.sub(r"\s+", " ", (label or "").strip().lower())
    if not c or not lab:
        return False
    if c == lab:
        return True
    # "Name, 24" / "Name · online" — name is the first segment
    first = re.split(r"[,·|•\-–]", lab, maxsplit=1)[0].strip()
    if first == c:
        return True
    return bool(re.search(rf"(?<!\w){re.escape(c)}(?!\w)", lab))


def _looks_like_message_preview(label: str) -> bool:
    """True for last-message preview text — never a contact name / row key.

    Examples: 'Good and you' (Badoo), 'Hola' (Tagged), 'hey what's up'.
    Names with emoji/heart suffix ('Amie ♡') are NOT previews.
    """
    name = (label or "").strip()
    if not name:
        return True
    # Strip trailing emoji / hearts so "Amie ♡" counts as a person name
    name_core = re.sub(r"[\W_]+$", "", name, flags=re.UNICODE).strip() or name
    low = name_core.lower()
    # Short all-lowercase greetings / snippets
    greetings = (
        "hola",
        "hey",
        "hi",
        "hello",
        "sup",
        "yo",
        "ok",
        "okay",
        "yes",
        "no",
        "thanks",
        "thank you",
        "good and you",
        "how are you",
        "what's up",
        "whats up",
        "wyd",
        "hii",
        "heyy",
        "good morning",
        "good night",
        "lol",
        "haha",
        "hahaha",
        "good u",
    )
    if low in greetings or name.strip().lower() in greetings:
        return True
    # "You: …" outgoing preview prefix
    if name.strip().lower().startswith("you:"):
        return True
    # Multi-word sentence that is not Title Case person name ("Ada Love")
    # Ignore non-alpha tokens (♡, emoji) when judging Title Case
    words = [w for w in name_core.split() if any(ch.isalpha() for ch in w)]
    if len(words) >= 2:
        # All lowercase / sentence case → preview
        joined = " ".join(words)
        if joined == joined.lower() or (
            words[0][:1].isupper() and all(w == w.lower() for w in words[1:])
        ):
            # Allow "First Last" Title Case names
            if not all(
                w[:1].isupper() and (len(w) == 1 or w[1:].islower()) for w in words
            ):
                return True
        # Ends with punctuation / question → preview
        if name_core[-1] in ".!?…" or "?" in name_core:
            return True
    # Preview-ish verbs / pronouns
    low_full = name.lower()
    if any(
        tok in low_full
        for tok in (
            " and you",
            "how are",
            "what's",
            "whats ",
            "miss you",
            "see you",
            "message before match",
        )
    ):
        return True
    return False


def _looks_like_chat_list_row(
    node: Dict[str, Any], result_ids: Sequence[str] = ()
) -> bool:
    """Restrict contact taps to inbox/match row *name* nodes — never previews."""
    # Never treat status-bar / toolbar headers as chat rows
    y = int(node.get("y") or 0)
    if y < 200:
        return False
    nid = str(node.get("id") or "").lower()
    label = (node.get("label") or node.get("text") or "").strip()
    low = label.lower()
    # Common non-row chrome
    if low in (
        "chat",
        "chats",
        "messages",
        "matches",
        "connections",
        "back",
        "search",
        "new friends",
        "reactions",
        "conversations",
    ):
        return False
    # Message preview text must never be the row key
    if _looks_like_message_preview(label):
        return False
    # Preview / last-message resource ids — never rows
    preview_id_toks = (
        "messagefield",
        "message_field",
        "last_message",
        "row_message",
        "conversations_row_message",
        "preview",
        "msg_text",
        "message_text",
        "chat_message",
        "subtitle",
        "secondary_text",
    )
    if any(t in nid for t in preview_id_toks):
        return False
    # Name-specific ids preferred over list containers
    name_id_toks = (
        "usernamefield",
        "profileinfo_name",
        "personname",
        "person_name",
        "match_name",
        "like_name",
        "contact_name",
        "conversations_row_contact_name",  # WhatsApp home chat list
        "conversation_contact_name",
        "tvusername",
        "dialogmessageitem",  # Hily name row
        "center_name",
        "connectionsitem_personname",
    )
    if any(t in nid for t in name_id_toks):
        return True
    if result_ids and _node_id_matches(node, result_ids):
        # Container ids (connection_container / clConversationContainer) may
        # carry concatenated name+preview — require non-preview label.
        containerish = any(
            t in nid
            for t in (
                "container",
                "conversationlist",
                "connection_container",
            )
        )
        if containerish and (" " in label and _looks_like_message_preview(label)):
            return False
        # Prefer name-looking labels on containers
        if containerish and _looks_like_message_preview(label):
            return False
        return True
    row_id_toks = (
        "match_row",
        "connection_row",
        "like_row",
        "dating_match_row",
        "dating_inbox_row",
        "contact_row",
        "conversations_row",
        "row_inbox",
        "thread_list_item",
    )
    if any(t in nid for t in row_id_toks):
        return True
    # Fake-chats / bench rows: "Chat with X" / "Match X" / "Match01"
    if low.startswith("chat with ") or low.startswith("match "):
        return True
    if re.match(r"^match\d{1,3}$", low.replace(" ", "")):
        return True
    return False


def _is_bulk_quantity_contact(contact: str) -> bool:
    """True for '5 matches' / '3 people' — not a real contact name."""
    c = (contact or "").strip().lower()
    if not c:
        return False
    return bool(
        re.match(
            r"^\d+\s*(?:existing\s+)?(?:matches?|people|contacts?|chats?)$",
            c,
        )
    )


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
        if _resource_id_matches(nid, n):
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
    """Best match for a contact *chat-list row* — never deck cards / counters.

    Requires exact or whole-word name match on a row-like node (result_ids /
    known inbox row ids). Substring hits like '5' inside '15 matches' are refused.
    """
    nodes = _parse_compact_nodes(tree)
    if not nodes or _is_bulk_quantity_contact(contact):
        return None
    chats_y = _chats_section_y(nodes)
    candidates: List[Tuple[float, int, Dict[str, Any]]] = []
    for node in nodes:
        if _is_searchish_node(node, search_labels):
            continue
        if exclude_ids and _node_id_matches(node, exclude_ids):
            continue
        if not _looks_like_chat_list_row(node, result_ids):
            continue
        label = node.get("label") or node.get("text") or ""
        low = label.lower()
        # "From Precious Achalugo" chip / message snippet rows
        if low.startswith("from "):
            continue
        if "search_message" in str(node.get("id") or "").lower():
            continue
        # WhatsApp Community / Announcements / Channels are not DMs
        if any(
            tok in low
            for tok in (
                "community",
                "communities",
                "announcement",
                "announcements",
                "channel",
                "channels",
                "broadcast",
            )
        ):
            continue
        nid_l = str(node.get("id") or "").lower()
        if any(
            tok in nid_l
            for tok in ("community", "announcement", "newsletter", "channel")
        ):
            continue
        # Counters / deck chrome — never treat as a contact row
        if re.search(r"\b\d+\s*(matches?|people|likes?)\b", low):
            continue
        if not _name_exact_or_whole_word(contact, label):
            continue
        score = 1.0 if label.strip().lower() == contact.strip().lower() else 0.92
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


def _log_detector_false(name: str, tree: str, package: str = "") -> None:
    """Best-effort S3/log capture when a screen detector returns false."""
    try:
        from cloud_agent import save_detector_miss_tree
    except ImportError:
        try:
            from backend.cloud_agent import save_detector_miss_tree  # type: ignore
        except ImportError:
            return
    try:
        save_detector_miss_tree(name, tree or "", package=package)
    except Exception:
        pass


def _bumble_nodes(tree: str) -> List[Dict[str, Any]]:
    """Nodes in the active com.bumble.app window only (ignore launcher overlays)."""
    return _parse_compact_nodes(
        tree, package_filter="com.bumble.app", active_window_only=True
    )


def bumble_on_photo_grid(tree: str) -> bool:
    """True when People tab shows the photo-grid RecyclerView (not a swipe card)."""
    for n in _bumble_nodes(tree):
        nid = str(n.get("id") or "").lower()
        if "encountersgridprofile_list" in nid or "encountersgridprofilelist" in nid:
            return True
        if "encountersgrid" in nid and "list" in nid and "item" not in nid:
            return True
    return bool(
        _tree_id_center(
            tree,
            "encountersGridProfile_list",
            "com.bumble.app:id/encountersGridProfile_list",
        )
    )


def bumble_on_photo_browser(tree: str) -> bool:
    """True in full-screen photo browser whose only CTA is Send SuperSwipe (paid).

    Do NOT match the deck's profile_details_badgeSuperSwipe badge — that is a
    normal People card with a paid badge, not the photo browser.
    """
    for n in _bumble_nodes(tree):
        nid = str(n.get("id") or "").lower()
        nid_f = nid.replace("_", "")
        # Real S21+ People cards label the star "Send SuperSwipe" with this id.
        # That is the on-card badge, not the full-screen photo browser.
        if "badgesuperswipe" in nid_f or "profiledetailsbadgesuper" in nid_f:
            continue
        if "photobrowser" in nid_f:
            return True
        lab = (n.get("label") or n.get("text") or n.get("desc") or "").strip().lower()
        if lab == "send superswipe" or "send superswipe" in lab:
            return True
    return False


def bumble_back_from_photo_browser(
    planner: str = "bumble_heuristic",
) -> Dict[str, Any]:
    """Leave photo browser — never tap SuperSwipe."""
    return _fp(
        {
            "action": "press_button",
            "button": "back",
            "reason": (
                f"Back out of Bumble photo browser "
                f"(Send SuperSwipe is paid) ({planner})"
            ),
            "planner": planner,
            "llm_provider": None,
        },
        "bumble_photo_browser_back",
    )


def bumble_first_grid_tile_center(tree: str) -> Optional[Tuple[int, int]]:
    """Center of the first tappable tile in the People photo grid."""
    tiles: List[Dict[str, Any]] = []
    for n in _bumble_nodes(tree):
        nid = str(n.get("id") or "").lower()
        if not n.get("clickable") and "grid" not in nid and "photo" not in nid:
            continue
        y = int(n.get("y") or 0)
        if y < 250 or y > 2000:
            continue
        # Prefer grid cell / photo tiles over nav
        if any(
            t in nid
            for t in (
                "encountersgrid",
                "griditem",
                "profile_photo",
                "photo",
                "encounter",
            )
        ) or (
            n.get("clickable")
            and 300 < y < 1800
            and "nav" not in nid
            and "tab" not in nid
        ):
            lab = (n.get("label") or "").lower()
            if lab in ("people", "chats", "discover", "profile", "liked you"):
                continue
            tiles.append(n)
    if not tiles:
        return None
    tiles.sort(key=lambda n: (int(n.get("y") or 0), int(n.get("x") or 0)))
    t0 = tiles[0]
    return (int(t0["x"]), int(t0["y"]))


def bumble_on_people_deck(tree: str, *, _log: bool = True) -> bool:
    """True when Bumble People tab *card stack* is visible (not photo grid).

    Only inspects the active ``com.bumble.app`` window — Samsung launcher
    'Edge panels' handles must never count as a deck card.
    """
    if bumble_on_photo_grid(tree):
        # Photo grid ≠ swipe deck
        if _log:
            _log_detector_false("bumble_on_people_deck_grid", tree, "com.bumble.app")
        return False
    nodes = _bumble_nodes(tree)
    # Strong: profile / encounters container ids (in Bumble window)
    for n in nodes:
        nid = str(n.get("id") or "").lower()
        if any(
            t in nid
            for t in (
                "profile_root_container",
                "encountersgriditem_summarycontainer",
                "encountersgriditem_summary",
            )
        ):
            return True
    if _tree_id_center(
        tree,
        "profile_root_container",
        "encountersGridItem_summaryContainer",
        "com.bumble.app:id/profile_root_container",
        "com.bumble.app:id/encountersGridItem_summaryContainer",
    ):
        # Confirm the id lives in the bumble window when windows exist
        if not re.search(r"<w\b", tree or "", re.I) or nodes:
            # If multi-window, require the id among bumble nodes
            if re.search(r"<w\b", tree or "", re.I):
                if any(
                    "profile_root" in str(n.get("id") or "").lower()
                    or "encountersgriditem_summary" in str(n.get("id") or "").lower()
                    for n in nodes
                ):
                    return True
            else:
                return True
    # Strong: main photo content-desc + Name, Age near bottom of card (bumble only)
    photo = False
    name_age = False
    for n in nodes:
        lab = n.get("label") or ""
        low = lab.lower()
        if "main photo" in low and ("'s" in low or "\u2019s" in lab):
            photo = True
        if re.search(r",\s*\d{2}\s*$", lab.strip()) and int(n.get("y") or 0) > 1500:
            name_age = True
    if photo or name_age:
        return True
    # Do NOT use a weak "any labelled mid-screen node" fallback — that matched
    # launcher Edge panels and empty People shells.
    if _log:
        _log_detector_false("bumble_on_people_deck", tree, "com.bumble.app")
    return False


def bumble_on_connections(tree: str, *, _log: bool = True) -> bool:
    """True on Bumble Chats/Connections list (multi-signal S21 map).

    Strong list roots / row ids win. Weak name+Chats signals must NOT fire on
    the Discover/People deck (card name + bottom-nav Chats → false positive →
    'No chat-list rows after 3 scrolls' while still on the deck).
    """
    # List roots
    if _tree_id_center(
        tree,
        "connections_root",
        "connections_connectionsList",
        "com.bumble.app:id/connections_root",
        "com.bumble.app:id/connections_connectionsList",
    ):
        return True
    # Row ids (person name / connection item)
    if _tree_id_center(
        tree,
        "connectionItem",
        "connectionsItem_personName",
        "com.bumble.app:id/connectionItem",
        "com.bumble.app:id/connectionsItem_personName",
        "connection_row",
        "connection_name",
    ):
        return True
    # Require real chat rows (name + preview) in the Bumble window — never the
    # bottom-nav tab label alone.
    has_your_matches = bool(
        re.search(r'\bt="Your matches"', tree or "", re.I)
        or _exact_label_center(tree, "Your matches")
    )
    has_older = bool(re.search(r"older chats", tree or "", re.I))
    # Mid-screen Chats/Connections header (not bottom-nav y≳2100)
    has_mid_chats_header = False
    for n in _bumble_nodes(tree) or _parse_compact_nodes(
        tree, package_filter="com.bumble.app"
    ):
        t = (n.get("text") or "").strip().lower()
        y = int(n.get("y") or 0)
        if t in ("chats", "connections") and 120 < y < 500:
            has_mid_chats_header = True
            break
    row_hit = False
    for n in _bumble_nodes(tree) or _parse_compact_nodes(
        tree, package_filter="com.bumble.app"
    ):
        text = (n.get("text") or "").strip()
        y = int(n.get("y") or 0)
        if not text or y < 400 or y > 2000:
            continue
        low = text.lower()
        if low in ("chats", "people", "discover", "liked you", "profile", "for you"):
            continue
        if _is_badge_or_numeric_label(text):
            continue
        # Name-ish left column or preview mid row
        if len(text) <= 40 and not low.startswith("older"):
            row_hit = True
            break
    if (has_your_matches or has_older) and row_hit:
        return True
    # Mid header + rows — never bottom-nav "Chats" alone (deck false positive)
    if row_hit and has_mid_chats_header:
        return True
    # On People/Discover deck without list chrome → not connections
    if bumble_on_people_deck(tree, _log=False) and not (
        has_your_matches or has_older or has_mid_chats_header
    ):
        if _log:
            _log_detector_false("bumble_on_connections_deck", tree, "com.bumble.app")
        return False
    if _log:
        _log_detector_false("bumble_on_connections", tree, "com.bumble.app")
    return False


def bumble_collapsed_older_chats_center(tree: str) -> Optional[Tuple[int, int]]:
    """Tap target for collapsed 'Older chats · (N)' row — expand before picking."""
    for n in _bumble_nodes(tree) or _parse_compact_nodes(tree):
        lab = (n.get("label") or n.get("text") or "").strip()
        low = lab.lower()
        if "older chats" not in low:
            continue
        # Collapsed form includes a count: Older chats · (12) / Older chats (12)
        if not (
            re.search(r"older chats\s*[·•.\-]?\s*\(\s*\d+\s*\)", low)
            or re.search(r"older chats\s*[·•]", low)
            or (n.get("clickable") and "(" in lab)
        ):
            # Still allow a lone clickable Older chats header with no visible rows
            if not n.get("clickable"):
                continue
        y = int(n.get("y") or 0)
        if y < 400 or y > 2200:
            continue
        return (int(n["x"]), int(n["y"]))
    return None


def _bumble_card_name_ok(name: str) -> bool:
    """Reject owner chrome (MacAnderson) and tab/filter labels."""
    raw = (name or "").strip()
    if not raw or re.match(r"^profile[_\s]?\d+$", raw, re.I):
        return False
    low = raw.lower().split(",")[0].strip()
    if low in {
        "profile",
        "discover",
        "people",
        "liked you",
        "chats",
        "filters",
        "filter",
        "bumble",
        "macanderson",
        "mac anderson",
        "superswipe",
        "spotlight",
    }:
        return False
    try:
        from bulk_bench_heuristics import _card_name_is_owner, _card_name_is_real_profile
    except ImportError:
        from backend.bulk_bench_heuristics import (  # type: ignore
            _card_name_is_owner,
            _card_name_is_real_profile,
        )
    if _card_name_is_owner(raw):
        return False
    return bool(_card_name_is_real_profile(raw))


def bumble_deck_card_name(tree: str) -> Optional[str]:
    """Real profile name from the Bumble card (never invent profile_N)."""
    for n in _bumble_nodes(tree) or _parse_compact_nodes(tree):
        text = (n.get("text") or "").strip()
        if not text:
            continue
        if re.search(r",\s*\d{2}\s*$", text) and int(n.get("y") or 0) > 1400:
            name = text.split(",")[0].strip()
            if _bumble_card_name_ok(name):
                return name
    for n in _bumble_nodes(tree) or _parse_compact_nodes(tree):
        desc = (n.get("desc") or "").strip()
        m = re.match(r"(.+?)['\u2019]s main photo", desc, re.I)
        if m:
            name = m.group(1).strip()
            if _bumble_card_name_ok(name):
                return name
    return None


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


def _is_badge_or_numeric_label(text: str) -> bool:
    """True for counters like '50+', '42', '99+' — never a profile name."""
    t = (text or "").strip()
    if not t:
        return True
    return bool(re.match(r"^\d+\+?$", t))


# Chrome / top-filter tabs mistaken for a person name on Yubo (r21: "Social")
_YUBO_CHROME_LABELS = frozenset(
    {
        "chat",
        "chats",
        "likes",
        "friends",
        "more",
        "aa",
        "direct",
        "blast",
        "send a message",
        "conversations",
        "new friends",
        "reactions",
        "social",  # top filter tab — not a card name
        "people",
        "discover",
        "explore",
        "feed",
        "live",
        "nearby",
        "popular",
        "for you",
        "following",
        "yubo",
    }
)


def _is_yubo_chrome_label(text: str) -> bool:
    low = (text or "").strip().lower()
    return bool(low) and low in _YUBO_CHROME_LABELS


def yubo_deck_card_name(tree: str) -> Optional[str]:
    """Profile name on the Yubo deck (S21 map: left x≈42 name node).

    Skips numeric/badge labels (``50+``, ``42`` Yubucks) and chrome tabs
    (``Social``, ``Likes``, …) that are not person names.
    """
    for n in _parse_compact_nodes(tree):
        text = (n.get("text") or "").strip()
        if not text or len(text) > 40:
            continue
        if _is_badge_or_numeric_label(text) or _is_yubo_chrome_label(text):
            continue
        x1 = n.get("x1")
        if x1 is None:
            continue
        if abs(int(x1) - 42) > 8:  # allow slight dump jitter vs map's 42
            continue
        y = int(n.get("y") or 0)
        if y < 200 or y > 2100:
            continue
        return text
    # Fallback: first non-badge mid-card title (not bottom nav / section header)
    for n in _parse_compact_nodes(tree):
        text = (n.get("text") or "").strip()
        if (
            not text
            or _is_badge_or_numeric_label(text)
            or _is_yubo_chrome_label(text)
            or len(text) > 40
        ):
            continue
        y = int(n.get("y") or 0)
        if y < 250 or y > 900:
            continue
        if int(n.get("x") or 0) > 700:  # skip right-side pills
            continue
        return text
    return None


def yubo_on_deck(tree: str, *, _log: bool = True) -> bool:
    """True on the People/deck card — never Chat-list chrome (Reactions, etc.)."""
    blob = (tree or "").lower()
    # Chat / Conversations list is never the swipe deck
    if yubo_on_chat(tree):
        return False
    if "conversations" in blob or (
        "new friends" in blob and "reactions" in blob and "send a message" not in blob
    ):
        return False
    name = yubo_deck_card_name(tree)
    if name:
        low = name.lower()
        # Reject chat-list / filter chrome mistaken for a card
        if any(
            tok in low
            for tok in (
                "verified",
                "reaction",
                "conversation",
                "friend",
                "chat",
                "like",
                "more",
                "social",
                "people",
                "discover",
            )
        ):
            if _log:
                _log_detector_false("yubo_on_deck", tree, "co.yellw.yellowapp")
            return False
        # Prefer a real card: name plus Send a message CTA (not inbox)
        if "send a message" in blob:
            return True
        # Name alone at left edge is enough when not on chat list
        return True
    if _log:
        _log_detector_false("yubo_on_deck", tree, "co.yellw.yellowapp")
    return False


def yubo_on_chat_list(tree: str, *, _log: bool = True) -> bool:
    """True on Yubo Chat/Conversations list (multi-signal; not the deck).

    The Chat tab is visible on the deck too — require Conversations/New friends
    section text and/or conversation rows below the header.
    """
    if yubo_on_chat(tree):
        return False
    if yubo_on_deck(tree, _log=False) and "conversations" not in (tree or "").lower():
        # Deck card + Send a message without Conversations section → not inbox
        if _log:
            pass  # don't log false when clearly on deck
        return False
    blob = (tree or "").lower()
    has_section = "conversations" in blob or "new friends" in blob
    # Conversation rows: leftish name texts under Conversations header (y≳1100)
    row_hit = False
    for n in _parse_compact_nodes(tree):
        text = (n.get("text") or "").strip()
        if not text or _is_badge_or_numeric_label(text) or len(text) > 40:
            continue
        y = int(n.get("y") or 0)
        if y < 1100 or y > 2000:
            continue
        low = text.lower()
        if low in (
            "chat",
            "likes",
            "friends",
            "more",
            "conversations",
            "new friends",
            "reactions",
            "launch a hypersurge",
            "aa",
            "direct",
            "blast",
            "send a message",
        ):
            continue
        if int(n.get("x") or 0) < 500:
            row_hit = True
            break
    if has_section and row_hit:
        return True
    # After scroll the section header may leave the viewport — rows alone suffice
    if row_hit and not yubo_on_deck(tree, _log=False):
        return True
    if has_section and "aa" not in blob and "send a message" not in blob:
        return True
    if _log:
        _log_detector_false("yubo_on_chat_list", tree, "co.yellw.yellowapp")
    return False


def yubo_on_chat(tree: str) -> bool:
    """True in an open Yubo thread — never match SystemUI 'Messages notification'.

    Require an *editable* Aa/compose field. A non-editable 'Aa' label on the
    Conversations list (plus a Back chrome) falsely triggered open_chat_thread
    → Back loop while Roch/Leah rows stayed visible (r22 yubo_reply5).
    """
    # Chat list chrome beats thread detection
    blob = (tree or "").lower()
    if "conversations" in blob and (
        "new friends" in blob or "reactions" in blob
    ):
        # Only treat as thread when an editable composer is clearly present
        pass
    nodes = _parse_compact_nodes(tree, package_filter="co.yellw.yellowapp")
    if not nodes:
        nodes = [
            n
            for n in _parse_compact_nodes(tree)
            if not _is_system_chrome_package(str(n.get("package") or ""))
        ]
    has_editable_compose = False
    has_back = False
    for n in nodes:
        lab = (n.get("label") or n.get("text") or n.get("desc") or "").strip().lower()
        nid = str(n.get("id") or "").lower()
        if n.get("editable") and (
            lab in ("aa", "message", "type a message", "hey", "")
            or "message" in nid
            or "compose" in nid
            or "input" in nid
        ):
            has_editable_compose = True
        if lab == "back" or nid.endswith("/back") or "navigate up" in lab:
            if "systemui" not in str(n.get("package") or "").lower():
                has_back = True
    if has_editable_compose and has_back:
        return True
    # Compose-only fallback: editable field + Back
    compose = find_compose_center(tree, ("Aa", "Message"), ())
    if not compose:
        return False
    # find_compose_center may hit non-editable — require an editable node nearby
    if not any(n.get("editable") for n in nodes):
        return False
    return any((n.get("label") or "").strip().lower() == "back" for n in nodes)


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
    # r45: Blast mode shows "Message tons of new people at once" and the
    # 50+/100+/200+ reach chips. The old size check read the wide Direct
    # *tile* (View 737..973) as "selected" and let the send go on Blast.
    blast_mode = "message tons of new people" in blob or (
        "50+" in blob and "100+" in blob
    )
    # Prefer the Direct TextView (the tile View has the same label)
    for n in nodes:
        if (n.get("label") or "").strip().lower() == "direct" and "text" in str(
            n.get("cls") or n.get("class") or ""
        ).lower():
            direct_n = n
            break
    # Selected Direct has bounds ≈[729,515][875,572]; unselected ≈[754,525][871,570]
    direct_selected = False
    if blast_mode:
        direct_selected = False
    elif direct_n is not None and direct_n.get("x1") is not None:
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


def badoo_on_encounters(tree: str, *, _log: bool = True) -> bool:
    """True on Badoo Encounters deck — VoteYes/VoteNo ids from S21 map."""
    if _tree_id_center(
        tree,
        "encounters_stackView",
        "encounters_profile_voting_buttonVoteYes",
        "encounters_profile_voting_buttonVoteNo",
        "com.badoo.mobile:id/encounters_stackView",
        "com.badoo.mobile:id/encounters_profile_voting_buttonVoteYes",
        "com.badoo.mobile:id/encounters_profile_voting_buttonVoteNo",
    ):
        return True
    # Exact Like/Pass voting labels near bottom action row
    like = _exact_label_center(tree, "Like")
    pass_ = _exact_label_center(tree, "Pass")
    if like and pass_ and int(like[1]) > 1700 and int(pass_[1]) > 1700:
        return True
    if _log:
        _log_detector_false("badoo_on_encounters", tree, "com.badoo.mobile")
    return False


def badoo_on_connections(tree: str, *, _log: bool = True) -> bool:
    """True on Badoo Chats/Connections list (multi-signal S21 map)."""
    if _tree_id_center(
        tree,
        "connections_root",
        "connection_list_component",
        "com.badoo.mobile:id/connections_root",
        "com.badoo.mobile:id/connection_list_component",
    ):
        return True
    if _tree_id_center(
        tree,
        "connection_container",
        "profileInfo_name",
        "com.badoo.mobile:id/connection_container",
        "com.badoo.mobile:id/profileInfo_name",
    ) and not _tree_id_center(
        tree,
        "encounters_stackView",
        "encounters_profile_voting_buttonVoteYes",
    ):
        return True
    chats_tab = bool(
        _tree_id_center(
            tree,
            "nav_bar_button_connections",
            "com.badoo.mobile:id/nav_bar_button_connections",
        )
        or _exact_label_center(tree, "Chats")
    )
    if chats_tab and not badoo_on_encounters(tree, _log=False):
        # Require a real chat row: name + preview (or connection_container),
        # not just any mid-screen text near the Chats tab.
        has_row_id = bool(
            _tree_id_center(
                tree,
                "connection_container",
                "profileInfo_name",
                "com.badoo.mobile:id/connection_container",
                "com.badoo.mobile:id/profileInfo_name",
            )
        )
        name_hit = False
        preview_hit = False
        for n in _parse_compact_nodes(tree, package_filter="com.badoo.mobile"):
            text = (n.get("text") or "").strip()
            y = int(n.get("y") or 0)
            if not text or y < 600 or y > 2000:
                continue
            low = text.lower()
            if low in ("likes", "chats", "encounters", "buy credits", "people"):
                continue
            if _is_badge_or_numeric_label(text):
                continue
            if len(text) <= 32 and int(n.get("x") or 0) < 700:
                name_hit = True
            elif len(text) > 8:
                preview_hit = True
        if has_row_id or (name_hit and preview_hit):
            return True
    if _log:
        _log_detector_false("badoo_on_connections", tree, "com.badoo.mobile")
    return False


def badoo_dismiss_popup(
    tree: str, planner: str = "badoo_heuristic"
) -> Optional[Dict[str, Any]]:
    nodes = _parse_compact_nodes(tree)
    blob = " ".join(
        f"{n.get('id')} {n.get('label')} {n.get('text')}" for n in nodes
    ).lower()
    # Treasure promo sheet ONLY — never Back when Connections list is open
    # (r22: list row "Treasure" made dismiss fire and broke reply5 that
    # passed 5/5 on 563 via connections_root → Open <person>).
    on_connections = bool(
        "connections_root" in blob
        or "connection_list_component" in blob
        or "connection_container" in blob
    )
    treasure_sheet = any(
        tok in blob
        for tok in (
            "open treasure",
            "claim treasure",
            "your treasure",
            "treasure chest",
        )
    ) or (
        "treasure" in blob
        and any(tok in blob for tok in ("close", "not now", "maybe later", "claim"))
        and not on_connections
    )
    if treasure_sheet and not on_connections:
        for lab in ("Close", "Not now", "Maybe later", "No thanks", "Skip"):
            close = _tree_node_center(tree, lab)
            if close:
                return _fp(
                    {
                        "action": "tap",
                        "x": close[0],
                        "y": close[1],
                        "reason": f"Dismiss Badoo Treasure sheet → {lab} ({planner})",
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "badoo_popup_treasure",
                )
        return _fp(
            {
                "action": "press_button",
                "button": "back",
                "reason": f"Dismiss Badoo Treasure sheet ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "badoo_popup_treasure",
        )
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


def hily_on_top_picks_grid(tree: str) -> bool:
    """Discover as photo grid (Top picks / Shared interests) — not a swipe deck."""
    blob = " ".join(
        f"{n.get('text') or ''} {n.get('label') or ''} {n.get('desc') or ''}"
        for n in _parse_compact_nodes(tree)
    ).lower()
    if "top picks" in blob or "shared interests" in blob:
        return True
    # Crush icon tiles without ActionButton_LIKE → grid
    has_crush = any(
        (n.get("text") or n.get("desc") or n.get("label") or "").strip().lower()
        == "crush"
        or "crush" in str(n.get("id") or "").lower()
        for n in _parse_compact_nodes(tree)
    )
    if has_crush and not _tree_id_center(
        tree, "ActionButton_LIKE", "id/ActionButton_LIKE"
    ):
        return True
    return False


def hily_first_grid_tile_center(tree: str) -> Optional[Tuple[int, int]]:
    """Open first Discover grid tile (avoid Crush paid icon)."""
    candidates: List[Tuple[int, int, int]] = []
    for n in _parse_compact_nodes(tree):
        if not n.get("clickable"):
            continue
        lab = (n.get("text") or n.get("desc") or n.get("label") or "").strip().lower()
        nid = str(n.get("id") or "").lower()
        if "crush" in lab or "crush" in nid:
            continue
        if lab in ("like", "pass", "skip", "chats", "discover", "filter"):
            continue
        y = int(n.get("y") or 0)
        x = int(n.get("x") or 0)
        if y < 280 or y > 1900:
            continue
        w = int(n.get("x2") or x) - int(n.get("x1") or x)
        h = int(n.get("y2") or y) - int(n.get("y1") or y)
        if w < 120 or h < 120:
            continue
        candidates.append((y, x, int(n["y"])))
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t[0], t[1]))
    y, x, _ = candidates[0]
    return (x, y)


def hily_on_finder(tree: str, *, _log: bool = True) -> bool:
    """True on Hily Finder deck — ActionButton_LIKE / SKIP from S21 map."""
    if hily_on_top_picks_grid(tree):
        # Grid is Discover, not the classic button deck
        return False
    if _tree_id_center(
        tree,
        "ActionButton_LIKE",
        "ActionButton_SKIP",
        "id/ActionButton_LIKE",
        "id/ActionButton_SKIP",
    ):
        return True
    if (
        _tree_id_center(
            tree,
            "userNameAgeField",
            "finderCardUser",
            "id/userNameAgeField",
        )
        and not hily_on_thread(tree)
        and not hily_on_chats_list(tree)
    ):
        return True
    # Exact Pass/Like labels on the action row
    like = _exact_label_center(tree, "Like")
    pass_ = _exact_label_center(tree, "Pass")
    if like and pass_ and int(like[1]) > 1700:
        return True
    if _log:
        _log_detector_false("hily_on_finder", tree, "com.hily.app")
    return False


def hily_close_mbm(
    tree: str, planner: str = "hily_heuristic"
) -> Optional[Dict[str, Any]]:
    """Close Message Before Match sheet via closeButton — never Major Crush / credits.

    Never blind-tap map xy (74,160) — that lands on the non-clickable Chats title
    when no sheet is present / close control is missing. Prefer Back instead.
    """
    if not hily_on_mbm(tree):
        return None
    close = _tree_id_center(
        tree, "closeButton", "id/closeButton", "com.hily.app:id/closeButton"
    ) or _tree_node_center(tree, "Close", "Not now", "No thanks")
    if close:
        return _fp(
            {
                "action": "tap",
                "x": close[0],
                "y": close[1],
                "reason": f"Close Hily MBM sheet ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "hily_mbm_close",
        )
    return _fp(
        {
            "action": "press_button",
            "button": "back",
            "reason": f"Back out of Hily MBM (no close control) ({planner})",
            "planner": planner,
            "llm_provider": None,
        },
        "hily_mbm_back",
    )


def hily_on_thread(tree: str) -> bool:
    """True on an open Hily conversation (toolbar + compose), not the chats list."""
    return bool(
        _tree_id_center(
            tree,
            "threadInputFieldText",
            "threadToolBarName",
            "threadSend",
        )
    )


def thread_header_verified(
    app: Optional[str],
    tree: str,
    contact: str,
) -> bool:
    """True when the open thread toolbar/header matches ``contact``.

    Rejects filter chips / section labels (Age, Notes, …) so Discover chrome
    never counts as an open chat (r26: BLK falsely verified composer for Age).
    """
    contact_l = (contact or "").strip().lower()
    if not contact_l or contact_l.startswith("__existing_"):
        return False
    if looks_like_section_label(contact):
        return False
    contact_core = re.sub(r"[\W_]+$", "", contact, flags=re.UNICODE).strip() or contact
    person_ok = (
        looks_like_profile_name(contact)
        or looks_like_profile_name(contact_core)
        or bool(re.match(r"^(?:Profile|Match)\d+$", contact, re.I))
        or bool(re.search(r"\d{3,}", contact))  # WA numbers
    )
    if not person_ok:
        return False
    app_l = (app or "").lower()
    profile = DM_APP_PROFILES.get(app_l, {}) if app_l else {}
    header_ids = tuple(profile.get("header_ids") or ())
    for n in _parse_compact_nodes(tree):
        nid = str(n.get("id") or "").lower()
        label = (n.get("text") or n.get("label") or "").strip()
        if not label:
            continue
        if looks_like_section_label(label):
            continue
        id_ok = False
        if header_ids:
            id_ok = any(
                h.lower().split("/")[-1] in nid or h.lower() in nid for h in header_ids
            )
        # Toolbar / top-of-screen name
        y_ok = int(n.get("y") or 0) < 400
        if (id_ok or y_ok) and _name_exact_or_whole_word(contact_l, label):
            return True
    return False


def compose_center_in_thread(
    app: Optional[str],
    tree: str,
    contact: str,
    *,
    screen_h: int = 2400,
) -> Optional[Tuple[int, int]]:
    """Locate composer ONLY after the thread header matches ``contact``.

    Prefers compose resource-ids in the bottom 30% of the screen so list-row
    'Message' previews (e.g. Hily mid-list) are never tapped.
    """
    if not thread_header_verified(app, tree, contact):
        return None
    app_l = (app or "").lower()
    profile = DM_APP_PROFILES.get(app_l, {}) if app_l else {}
    compose_ids = tuple(profile.get("compose_ids") or ())
    compose_labels = tuple(profile.get("compose_labels") or ())
    y_min = int(screen_h * 0.70)
    # 1) compose ids in bottom 30%
    for n in _parse_compact_nodes(tree):
        nid = str(n.get("id") or "").lower()
        if not nid or not compose_ids:
            continue
        if not any(
            c.lower().split("/")[-1] in nid or c.lower() in nid for c in compose_ids
        ):
            continue
        if int(n.get("y") or 0) >= y_min:
            return (int(n["x"]), int(n["y"]))
    # 2) any matching compose id (still after header verify)
    c = _tree_id_center(tree, *compose_ids) if compose_ids else None
    if c and c[1] >= y_min - 100:
        return c
    # 3) editable / exact label in bottom band only
    for n in _parse_compact_nodes(tree):
        if int(n.get("y") or 0) < y_min:
            continue
        lab = (n.get("label") or n.get("hint") or n.get("text") or "").strip().lower()
        if n.get("editable") or any(lab == str(x).lower() for x in compose_labels):
            return (int(n["x"]), int(n["y"]))
    return None


def hily_on_chats_list(tree: str) -> bool:
    """True on Hily chats inbox. Thread screens must not count as the list.

    Also accept Matches/All/Unread chrome (r22: tapped Chats then stalls when
    dialogMessageItem ids are missing but list names are visible).
    """
    if hily_on_thread(tree):
        return False
    if _tree_id_center(
        tree,
        "dialogMessageItem",
        "dialogsSearchButton",
        "userNameField",
    ):
        return True
    blob = (tree or "").lower()
    if hily_on_finder(tree, _log=False) or hily_on_top_picks_grid(tree):
        return False
    # Chats tab chrome without row ids
    if ("matches" in blob or "unread" in blob) and (
        "all" in blob or "chats" in blob or "dialogs" in blob
    ):
        return True
    return False


def hily_on_mbm(tree: str) -> bool:
    """True only on the Message Before Match *sheet*, not a chats-list row.

    List rows often preview 'Message before match' under a name (Paige) — that
    must NOT trigger Back/close loops. Require sheet chrome (closeButton /
    allowanceCounter / majorCrush + title), or title without chats list.
    """
    # r30: never treat the chats inbox as the MBM sheet — Paige's row
    # previews 'Message before match', and a sparse tree of that list used
    # to trip the title-only fallback and Back out of every open-chat tap.
    if hily_on_chats_list(tree):
        return False
    nodes = _parse_compact_nodes(tree)
    blob = " ".join(f"{n.get('id')} {n.get('label')}" for n in nodes).lower()
    has_phrase = "message before match" in blob or "majorcrush" in blob.replace("_", "")
    if not has_phrase:
        return False
    # Real MBM sheet chrome only — do not infer a sheet from the phrase alone.
    if _tree_id_center(
        tree,
        "closeButton",
        "id/closeButton",
        "allowanceCounter",
        "id/allowanceCounter",
        "sendMessageButton",
        "id/sendMessageButton",
        "userInfoBlockTitle",
        "id/userInfoBlockTitle",
    ):
        return True
    return False


def hily_on_photo_viewer(tree: str) -> bool:
    """Full-screen photo pager ('1 of 4') with app_top_bar_back — not the deck."""
    blob = (tree or "").lower()
    has_pager = bool(re.search(r"\b\d+\s+of\s+\d+\b", blob))
    has_back = bool(
        _tree_id_center(tree, "app_top_bar_back", "id/app_top_bar_back")
        or _tree_node_center(tree, "Navigate up")
    )
    # Photo viewer lacks Like/Pass gamepad
    has_like = bool(
        _tree_id_center(tree, "likeButton", "id/likeButton", "dislikeButton")
    )
    return has_pager and has_back and not has_like


def hily_on_profile_sheet(tree: str) -> bool:
    """Profile overlay with Crush / Major crush covering the deck or chats.

    Must be closed (Back) before chats-tab taps — otherwise bottom-nav coords
    hit Crush underneath (SAFETY: dry-run Crush incident).

    Do NOT match the normal Finder deck Crush CTA (~y 1959 next to Like/Pass).
    Do NOT match the chats inbox (APK 534: reply Back-loop hung 7 min).
    """
    if hily_on_mbm(tree):
        return False
    # Chat list is never a Crush sheet — reply must open rows, not Back
    if hily_on_chats_list(tree):
        return False
    blob = (tree or "").lower()
    # Explicit Major crush / MBM-adjacent sheet chrome
    if "major crush" in blob or "majorcrush" in blob.replace("_", "").replace("-", ""):
        return True
    # Finder deck has Skip/Pass + Crush mid-CTA row — not a covering sheet
    if _tree_id_center(
        tree,
        "ActionButton_SKIP",
        "id/ActionButton_SKIP",
        "finderCardUser",
    ):
        return False
    # Sheet Crush sits over the bottom-nav band (y≳2100), covering Chats taps
    for n in _parse_compact_nodes(tree):
        lab = (n.get("label") or "").lower()
        nid = str(n.get("id") or "").lower()
        if "crush" not in lab and "crush" not in nid:
            continue
        y = int(n.get("y") or 0)
        y2 = int(n.get("y2") or 0)
        if y >= 2100 or y2 >= 2180:
            return True
    return False


def hily_back_from_photo_viewer(
    planner: str = "hily_heuristic",
) -> Dict[str, Any]:
    return _fp(
        {
            "action": "press_button",
            "button": "back",
            "reason": (f"Back out of Hily photo viewer before swipe/chats ({planner})"),
            "planner": planner,
            "llm_provider": None,
        },
        "hily_photo_viewer_back",
    )


def hily_deck_card_name(tree: str) -> Optional[str]:
    """Best-effort Finder card name — id first, then name±age mid-screen text."""
    # r30: chats-list userNameField (Paige) must never count as a Finder card.
    if hily_on_chats_list(tree):
        return None
    for n in _parse_compact_nodes(tree):
        nid = str(n.get("id") or "").lower()
        # userNameAgeField / finderCardUser only — not userNameField (inbox).
        if "usernameagefield" not in nid and "findercarduser" not in nid:
            continue
        text = (n.get("text") or "").strip()
        if text and "," in text:
            return text.split(",")[0].strip()
        if text:
            return text
    # Sparse Finder: Like/Pass present but name id missing — scrape mid card
    skip = {
        "like",
        "pass",
        "crush",
        "skip",
        "boost",
        "finder",
        "chats",
        "profile",
        "hily",
        "message before match",
        "got it",
        "not now",
    }
    has_actions = bool(
        _tree_id_center(
            tree,
            "ActionButton_LIKE",
            "ActionButton_SKIP",
            "ActionButton_PASS",
            "id/ActionButton_LIKE",
        )
    )
    if not has_actions and not hily_on_finder(tree, _log=False):
        return None
    for n in _parse_compact_nodes(tree, package_filter="com.hily.app"):
        text = (n.get("text") or "").strip()
        y = int(n.get("y") or 0)
        if y < 200 or y > 1600:
            continue
        if text.lower() in skip or len(text) < 2:
            continue
        # "Sam, 24" or plain name
        if re.match(r"^[A-Za-z][A-Za-z\s'\-]{1,28}(?:,\s*\d{2})?$", text):
            return text.split(",")[0].strip()
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

    # r26: full-screen "They liked you / Find out who" sheet (no chat rows) → back
    text_blob = " ".join(
        (n.get("text") or n.get("label") or "") for n in nodes
    ).lower()
    if "they liked you" in text_blob or "find out who" in text_blob:
        has_chat_row = any(
            "dialogmessageitem" in str(n.get("id") or "").lower()
            or "usernamefield" in str(n.get("id") or "").lower()
            for n in nodes
        )
        if not has_chat_row:
            close = _tree_node_center(
                tree, "Close", "Not now", "No thanks", "Maybe later", "Got it"
            )
            if close:
                return _fp(
                    {
                        "action": "tap",
                        "x": close[0],
                        "y": close[1],
                        "reason": (
                            f"Dismiss Hily 'They liked you' sheet ({planner})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "hily_liked_you_dismiss",
                )
            return _fp(
                {
                    "action": "press_button",
                    "button": "back",
                    "reason": (
                        f"Back — dismiss Hily 'They liked you' sheet ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "hily_liked_you_back",
            )
        # List has real rows — row finder already skips the promo tile

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
    """Tap dialogMessageItem / userNameField matching contact.

    Never returns the 'They liked you!' / 'Find out who…' upsell tile.
    """
    best: Optional[Tuple[float, int, int]] = None
    for n in _parse_compact_nodes(tree):
        nid = str(n.get("id") or "").lower()
        text = (n.get("text") or n.get("label") or "").strip()
        if not text:
            continue
        low = text.lower()
        if "they liked you" in low or "find out who" in low or "dialogtag_liked" in nid:
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
    # Discover card: Like Icon / heart / X+crown row and/or "Send a message" + name/age
    has_like = False
    has_pass = False
    has_send_msg = False
    has_age = False
    for n in _parse_compact_nodes(tree):
        d = str(n.get("desc") or "").strip().lower()
        t = str(n.get("text") or "").strip().lower()
        lab = str(n.get("label") or "").strip().lower()
        if d == "like icon" or d in ("like", "heart") or lab in ("like", "heart"):
            has_like = True
        if d in ("pass", "x", "dislike", "nope") or t == "×" or lab == "x":
            has_pass = True
        if t == "send a message":
            has_send_msg = True
        # Age alone on card (e.g. "29") mid-screen
        if re.fullmatch(r"\d{2}", t) and 18 <= int(t) <= 80:
            y = int(n.get("y") or 0)
            if 400 < y < 2000:
                has_age = True
    if has_like or has_pass:
        return True
    if has_send_msg and "your turn" not in (tree or "").lower():
        return True
    # Age + bottom action cluster (X/heart/crown unlabeled) counts as deck
    if has_age and not blk_on_matches(tree):
        click_mid = [
            n
            for n in _parse_compact_nodes(tree)
            if n.get("clickable") and 1600 < int(n.get("y") or 0) < 2100
        ]
        if len(click_mid) >= 2:
            return True
    return False


def blk_on_matches(tree: str) -> bool:
    """True on Matches inbox — not Discover deck with bottom-nav 'Matches' tab."""
    nodes = _parse_compact_nodes(tree)
    blob = " ".join((n.get("text") or n.get("label") or "") for n in nodes).lower()
    if "your turn" in blob or "their turn" in blob:
        return True
    # Section header 'Matches' mid-screen — never the bottom-nav tab alone
    has_mid_matches = False
    for n in nodes:
        t = (n.get("text") or "").strip().lower()
        if t.startswith("matches") and 200 < int(n.get("y") or 0) < 1800:
            has_mid_matches = True
            break
    if not has_mid_matches:
        return False
    # Veto when Discover card chrome is present
    if any(
        str(n.get("desc") or "").strip().lower() == "like icon"
        or (n.get("text") or "").strip().lower() == "send a message"
        for n in nodes
    ):
        return False
    return True


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
    return (
        "you reached the end" in blob
        or "reached the end of the deck" in blob
        or "oh no! you reached the end" in blob
        or ("oh no" in blob and "end of the deck" in blob)
        or "reached the end" in blob
    )


# Profile section / category labels that must NEVER be treated as card names
# (r24: BLK 'Intentions', Taimi 'Health and Fitness').
_PROFILE_SECTION_LABELS = frozenset(
    {
        "intentions",
        "education",
        "height",
        "looking for",
        "religion",
        "ethnicity",
        "politics",
        "drinking",
        "smoking",
        "cannabis",
        "kids",
        "family plans",
        "exercise",
        "pets",
        "zodiac",
        "languages",
        "health and fitness",
        "health & fitness",
        "fitness",
        "interests",
        "basics",
        "more about me",
        "about me",
        "my vitals",
        "vitals",
        "prompts",
        "essentials",
        "lifestyle",
        "work",
        "job",
        "jobs",
        "school",
        "hometown",
        "location",
        "gender",
        "pronouns",
        "sexuality",
        "relationship type",
        "relationship goals",
        "causes and communities",
        "virtual dating",
        "filters",
        "filter",
        "discover",
        "boost",
        "pass",
        "like icon",
        "send a message",
        "matches",
        "likes",
        "profile",
        "curated for you",
        "active today",
        "people",
        "trending",
        "standouts",
        "preferred",
        # r26 false card/chat names from section chips / chrome
        "notes",
        "junk",
        "age",
        "ages",
        "distance",
        "verified",
        "new here",
        "recently active",
        "online",
        "offline",
        "photos",
        "photo",
        "videos",
        "spotlights",
        "compatibility",
        "astrology",
        "mbti",
        "love language",
        "looking for love",
        "they liked you",
        "find out who",
        "liked you",
        # r28: home-folder / chrome mistaken for card or chat names
        "social",
        "chats",
        "chat",
        "messages",
        "inbox",
        "conversations",
        "added you",
        "reactions",
        "elite pack",
        "see who added you",
        "send a message",
    }
)

_BLK_FILTER_CHIP_WORDS = _PROFILE_SECTION_LABELS


# Samsung home-folder titles that must never be read as dating-profile names.
_LAUNCHER_HOME_LABELS = frozenset(
    {
        "jobs",
        "notes",
        "social",
        "junk",
        "shopping",
        "online shopping",
        "travel & events",
        "travel and events",
        "msc uni info",
        "bible and prayer",
        "watchtv/gallery",
        "watchtv",
        "indeed job search",
        "health and fitness",
        "health & fitness",
        "finance & investments",
        "finance and investments",
        "folder",
    }
)


def is_launcher_home_label(text: str) -> bool:
    """True for Samsung launcher folder titles (Jobs, Social, …)."""
    low = (text or "").strip().lower().split(",")[0].strip()
    if not low:
        return False
    if low in _LAUNCHER_HOME_LABELS or low in _PROFILE_SECTION_LABELS:
        return True
    if low.endswith(", folder") or low.endswith(" folder"):
        return True
    return False


def looks_like_section_label(text: str) -> bool:
    """True for profile section/category labels (never a person name)."""
    low = (text or "").strip().lower()
    if not low:
        return True
    if low in _PROFILE_SECTION_LABELS:
        return True
    if any(w in low for w in _PROFILE_SECTION_LABELS if " " in w or "&" in w):
        return True
    return False


def looks_like_profile_name(text: str) -> bool:
    """True for 'Name' or 'Name, 28' — rejects section labels / chips."""
    t = (text or "").strip()
    if not t or len(t) > 40:
        return False
    if looks_like_section_label(t):
        return False
    # Prefer name, age; also accept plain first names
    if re.match(
        r"^[A-Za-z][A-Za-z'\-]*(?:\s+[A-Za-z][A-Za-z'\-]*){0,2}(?:,\s*\d{2})?$",
        t,
    ):
        return True
    return False


def _blk_looks_like_person_name(text: str) -> bool:
    return looks_like_profile_name(text)


def blk_deck_card_name(tree: str) -> Optional[str]:
    """Name = TextView immediately before 'Send a message' on the card.

    Rejects filter chips (Education, Height, …) that sit near the CTA.
    Also accepts Name / 'Name, 29' / age-adjacent person labels on Discover.
    """
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
            # Walk backward past filter chips to a person-like name
            for j in range(i - 1, max(-1, i - 6), -1):
                prev = texts[j][2].strip()
                if _blk_looks_like_person_name(prev):
                    return prev.split(",")[0].strip()
            return None
    # Fallback: Name, Age mid-card or person name above age digit
    for y, _x, t in texts:
        if 400 < y < 1900 and _blk_looks_like_person_name(t):
            if t.lower() in _BLK_FILTER_CHIP_WORDS:
                continue
            return t.split(",")[0].strip()
    for i, (y, _x, t) in enumerate(texts):
        if re.fullmatch(r"\d{2}", t) and 18 <= int(t) <= 80 and 400 < y < 2000:
            for j in range(i - 1, max(-1, i - 4), -1):
                prev = texts[j][2].strip()
                if _blk_looks_like_person_name(prev):
                    return prev.split(",")[0].strip()
            # Age alone still identifies a real card for dry-run markers
            return f"age_{t}"
    return None


def blk_dismiss_popup(
    tree: str, planner: str = "blk_heuristic"
) -> Optional[Dict[str, Any]]:
    """Super Like upsell → Send Like anyway; Streaks → Got it; Boost → Back; notif → Close."""
    nodes = _parse_compact_nodes(tree)
    blob = " ".join((n.get("text") or n.get("label") or "") for n in nodes).lower()
    # Peak-time Boost upsell — never Get Boost / Buy
    if (
        "get boost" in blob
        or "it's peak time" in blob
        or "its peak time" in blob
        or ("peak time" in blob and "boost" in blob)
    ):
        close = (
            _exact_label_center(tree, "Close")
            or _exact_label_center(tree, "Not now")
            or _exact_label_center(tree, "No thanks")
            or _tree_node_center(tree, "Close", "Not now", "No thanks", "Maybe later")
        )
        if close:
            return _fp(
                {
                    "action": "tap",
                    "x": close[0],
                    "y": close[1],
                    "reason": f"Dismiss BLK Boost peak-time upsell ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                    "label": "Close",
                },
                "blk_boost_dismiss",
            )
        return _fp(
            {
                "action": "press_button",
                "button": "back",
                "reason": f"Back — dismiss BLK Boost peak-time upsell ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "blk_boost_back",
        )
    if "introducing streaks" in blob or (
        "streaks" in blob and ("got it" in blob or "got it!" in blob)
    ):
        # Tap the Got it! text node (e.g. 540,2049) — never screen centre guess
        got = (
            _exact_label_center(tree, "Got it!")
            or _exact_label_center(tree, "Got it")
            or _tree_node_center(tree, "Got it!", "Got it", "GOT IT")
        )
        if got:
            return _fp(
                {
                    "action": "tap",
                    "x": got[0],
                    "y": got[1],
                    "reason": f"Dismiss BLK Introducing Streaks → Got it ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                    "label": "Got it!",
                },
                "blk_streaks_got_it",
            )
    if (
        "super like" in blob
        or "send a super like" in blob
        or "upgrade your like" in blob
    ):
        # Live-test / post-like upsell: prefer free dismiss, never upgrade CTA
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
                    "label": "Send Like anyway",
                },
                "blk_send_like_anyway",
            )
        close = (
            _exact_label_center(tree, "No thanks")
            or _exact_label_center(tree, "Not now")
            or _exact_label_center(tree, "Close")
            or _exact_label_center(tree, "Maybe later")
            or _tree_node_center(
                tree, "No thanks", "Not now", "Close", "Maybe later", "Cancel", "X"
            )
        )
        if close:
            return _fp(
                {
                    "action": "tap",
                    "x": close[0],
                    "y": close[1],
                    "reason": (
                        f"Dismiss Super Like upsell → Close/No thanks ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "label": "No thanks",
                },
                "blk_super_like_dismiss",
            )
        return _fp(
            {
                "action": "press_button",
                "button": "back",
                "reason": f"Back — dismiss Super Like upsell ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "blk_super_like_back",
        )
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
    """Normal Like = rightmost heart / 'Like Icon' (never left crown super-like).

    Prefer desc 'Like Icon' with left>=850 and top<1900 (cyan heart).
    Fallback: rightmost clickable in the 1600–1950 action band (X | heart | crown).
    """
    best: Optional[Tuple[int, int, int]] = None  # x1, x, y
    for n in _parse_compact_nodes(tree):
        d = str(n.get("desc") or "").strip().lower()
        if d != "like icon" and d not in ("like", "heart"):
            continue
        x1 = n.get("x1")
        y1 = n.get("y1")
        if x1 is None or y1 is None:
            x1 = int(n.get("x") or 0) - 40
            y1 = int(n.get("y") or 0) - 40
        if int(x1) < 850 or int(y1) >= 1900:
            continue
        if best is None or int(x1) > best[0]:
            best = (int(x1), int(n["x"]), int(n["y"]))
    if best is None:
        # Unlabeled X/heart/crown row — pick middle-right clickable (heart)
        band = [
            n
            for n in _parse_compact_nodes(tree)
            if n.get("clickable") and 1600 <= int(n.get("y") or 0) <= 2000
        ]
        band.sort(key=lambda n: int(n.get("x") or 0))
        # Avoid leftmost (X/pass) and rightmost crown if 3 buttons
        if len(band) >= 3:
            heart = band[-2]
            best = (
                int(heart.get("x1") or heart["x"]),
                int(heart["x"]),
                int(heart["y"]),
            )
        elif len(band) == 2:
            heart = band[-1]
            best = (
                int(heart.get("x1") or heart["x"]),
                int(heart["x"]),
                int(heart["y"]),
            )
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


# --- Hinge (co.hinge.app) SM-G996B — sparse a11y on main tabs ---


def hinge_on_discover(tree: str, *, _log: bool = True) -> bool:
    """Discover feed / profile: message box or 'Send a message', not Matches list."""
    if hinge_on_matches(tree, _log=False):
        return False
    if hinge_on_thread(tree):
        return False
    nodes = _hinge_nodes(tree)
    if not nodes:
        return False
    blob = " ".join(
        f"{n.get('text') or ''} {n.get('desc') or ''} {n.get('label') or ''}"
        for n in nodes
    ).lower()
    if "send a message" in blob:
        return True
    if any(n.get("editable") for n in nodes) and (
        "discover" in blob or "like" in blob or "rose" in blob
    ):
        return True
    # Prompt / name + age style card without Your turn
    if "your turn" not in blob and "their turn" not in blob:
        if any(
            t in blob
            for t in ("compatible", "most compatible", "we met on hinge", "prompt")
        ):
            return True
    return False


def hinge_on_matches(tree: str, *, _log: bool = True) -> bool:
    """Matches tab: Your turn / Their turn / Hidden section headers."""
    nodes = _hinge_nodes(tree)
    if not nodes:
        return False
    blob = " ".join((n.get("text") or n.get("label") or "") for n in nodes).lower()
    has_turn = "your turn" in blob or "their turn" in blob
    has_hidden = bool(re.search(r"\bhidden\b", blob))
    # Avoid treating Discover "Send a message" as Matches
    if "send a message" in blob and not has_turn:
        return False
    return has_turn or (has_hidden and "matches" in blob)


def hinge_on_thread(tree: str) -> bool:
    """Thread: sole EditText composer, not Discover CTA or Matches list."""
    nodes = _hinge_nodes(tree)
    if not nodes:
        return False
    edits = [n for n in nodes if n.get("editable")]
    if len(edits) != 1:
        return False
    blob = " ".join(
        f"{n.get('text') or ''} {n.get('desc') or ''} {n.get('label') or ''}"
        for n in nodes
    ).lower()
    if "your turn" in blob or "their turn" in blob:
        return False
    # Discover profile has EditText + 'Send a message' / Rose — not a thread
    if "send a message" in blob or "rose" in blob:
        return False
    return True


def hinge_deck_card_name(tree: str) -> Optional[str]:
    """Profile / Discover name — never invent profile_N / section labels."""
    skip = {
        "send a message",
        "like",
        "rose",
        "boost",
        "preferred",
        "hingex",
        "hinge x",
        "discover",
        "standouts",
        "likes you",
        "matches",
        "profile",
        "your turn",
        "their turn",
        "hidden",
        "message",
        "type a message",
        "say something",
        "skip",
        "comment",
        "share",
        "enable for",
        "dismiss",
        "intentions",
        "education",
        "health and fitness",
        "jobs",
        "notes",
        "social",
        "junk",
        "online shopping",
        "travel & events",
        "travel and events",
        "msc uni info",
        "bible and prayer",
        "watchtv/gallery",
        "indeed job search",
        "finance & investments",
        "finance and investments",
    }
    # Never fall back to launcher / other-package nodes (r30: "Jobs" folder).
    nodes = _hinge_nodes(tree)
    if not nodes:
        return None
    candidates: List[Tuple[int, str]] = []
    for n in nodes:
        t = (n.get("text") or "").strip()
        if not t or len(t) > 40:
            continue
        low = t.lower()
        if low in skip or low.startswith("enable for"):
            continue
        if looks_like_section_label(t) or is_launcher_home_label(t):
            continue
        if re.match(r"^profile\d+$", t, re.I):
            continue
        if re.match(r"^\d+$", t):
            continue
        # Name, age patterns: "Alex, 28" or plain "Alex"
        y = int(n.get("y1") if n.get("y1") is not None else n.get("y") or 0)
        if y > 1800:
            continue
        if not looks_like_profile_name(t):
            continue
        name = t.split(",")[0].strip()
        if len(name) < 2:
            continue
        candidates.append((y, name))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def hinge_dismiss_enable_prompt(
    tree: str, planner: str = "hinge_heuristic"
) -> Optional[Dict[str, Any]]:
    """Never tap 'Enable for <Name>'; dismiss at verified xy or Dismiss label."""
    nodes = _parse_compact_nodes(tree)
    blob = " ".join(
        f"{n.get('text') or ''} {n.get('desc') or ''} {n.get('label') or ''}"
        for n in nodes
    ).lower()
    if "enable for" not in blob and "get messages notifications" not in blob:
        return None
    dismiss = _tree_node_center(tree, "Dismiss", "Not now", "No thanks", "Close")
    if dismiss:
        return _fp(
            {
                "action": "tap",
                "x": dismiss[0],
                "y": dismiss[1],
                "reason": f"Dismiss Hinge Enable-for prompt ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "hinge_dismiss_enable",
        )
    xy = DM_APP_PROFILES["hinge"].get("notif_dismiss_xy") or (985, 396)
    return _fp(
        {
            "action": "tap",
            "x": int(xy[0]),
            "y": int(xy[1]),
            "reason": f"Dismiss Hinge Enable-for prompt (map xy) ({planner})",
            "planner": planner,
            "llm_provider": None,
        },
        "hinge_dismiss_enable",
    )


def hinge_dismiss_play_review(
    tree: str, planner: str = "hinge_heuristic"
) -> Optional[Dict[str, Any]]:
    """Google Play in-app review → Not now."""
    blob = " ".join(
        f"{n.get('text') or ''} {n.get('desc') or ''} {n.get('label') or ''}"
        for n in _parse_compact_nodes(tree)
    ).lower()
    if "rate this app" not in blob and "enjoying hinge" not in blob:
        if "not now" not in blob or "google play" not in blob:
            # Still allow bare Not now when review sheet copy is sparse
            if not (
                "not now" in blob
                and ("star" in blob or "review" in blob or "play" in blob)
            ):
                return None
    c = _tree_node_center(tree, "Not now", "No thanks")
    if not c:
        return None
    return _fp(
        {
            "action": "tap",
            "x": c[0],
            "y": c[1],
            "reason": f"Dismiss Play review → Not now ({planner})",
            "planner": planner,
            "llm_provider": None,
        },
        "hinge_play_review_not_now",
    )


def hinge_on_like_sheet(tree: str) -> bool:
    """Like sheet with Add a comment / Send Like / Rose (a11y present)."""
    blob = " ".join(
        f"{n.get('text') or ''} {n.get('desc') or ''} {n.get('label') or ''}"
        for n in _parse_compact_nodes(tree)
    ).lower()
    if "send like" in blob and ("add a comment" in blob or "rose" in blob):
        return True
    if "send a rose instead" in blob or "send like anyway" in blob:
        return True
    return False


def hinge_like_sheet_action(
    tree: str, planner: str = "hinge_heuristic"
) -> Optional[Dict[str, Any]]:
    """Prefer Send Like / Send Like anyway — never Rose / Send a Rose."""
    if not hinge_on_like_sheet(tree):
        return None
    anyway = _tree_node_center(tree, "Send Like anyway", "Send like anyway")
    if anyway:
        return _fp(
            {
                "action": "tap",
                "x": anyway[0],
                "y": anyway[1],
                "reason": f"Hinge Send Like anyway (never Rose) ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "hinge_send_like_anyway",
        )
    send_like = _exact_label_center(tree, "Send Like") or _tree_node_center(
        tree, "Send Like"
    )
    if send_like:
        return _fp(
            {
                "action": "tap",
                "x": send_like[0],
                "y": send_like[1],
                "reason": f"Hinge Send Like ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "hinge_send_like",
        )
    xy = DM_APP_PROFILES["hinge"].get("send_like_xy") or (686, 1277)
    return _fp(
        {
            "action": "tap",
            "x": int(xy[0]),
            "y": int(xy[1]),
            "reason": f"Hinge Send Like (map xy) ({planner})",
            "planner": planner,
            "llm_provider": None,
        },
        "hinge_send_like",
    )


def hinge_find_send_a_message(tree: str) -> Optional[Tuple[int, int]]:
    """Thread Send message desc, or Discover CTA — never Rose/Boost."""
    for n in _parse_compact_nodes(tree):
        t = (n.get("text") or n.get("label") or "").strip().lower()
        d = (n.get("desc") or "").strip().lower()
        if d == "send message" or t == "send message":
            return (int(n["x"]), int(n["y"]))
        if t == "send a message" or d == "send a message":
            return (int(n["x"]), int(n["y"]))
        if d == "record voice note":
            continue  # empty composer — not Send
    return _tree_node_center(tree, "Send a message", "Send message")


def _compose_editable(tree: str) -> Optional[Dict[str, Any]]:
    """The compose-box editable: the focused one, else the bottom-most.

    Shared selection so planners and the device-side target agree on which
    field the text must land in. Facebook keeps off-screen feed editables
    in the tree (r51) — the focused box wins over tree order.
    """
    edits = [n for n in _parse_compact_nodes(tree) if n.get("editable")]
    if not edits:
        return None
    focused = [n for n in edits if n.get("focused")]
    if focused:
        return focused[-1]
    return sorted(edits, key=lambda e: int(e.get("y") or 0))[-1]


def compose_box_text(tree: str) -> str:
    """Text currently in the compose box ('' when empty or no box).

    A box showing only its placeholder counts as its placeholder text here
    (Facebook renders the placeholder as the node's text until something
    is typed) — callers compare against the expected message, so an empty
    box never equals it.
    """
    n = _compose_editable(tree)
    if not n:
        return ""
    return str(n.get("text") or "").strip()


def compose_box_focused(tree: str) -> bool:
    """True when the compose box is the focused editable in the tree."""
    n = _compose_editable(tree)
    return bool(n and n.get("focused"))


def hinge_find_compose(tree: str) -> Optional[Tuple[int, int]]:
    """Thread / like-sheet comment EditText (hint Send a message / Add a comment)."""
    n = _compose_editable(tree)
    if not n:
        return None
    return (int(n["x"]), int(n["y"]))


def hinge_outgoing_verified(tree: str, message: str) -> bool:
    """View desc ' You: <text>. ' + TextView 'Sent'."""
    needle = (message or "").strip().lower()
    if len(needle) < 2:
        return False
    saw_you = False
    saw_sent = False
    for n in _parse_compact_nodes(tree):
        d = (n.get("desc") or "").strip().lower()
        t = (n.get("text") or "").strip().lower()
        if d.startswith("you:") and needle in d:
            saw_you = True
        if t == needle and "you:" in d:
            saw_you = True
        if t == "sent" or d == "sent":
            saw_sent = True
    return saw_you and saw_sent


def hinge_find_match_row(tree: str, contact: str) -> Optional[Tuple[int, int]]:
    """Matches list: Your turn / Their turn rows; skip Hidden section."""
    nodes = _hinge_nodes(tree)
    if not nodes:
        return None
    hidden_y: Optional[int] = None
    for n in nodes:
        t = (n.get("text") or "").strip().lower()
        if t == "hidden" or t.startswith("hidden"):
            hidden_y = int(n.get("y") or 0)
            break
    best: Optional[Tuple[float, int, int]] = None
    for n in nodes:
        text = (n.get("text") or "").strip()
        if not text:
            continue
        low = text.lower()
        if low.startswith(("your turn", "their turn", "hidden", "enable for")):
            continue
        y = int(n.get("y") or 0)
        if hidden_y is not None and y >= hidden_y:
            continue
        score = _fuzzy_score(contact, text)
        if score < 0.6:
            continue
        if best is None or score > best[0]:
            best = (score, int(n["x"]), y)
    return (best[1], best[2]) if best else None


def hinge_open_discover_tab(planner: str = "hinge_heuristic") -> Dict[str, Any]:
    xy = DM_APP_PROFILES["hinge"].get("deck_tab_xy") or (110, 2195)
    return _fp(
        {
            "action": "tap",
            "x": int(xy[0]),
            "y": int(xy[1]),
            "reason": f"Open Hinge Discover tab (nav xy) ({planner})",
            "planner": planner,
            "llm_provider": None,
        },
        "hinge_open_discover",
    )


def hinge_open_matches_tab(planner: str = "hinge_heuristic") -> Dict[str, Any]:
    xy = DM_APP_PROFILES["hinge"].get("inbox_tab_xy") or (754, 2195)
    return _fp(
        {
            "action": "tap",
            "x": int(xy[0]),
            "y": int(xy[1]),
            "reason": f"Open Hinge Matches tab (nav xy) ({planner})",
            "planner": planner,
            "llm_provider": None,
        },
        "hinge_open_matches",
    )


def _hinge_nodes(tree: str) -> List[Dict[str, Any]]:
    """Hinge-window nodes only. Never the legacy unscoped fallback (launcher)."""
    nodes = _parse_compact_nodes(tree or "", package_filter="co.hinge.app")
    return [
        n
        for n in nodes
        if "co.hinge.app" in (n.get("package") or "").lower()
    ]


def hinge_in_foreground(tree: str, package: str = "") -> bool:
    """True when the foreground window or given package is Hinge."""
    pkg = (package or "").lower()
    if "co.hinge.app" in pkg and "launcher" not in pkg:
        return True
    blob = tree or ""
    return 'p="co.hinge.app"' in blob or "p='co.hinge.app'" in blob


def hinge_find_top_match_row(tree: str) -> Optional[Tuple[int, int]]:
    """First Your-turn (else first) match row; skip Hidden. None if tree empty."""
    nodes = _hinge_nodes(tree)
    if not nodes:
        return None
    hidden_y: Optional[int] = None
    your_turn_y: Optional[int] = None
    for n in nodes:
        t = (n.get("text") or "").strip().lower()
        y = int(n.get("y") or 0)
        if t == "hidden" or t.startswith("hidden"):
            hidden_y = y
        if t.startswith("your turn"):
            your_turn_y = y
    rows: List[Tuple[int, int, int]] = []
    for n in nodes:
        text = (n.get("text") or "").strip()
        if not text or not n.get("clickable"):
            continue
        low = text.lower()
        if low.startswith(("your turn", "their turn", "hidden", "enable for", "matches")):
            continue
        if is_launcher_home_label(text) or looks_like_section_label(text):
            continue
        if not looks_like_profile_name(text):
            continue
        y = int(n.get("y") or 0)
        if hidden_y is not None and y >= hidden_y:
            continue
        rows.append((y, int(n["x"]), y))
    if not rows:
        return None
    if your_turn_y is not None:
        after = [r for r in rows if r[0] >= your_turn_y]
        if after:
            after.sort()
            return (after[0][1], after[0][2])
    rows.sort()
    return (rows[0][1], rows[0][2])


def hinge_tap_top_chat(planner: str = "hinge_heuristic") -> Dict[str, Any]:
    """Tap the top Matches row; uses mapped xy when the list has no a11y."""
    xy = DM_APP_PROFILES["hinge"].get("top_chat_xy") or (540, 480)
    return _fp(
        {
            "action": "tap",
            "x": int(xy[0]),
            "y": int(xy[1]),
            "reason": f"Open Hinge top match chat (row xy) ({planner})",
            "planner": planner,
            "llm_provider": None,
        },
        "hinge_tap_top_chat",
    )


def hinge_composer_visible(tree: str, vision_hint: str = "") -> bool:
    """True when the thread composer is in the a11y tree or confirmed by vision.

    Empty Discover/Matches trees must not count. Discover 'Send a message'
    CTA / Rose sheet is not a thread composer.
    """
    if hinge_find_compose(tree) and hinge_on_thread(tree):
        return True
    if hinge_find_compose(tree) and not hinge_on_discover(tree) and not hinge_on_matches(tree):
        return True
    hint = (vision_hint or "").lower()
    if not hint:
        return False
    if any(bad in hint for bad in ("like sheet", "send like", "rose", "standouts")):
        return False
    return any(
        tok in hint
        for tok in (
            "composer visible",
            "composer is visible",
            "message box visible",
            "message field visible",
            "text field visible",
            "keyboard visible",
            "type a message visible",
        )
    )


def hinge_launch_intent_action(
    planner: str = "hinge_heuristic",
    *,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Open Hinge via its launch intent — never launcher search."""
    return _fp(
        {
            "action": "open_app",
            "app": "Hinge",
            "package": "co.hinge.app",
            "launch_activity": "co.hinge.app/.ui.AppActivity",
            "open_mode": "launch_intent",
            "reason": reason or f"Open Hinge via launch intent ({planner})",
            "planner": planner,
            "llm_provider": None,
        },
        "hinge_launch_intent",
    )


def hinge_is_paid_label(text: str) -> bool:
    low = (text or "").strip().lower()
    return any(
        t in low
        for t in (
            "rose",
            "boost",
            "super boost",
            "preferred",
            "hingex",
            "hinge x",
            "hinge+",
            "hingeone",
            "dating intent",
            "super like",
            "standouts",
            "rewind",
        )
    )


def yubo_bottom_tab_center(
    tree: str,
    *,
    which: str = "chat",
) -> Optional[Tuple[int, int]]:
    """Map Yubo unlabeled bottom tabs by resource-id or x-position band.

    which: 'deck' | 'chat' | 'likes' | 'friends' | 'more'
    Prefer resource-ids when present; else leftmost→rightmost clickable band
    at y≳2000 (never the header Chat title ~y 159).
    """
    which_l = (which or "chat").lower()
    id_hints = {
        "deck": ("tab_home", "tab_people", "tab_discover", "nav_home", "for_you"),
        "chat": ("tab_chat", "tab_chats", "tab_messages", "nav_chat", "inbox"),
        "likes": ("tab_likes", "tab_crush", "nav_likes"),
        "friends": ("tab_friends", "nav_friends"),
        "more": ("tab_more", "tab_profile", "nav_more", "nav_menu"),
    }
    for tok in id_hints.get(which_l, ()):
        c = _tree_id_center(tree, tok, f"id/{tok}")
        if c and int(c[1]) >= 1800:
            return c
    # Position bands on 1080-wide S21+ (deck left of chat)
    bands = {
        "deck": (0, 240),
        "chat": (240, 440),
        "likes": (440, 640),
        "friends": (640, 840),
        "more": (840, 1080),
    }
    x0, x1 = bands.get(which_l, (240, 440))
    best = None
    best_y = -1
    for n in _parse_compact_nodes(tree):
        y = int(n.get("y") or 0)
        if y < 2000:
            continue
        x = int(n.get("x") or 0)
        if not (x0 <= x < x1):
            continue
        if not (n.get("clickable") or n.get("id")):
            continue
        if y > best_y:
            best_y = y
            best = (x, y)
    return best


def yubo_chat_tab_xy() -> Tuple[int, int]:
    """Unlabeled bottom-nav Chat tab — map by index (22 Nov)."""
    p = DM_APP_PROFILES.get("yubo") or {}
    tabs = p.get("tab_xy_by_index")
    idx = int(p.get("inbox_tab_index") or 0)
    if isinstance(tabs, (tuple, list)) and 0 <= idx < len(tabs):
        xy = tabs[idx]
        return (int(xy[0]), int(xy[1]))
    xy = p.get("inbox_tab_xy") or (341, 2194)
    return (int(xy[0]), int(xy[1]))


def yubo_deck_tab_xy() -> Tuple[int, int]:
    p = DM_APP_PROFILES.get("yubo") or {}
    xy = p.get("deck_tab_xy") or (140, 2194)
    return (int(xy[0]), int(xy[1]))


def tab_bar_verified(app: Optional[str], tree: str) -> bool:
    """True when bottom tab bar is on-screen (safe for fixed-xy nav taps)."""
    app_l = (app or "").lower()
    nodes = _parse_compact_nodes(tree)
    if not nodes:
        return False
    profile = DM_APP_PROFILES.get(app_l, {}) if app_l else {}
    nav_ids = tuple(profile.get("inbox_tab_ids") or ()) + tuple(
        profile.get("deck_tab_ids") or ()
    )
    if app_l == "bumble":
        nav_ids = nav_ids + (
            "mainApp_navigationTabBar",
            "com.bumble.app:id/mainApp_navigationTabBar",
        )
    if app_l == "badoo":
        nav_ids = nav_ids + (
            "nav_bar_button_connections",
            "nav_bar_button_encounters",
        )
    if app_l == "hily":
        nav_ids = nav_ids + ("bottomNavTab_1", "bottomNavTab_2", "bottomNavTab_4")
    if app_l == "tagged":
        nav_ids = nav_ids + ("tab_nearby", "tab_chats", "tab_match_game")
    if nav_ids and _tree_id_center(tree, *nav_ids):
        return True
    nav_y = int(profile.get("nav_y") or (profile.get("inbox_tab_xy") or (0, 2190))[1])
    near = [
        n
        for n in nodes
        if n.get("clickable") and abs(int(n.get("y") or 0) - nav_y) < 120
    ]
    if len(near) >= 3:
        return True
    labels = ("Chats", "Chat", "People", "Discover", "Matches", "Connections", "Nearby")
    hits = 0
    for lab in labels:
        c = _exact_label_center(tree, lab)
        if c and abs(int(c[1]) - nav_y) < 150:
            hits += 1
    return hits >= 1


def keyboard_likely_up(tree: str) -> bool:
    for n in _parse_compact_nodes(tree):
        if n.get("editable") and n.get("focused"):
            y = int(n.get("y") or 0)
            if 900 < y < 1800:
                return True
    blob = " ".join(
        f"{n.get('id') or ''} {n.get('desc') or ''}" for n in _parse_compact_nodes(tree)
    ).lower()
    return "inputmethod" in blob or "keyboard" in blob


# --- Tagged (com.taggedapp) S21+ map ---


def tagged_on_deck(tree: str) -> bool:
    if _tree_id_center(
        tree,
        "likeBtn",
        "id/likeBtn",
        "dislikeBtn",
        "id/dislikeBtn",
        "chatBtn",
        "id/chatBtn",
        "tvUsername",
        "id/tvUsername",
    ):
        return True
    if _tree_id_center(tree, "id/tagged_like", "tagged_like", "id/tagged_pass"):
        return True
    for n in _parse_compact_nodes(tree):
        t = (n.get("text") or n.get("label") or "").strip().lower()
        if t not in ("like", "pass", "chat"):
            continue
        if int(n.get("y") or 0) > 1500:
            return True
    return False


def tagged_on_chats(tree: str) -> bool:
    return bool(
        _tree_id_center(
            tree,
            "conversationList",
            "id/conversationList",
            "clConversationContainer",
            "id/clConversationContainer",
        )
    )


def tagged_location_overlay_continue(
    tree: str, planner: str = "tagged_heuristic"
) -> Optional[Dict[str, Any]]:
    blob = " ".join(
        f"{n.get('text') or ''} {n.get('label') or ''}"
        for n in _parse_compact_nodes(tree)
    ).lower()
    if "activate your location" not in blob:
        return None
    c = _tree_id_center(tree, "dcButtonContinue", "id/dcButtonContinue")
    if not c:
        return None
    return _fp(
        {
            "action": "tap",
            "x": c[0],
            "y": c[1],
            "reason": f"Tagged location overlay Continue ({planner})",
            "planner": planner,
            "llm_provider": None,
        },
        "tagged_location_continue",
    )


def tagged_exit_dialog_present(tree: str) -> bool:
    """System 'End Tagged?' / leave-app confirm after Back at root."""
    blob = " ".join(
        f"{n.get('text') or ''} {n.get('label') or ''} {n.get('desc') or ''}"
        for n in _parse_compact_nodes(tree)
    ).lower()
    if "end tagged" in blob:
        return True
    if "close tagged" in blob or "leave tagged" in blob:
        return True
    if "tagged?" in blob and ("end" in blob or "close" in blob or "exit" in blob):
        return True
    return False


def tagged_dismiss_exit_dialog(
    tree: str, planner: str = "tagged_heuristic"
) -> Optional[Dict[str, Any]]:
    """Dismiss 'End Tagged?' with Cancel — never confirm exit."""
    if not tagged_exit_dialog_present(tree):
        return None
    c = _exact_label_center(tree, "Cancel") or _tree_node_center(
        tree, "Cancel", "Stay", "No", "Keep using Tagged"
    )
    if c:
        return _fp(
            {
                "action": "tap",
                "x": c[0],
                "y": c[1],
                "reason": f"Dismiss End Tagged? → Cancel ({planner})",
                "planner": planner,
                "llm_provider": None,
                "label": "Cancel",
            },
            "tagged_exit_cancel",
        )
    # No Cancel visible — do nothing (never tap End / Yes)
    return _fp(
        {
            "action": "wait",
            "seconds": 0.8,
            "reason": (
                f"End Tagged? dialog — wait for Cancel; "
                f"refusing confirm exit ({planner})"
            ),
            "planner": planner,
            "llm_provider": None,
        },
        "tagged_exit_wait",
    )


def tagged_like_action(
    tree: str, planner: str = "tagged_heuristic"
) -> Optional[Dict[str, Any]]:
    c = _tree_id_center(tree, "likeBtn", "id/likeBtn")
    if not c:
        if not tagged_on_deck(tree):
            return None
        xy = DM_APP_PROFILES["tagged"].get("like_xy") or (860, 1908)
        c = (int(xy[0]), int(xy[1]))
    return _fp(
        {
            "action": "tap",
            "x": c[0],
            "y": c[1],
            "reason": f"Tagged likeBtn ({planner})",
            "planner": planner,
            "llm_provider": None,
        },
        "tagged_like",
    )


def tagged_chat_action(
    tree: str, planner: str = "tagged_heuristic"
) -> Optional[Dict[str, Any]]:
    """Match-card chatBtn — start free chat with a new contact (not Premium)."""
    if tagged_is_premium(tree):
        return None
    c = _tree_id_center(tree, "chatBtn", "id/chatBtn", "id/tagged_chat")
    if not c:
        if not tagged_on_deck(tree):
            return None
        # Prefer chat_btn_xy (map); fall back to legacy chat_xy key
        xy = (
            DM_APP_PROFILES["tagged"].get("chat_btn_xy")
            or DM_APP_PROFILES["tagged"].get("chat_xy")
            or (540, 1911)
        )
        c = (int(xy[0]), int(xy[1]))
    return _fp(
        {
            "action": "tap",
            "x": c[0],
            "y": c[1],
            "reason": f"Tagged chatBtn (new contact) ({planner})",
            "planner": planner,
            "llm_provider": None,
        },
        "tagged_chat",
    )


def tagged_deck_card_name(tree: str) -> Optional[str]:
    for n in _parse_compact_nodes(tree):
        nid = str(n.get("id") or "").lower()
        if "tvusername" in nid:
            text = (n.get("text") or "").strip()
            if (
                text
                and not re.match(r"Profile\d+", text, re.I)
                and not looks_like_section_label(text)
                and looks_like_profile_name(text.split(",")[0].strip())
            ):
                return text.split(",")[0].strip()
    skip = {
        "like",
        "pass",
        "tagged",
        "messages",
        "browse",
        "chat",
        "meet",
        "nearby",
        "live",
        "notes",
        "junk",
        "age",
    }
    for n in _parse_compact_nodes(tree, package_filter="com.taggedapp"):
        text = (n.get("text") or "").strip()
        if re.match(r"Profile\d+", text, re.I):
            continue
        if looks_like_section_label(text):
            continue
        if (
            looks_like_profile_name(text)
            and int(n.get("y") or 0) < 1200
            and text.lower() not in skip
        ):
            return text.split(",")[0].strip()
    return None


def tagged_is_premium(tree: str) -> bool:
    blob = " ".join(
        f"{n.get('text') or ''} {n.get('label') or ''}"
        for n in _parse_compact_nodes(tree)
    ).lower()
    return "tagged premium" in blob


def open_chat_thread_present(app: Optional[str], tree: str) -> bool:
    """True when an open 1:1 chat thread is showing (composer / header), not root.

    Detects leftover threads at job start: 'Type a message…', 'Aa', editable
    compose in the bottom band, or back-arrow + contact name without a tab bar.
    """
    if not tree:
        return False
    app_l = (app or "").lower()
    # Hinge Discover "Send a message" + Type a message is the deck card CTA —
    # never treat it as a leftover open thread (swipe recover must not Back).
    if app_l == "hinge" and hinge_on_discover(tree) and not hinge_on_thread(tree):
        return False
    # Already on a known list/deck with tab bar → not a stuck thread
    if tab_bar_verified(app_l, tree) and not keyboard_likely_up(tree):
        # Tab bar + no focused compose → treat as root even if a hint says Aa
        # (Bumble Connections can show search). Still catch focused thread.
        if app_l == "yubo" and yubo_on_chat(tree):
            return True
        if app_l == "hily" and hily_on_thread(tree):
            return True
        if app_l == "blk" and blk_on_thread(tree):
            return True
        if app_l == "taimi" and taimi_on_thread(tree):
            return True
        if app_l == "bumble" and compose_field_present(
            tree, ("Aa", "Message", "Type a message", "Say something")
        ):
            # Connections list has no Aa; thread does
            if not bumble_on_connections(
                tree, _log=False
            ) and not bumble_on_people_deck(tree, _log=False):
                return True
        if app_l == "badoo" and compose_field_present(
            tree, ("Aa", "Message", "Type a message")
        ):
            if not badoo_on_connections(tree, _log=False) and not badoo_on_encounters(
                tree, _log=False
            ):
                return True
        if app_l == "tagged" and compose_field_present(
            tree, ("Type a message...", "Type a message", "Message", "Aa")
        ):
            if not tagged_on_chats(tree) and not tagged_on_deck(tree):
                return True
        # WhatsApp / generic: compose without chats list rows
        return False

    profile = DM_APP_PROFILES.get(app_l, {}) if app_l else {}
    compose_labels = tuple(
        profile.get("compose_labels")
        or (
            "Aa",
            "Type a message",
            "Type a message...",
            "Message",
            "Write a message",
            "Say something",
        )
    )
    if compose_field_present(tree, compose_labels):
        # Compose without a verified tab bar → open thread
        if not tab_bar_verified(app_l, tree):
            return True
    # App-specific thread detectors
    if app_l == "yubo" and yubo_on_chat(tree):
        return True
    if app_l == "hily" and hily_on_thread(tree):
        return True
    if app_l == "blk" and blk_on_thread(tree):
        return True
    if app_l == "taimi" and taimi_on_thread(tree):
        return True
    if app_l == "bumble":
        # Aa composer + toolbar title / Back = open thread
        has_aa = compose_field_present(
            tree, ("Aa", "Message", "Type a message", "Say something")
        )
        has_back = any(
            (n.get("label") or n.get("desc") or "").strip().lower()
            in ("back", "navigate up")
            or str(n.get("id") or "").lower().endswith("/back")
            for n in _parse_compact_nodes(tree)
            if int(n.get("y") or 0) < 400
        )
        if has_aa and has_back and not bumble_on_connections(tree, _log=False):
            return True
    if app_l == "badoo":
        if compose_field_present(tree, ("Aa", "Message", "Type a message")) and not (
            badoo_on_encounters(tree, _log=False)
            or badoo_on_connections(tree, _log=False)
        ):
            return True
    if app_l == "tagged":
        if compose_field_present(
            tree, ("Type a message...", "Type a message", "Message", "Aa")
        ) and not (tagged_on_chats(tree) or tagged_on_deck(tree)):
            return True
    if app_l in ("whatsapp", "wa") or (not app_l and "com.whatsapp" in (tree or "")):
        if compose_field_present(
            tree, ("Message", "Type a message", "Write a message")
        ) and not _tree_id_center(
            tree,
            "com.whatsapp:id/conversations_row_contact_name",
            "contact_row_container",
        ):
            return True
    # Generic: Back + name header + bottom editable, no tab bar
    nodes = _parse_compact_nodes(tree)
    has_back = False
    has_header_name = False
    has_bottom_edit = False
    for n in nodes:
        lab = (n.get("label") or n.get("desc") or n.get("text") or "").strip().lower()
        nid = str(n.get("id") or "").lower()
        y = int(n.get("y") or 0)
        if y < 400 and (
            lab in ("back", "navigate up")
            or nid.endswith("/back")
            or "navigateup" in nid
        ):
            has_back = True
        if (
            y < 400
            and not n.get("editable")
            and lab
            and len(lab) >= 2
            and lab
            not in (
                "back",
                "close",
                "more",
                "search",
                "video call",
                "audio call",
                "call",
            )
            and re.match(r"^[a-z][a-z0-9 .'\-]{1,30}$", lab)
        ):
            has_header_name = True
        if n.get("editable") and y > 1600 and "search" not in lab:
            has_bottom_edit = True
    if (
        has_back
        and has_header_name
        and has_bottom_edit
        and not tab_bar_verified(app_l, tree)
    ):
        return True
    return False


def app_overlay_present(app: Optional[str], tree: str) -> Optional[str]:
    """Return overlay name when a sheet/modal/viewer covers the root UI.

    Discover grids / bottom-nav remaining in the dump under a sheet must NOT
    count as a safe root — callers must Back/close first.
    """
    app_l = (app or "").lower()
    if not tree:
        return None
    if keyboard_likely_up(tree):
        return "keyboard"
    # Hinge like/comment sheet before generic thread (editable + Send Like
    # was misclassified as open_chat_thread → Back — r23 hinge_new3).
    if app_l == "hinge" and hinge_on_like_sheet(tree):
        return "hinge_like_sheet"
    if open_chat_thread_present(app_l, tree):
        return "open_chat_thread"
    if app_l == "bumble" and bumble_on_photo_browser(tree):
        return "bumble_photo_browser"
    if app_l == "hily":
        if hily_on_mbm(tree):
            return "hily_mbm"
        if hily_on_photo_viewer(tree):
            return "hily_photo_viewer"
        if hily_on_profile_sheet(tree):
            return "hily_profile_sheet"
    if app_l == "yubo":
        blob = (tree or "").lower()
        if "blast" in blob and ("direct" in blob or "send a message" in blob):
            # Direct/Blast compose sheet over deck
            if "yubucks" in blob or "blast" in blob:
                return "yubo_direct_sheet"
    if app_l == "tagged":
        blob = (tree or "").lower()
        if "continue" in blob and (
            "location" in blob or "enable location" in blob or "where are you" in blob
        ):
            return "tagged_location_overlay"
    if app_l == "blk":
        blob = (tree or "").lower()
        if "introducing streaks" in blob or ("streaks" in blob and "got it" in blob):
            return "blk_streaks_sheet"
        if "super like" in blob and ("send a super like" in blob or "instead" in blob):
            return "blk_super_like_sheet"
    if app_l == "badoo":
        blob = (tree or "").lower()
        if "buy credits" in blob or (
            "credits" in blob and ("close" in blob or "not now" in blob)
        ):
            return "badoo_credits_sheet"
    return None


def known_root_screen(app: Optional[str], tree: str) -> bool:
    """Deck, chat list, or verified tab bar — safe place to start a job.

    False whenever a sheet/modal/viewer overlay is present, even if Discover
    grid / bottom-nav nodes remain underneath in the dump.
    """
    app_l = (app or "").lower()
    if app_overlay_present(app_l, tree):
        return False
    if tab_bar_verified(app_l, tree):
        return True
    if app_l == "bumble":
        return (
            bumble_on_people_deck(tree, _log=False)
            or bumble_on_connections(tree, _log=False)
            or bumble_on_photo_grid(tree)
        ) and not bumble_on_photo_browser(tree)
    if app_l == "yubo":
        return yubo_on_deck(tree, _log=False) or yubo_on_chat_list(tree, _log=False)
    if app_l == "badoo":
        return badoo_on_encounters(tree, _log=False) or badoo_on_connections(
            tree, _log=False
        )
    if app_l == "hily":
        return (
            hily_on_finder(tree, _log=False)
            or hily_on_chats_list(tree)
            or hily_on_top_picks_grid(tree)
        ) and not hily_on_mbm(tree)
    if app_l == "hinge":
        return hinge_on_discover(tree, _log=False) or hinge_on_matches(tree, _log=False)
    if app_l == "tagged":
        return tagged_on_deck(tree) or tagged_on_chats(tree)
    if app_l == "blk":
        return blk_on_deck(tree) or blk_on_matches(tree)
    if app_l == "taimi":
        return taimi_on_people_deck(tree) or taimi_on_chats_list(tree)
    return False


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


_TAIMI_NOTIF_APP_TOKENS = frozenset(
    {
        "indeed",
        "job search",
        "linkedin",
        "gmail",
        "messages",
        "notification",
        "battery",
        "charging",
        "whatsapp",
        "instagram",
        "facebook",
        "chrome",
        "play store",
        "samsung",
        "android system",
        "mobilerun",
    }
)


def _looks_like_notif_or_app_title(text: str) -> bool:
    """True for notification / other-app titles (never a dating card name)."""
    low = (text or "").strip().lower()
    if not low:
        return True
    if any(tok in low for tok in _TAIMI_NOTIF_APP_TOKENS):
        return True
    # Multi-word Title Case app names ("Indeed Job Search", "Google Play Store")
    words = low.split()
    if len(words) >= 2 and any(
        w in ("job", "search", "store", "mail", "maps", "drive", "news")
        for w in words
    ):
        return True
    return False


def taimi_deck_card_name(tree: str) -> Optional[str]:
    """Name = large text roughly y 1507–1665 (not labels / icebreakers / notifs).

    Scope to com.takimi.android only — r22 false-passed 'Indeed Job Search'
    from a notification window when package_filter was absent.
    """
    skip = {
        "curated for you",
        "active today",
        "people",
        "likes",
        "chats",
        "profile",
        "trending",
        "left",
        "health and fitness",
        "health & fitness",
        "intentions",
        "interests",
        "basics",
    }
    best: Optional[Tuple[int, str]] = None
    nodes = _parse_compact_nodes(tree, package_filter="com.takimi.android")
    if not nodes:
        # Fall back but still reject foreign packages / notif titles
        nodes = [
            n
            for n in _parse_compact_nodes(tree)
            if "takimi" in str(n.get("package") or "").lower()
            or not str(n.get("package") or "").strip()
        ]
    for n in nodes:
        text = (n.get("text") or "").strip()
        if not text or len(text) > 40:
            continue
        pkg = str(n.get("package") or "").lower()
        if pkg and "takimi" not in pkg and "taimi" not in pkg:
            continue
        low = text.lower()
        if low in skip or "left" in low:
            continue
        if looks_like_section_label(text):
            continue
        if _looks_like_notif_or_app_title(text):
            continue
        if low.startswith(",") or ", ," in low:
            continue  # icebreaker chip
        # Require person-like name (Name / Name, age) — never categories
        if not looks_like_profile_name(text):
            continue
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


def parse_existing_chats_instruction(instruction: str) -> Optional[Dict[str, Any]]:
    """Parse 'message/reply \"body\" to N existing chat(s) on <app>'.

    Returns {app, message, count} for the deterministic first-N chats path
    (never invents a contact name for the AI planner).
    """
    text = (instruction or "").strip()
    if not text:
        return None
    m = re.search(
        r"(?:reply|message|auto[- ]?message)\s+[\"']([^\"']+)[\"']\s+"
        r"to\s+(\d+)\s+(?:existing\s+)?chats?\s*(?:on\s+(\w+))?",
        text,
        re.I,
    )
    if not m:
        m = re.search(
            r"(?:reply|message)\s+[\"']([^\"']+)[\"']\s+"
            r"to\s+(\d+)\s+existing\s+chats?",
            text,
            re.I,
        )
    if not m:
        return None
    app_key = detect_dm_app(text)
    if not app_key and m.lastindex and m.lastindex >= 3 and m.group(3):
        token = m.group(3).strip().lower()
        if token in DM_APP_PROFILES:
            app_key = token
    if not app_key:
        return None
    return {
        "app": app_key,
        "message": m.group(1).strip(),
        "count": int(m.group(2)),
        "existing_chats": True,
    }


def parse_dm_instruction(instruction: str) -> Optional[Dict[str, str]]:
    """Extract {app, contact, message} from a DM send goal.

    Supports phrasings like:
      whatsapp find and message Precious Achalugo tell her hi baby
      go on whatsapp message X and say Y

    Existing-chats bulk goals (\"message 'hi' to 1 existing chat on WhatsApp\")
    return a structured first-N marker — never a fake contact name.
    """
    text = (instruction or "").strip()
    if not text:
        return None
    existing = parse_existing_chats_instruction(text)
    if existing:
        return {
            "app": str(existing["app"]),
            "contact": f"__existing_{existing['count']}__",
            "message": str(existing["message"]),
            "existing_count": existing["count"],  # type: ignore[dict-item]
        }
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
        # Never treat "N matches/people/chats" as a contact (bulk goals).
        if _is_bulk_quantity_contact(contact):
            continue
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
    agent_state: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Generic DM fast-path. Returns an action dict or None."""
    parsed = parse_dm_instruction(instruction)
    if not parsed:
        return None
    # First-N existing chats (WhatsApp / dating): deterministic bulk path —
    # never hand a synthetic contact to the AI planner.
    if parsed.get("existing_count") or str(parsed.get("contact") or "").startswith(
        "__existing_"
    ):
        try:
            from bulk_bench_heuristics import plan_bulk_message
        except ImportError:
            from backend.bulk_bench_heuristics import plan_bulk_message  # type: ignore

        return plan_bulk_message(
            instruction,
            ui_tree,
            history,
            state=agent_state if isinstance(agent_state, dict) else {},
            package=package,
            dry_run=dry_run,
        )
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
            or "tap hily chat" in str(h).lower()
            or "tap blk match" in str(h).lower()
            or "tap taimi chat" in str(h).lower()
            or "hily_tap_chat" in str(h).lower()
            or "blk_tap_match" in str(h).lower()
            or "taimi_tap_chat" in str(h).lower()
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
            and not yubo_on_chat_list(ui_tree, _log=False)
            and not yubo_on_chat(ui_tree)
        ):
            # Prefer bottom-nav Chat (never header title ~y 159).
            chats = _nav_tab_center(
                ui_tree,
                "Chat",
                "Chats",
                "Conversations",
                ids=tuple(profile.get("inbox_tab_ids") or ()),
            )
            if chats and int(chats[1]) < 1800:
                chats = None  # header Chat — refuse
            if not chats:
                chats = yubo_bottom_tab_center(ui_tree, which="chat")
            if not chats:
                # Real device: unlabeled tabs — use index map (341,2194)
                chats = yubo_chat_tab_xy()
                return _fp(
                    {
                        "action": "tap",
                        "x": int(chats[0]),
                        "y": int(chats[1]),
                        "reason": (
                            f"Open Yubo Chat tab by index "
                            f"(no text/desc) ({planner})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                        "label": "Chat",
                        "needs_vision": True,
                    },
                    "yubo_open_chat_tab",
                )
            return _fp(
                {
                    "action": "tap",
                    "x": int(chats[0]),
                    "y": int(chats[1]),
                    "reason": f"Open Chat tab from Yubo deck ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                    "label": "Chat",
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
            if tab_bar_verified("badoo", ui_tree):
                tab = profile.get("inbox_tab_xy") or (756, 2210)
                return _fp(
                    {
                        "action": "tap",
                        "x": int(tab[0]),
                        "y": int(tab[1]),
                        "reason": f"Open Chats tab (nav bar verified) ({planner})",
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "badoo_open_chats_tab",
                )
            return _fp(
                {
                    "action": "press_button",
                    "button": "back",
                    "reason": (
                        f"Badoo tab bar not verified — back before nav xy "
                        f"({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "badoo_recover_before_nav",
            )

    # --- Hily real-device path (buttons only; never CRUSH / Allow / Audio) ---
    if app_key == "hily" and pkg_ok:
        popup = hily_dismiss_popup(ui_tree, planner=planner)
        if popup:
            return popup
        # MBM sheet: close and do not re-tap the same list row underneath
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
            closed = hily_close_mbm(ui_tree, planner=planner)
            if closed:
                return closed
        if (
            not chat_ok
            and not typed_message
            and (hily_on_finder(ui_tree) or hily_on_top_picks_grid(ui_tree))
            and not hily_on_chats_list(ui_tree)
            and not hily_on_thread(ui_tree)
        ):
            if not tab_bar_verified("hily", ui_tree):
                return _fp(
                    {
                        "action": "press_button",
                        "button": "back",
                        "reason": (
                            f"Hily tab bar not verified — back before nav "
                            f"({planner})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "hily_recover_before_nav",
                )
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

    # --- Hinge real-device path (sparse a11y; never Rose/Boost/Preferred/HingeX) ---
    if app_key == "hinge" and pkg_ok:
        play = hinge_dismiss_play_review(ui_tree, planner=planner)
        if play:
            return play
        popup = hinge_dismiss_enable_prompt(ui_tree, planner=planner)
        if popup:
            return popup
        if hinge_on_like_sheet(ui_tree) and not typed_message:
            # Existing-chat path should leave Discover like sheet
            return _fp(
                {
                    "action": "press_button",
                    "button": "back",
                    "reason": f"Leave Hinge like sheet → Matches ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "hinge_leave_like_sheet",
            )
        if (
            not chat_ok
            and not typed_message
            and hinge_on_discover(ui_tree)
            and not hinge_on_matches(ui_tree)
            and not hinge_on_thread(ui_tree)
        ):
            return hinge_open_matches_tab(planner=planner)
        if (
            not chat_ok
            and not typed_message
            and not tapped_contact
            and hinge_on_matches(ui_tree)
        ):
            row = hinge_find_match_row(ui_tree, contact)
            if row:
                return _fp(
                    {
                        "action": "tap",
                        "x": row[0],
                        "y": row[1],
                        "reason": f"Tap Hinge match '{contact}' (skip Hidden) ({planner})",
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "hinge_tap_match",
                )

    # 0a) If the contact row is already on-screen (inbox / matches list), tap it
    # before any search field — dating decks often expose a Search affordance
    # that would otherwise steal the flow. Never tap deck cards / counters /
    # substring hits; require chat-list row + exact/whole-word name.
    if (
        not chat_ok
        and not typed_message
        and not tapped_contact
        and not (app_key == "hily" and hily_on_thread(ui_tree))
        and not (app_key == "blk" and blk_on_thread(ui_tree))
        and not (app_key == "taimi" and taimi_on_thread(ui_tree))
    ):
        visible = find_contact_result_center(
            ui_tree,
            contact,
            search_labels=search_labels,
            result_ids=tuple(profile.get("result_ids") or ()),
            exclude_ids=tuple(profile.get("result_exclude_ids") or ()),
        )
        if visible is None:
            # Fake-chats rows: exact "Chat with X" / "Match X" labels only
            for needle in (f"Chat with {contact}", f"Match {contact}"):
                for n in _parse_compact_nodes(ui_tree):
                    lab = (n.get("label") or n.get("text") or "").strip()
                    if lab.lower() == needle.lower() and _looks_like_chat_list_row(n):
                        visible = (int(n["x"]), int(n["y"]))
                        break
                if visible:
                    break
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
        and not (app_key == "hinge" and hinge_on_matches(ui_tree))
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
            or (app_key == "hinge" and hinge_on_discover(ui_tree))
            or (app_key == "tagged" and tagged_on_deck(ui_tree))
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
            if app_key in (
                "bumble",
                "yubo",
                "badoo",
                "hily",
                "blk",
                "taimi",
                "hinge",
            ):
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
            elif app_key in ("tinder", "instagram") or (
                profile.get("package") or ""
            ).startswith(("com.tinder",)):
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
        and not (app_key == "hinge" and hinge_on_matches(ui_tree))
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
        or (
            app_key == "hinge"
            and (hinge_on_matches(ui_tree) or hinge_on_thread(ui_tree))
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
        # dry_run: NEVER type into a real thread (shows "typing…" to peer).
        if dry_run:
            return _fp(
                {
                    "action": "done",
                    "reason": (
                        f"[DRY RUN] composer verified for '{contact}'; "
                        f"would send '{message}' — never typed; send skipped"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "dry_run": True,
                    "dry_run_verified": True,
                    "screenshot": True,
                    "would_send_text": message,
                },
                "dry_run_verify_composer_no_type",
            )
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

    # 6) Send — prefer visible Send ImageButton (appears after text).
    # Dry-run: composer already verified above without typing — stop.
    # WA: never IME Enter in search (Meta AI); prefer tap Send in chat too.
    if typed_message and not tapped_send:
        if dry_run:
            return _fp(
                {
                    "action": "done",
                    "reason": (
                        f"dry_run — compose verified (never typed) for "
                        f"'{contact}'; send skipped"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "dry_run": True,
                    "dry_run_verified": True,
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
        if c is None and app_key == "hinge":
            # Prefer 'Send a message' on Discover; thread uses Send
            c = hinge_find_send_a_message(ui_tree) or find_send_center_safe(
                ui_tree, ("Send",), send_ids=(), profile=profile
            )
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
