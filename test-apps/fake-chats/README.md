# Fake Chats — emulator DM bench

Seven product-flavor APKs that mimic WhatsApp / Instagram / Messenger / Telegram /
Tinder / Bumble / Hinge view hierarchies (resource-ids + labels) so the Mobilerun
agent can be tested without real accounts or Mac's phone.

| Flavor | applicationId | Key compose / send ids |
|--------|---------------|------------------------|
| whatsapp | `com.whatsapp` | `id/entry`, `id/send` |
| instagram | `com.instagram.android` | `id/row_thread_composer_edittext`, `id/row_thread_composer_button_send` |
| messenger | `com.facebook.orca` | `id/composer_text`, `id/composer_send_button` |
| telegram | `org.telegram.messenger` | `id/chat_message_edit`, `id/chat_send_button` |
| tinder | `com.tinder` | `id/message_input`, `id/send_button` |
| bumble | `com.bumble.app` | `id/message_box`, `id/send_cta` |
| hinge | `co.hinge.app` | `id/your_message`, `id/send_message` |

Each conversation seeds an **old** outgoing bubble with text `hi baby`. A successful
agent send appends a **new** bubble and a line to `files/sent_messages.jsonl`
(readable via `adb shell run-as <pkg> cat files/sent_messages.jsonl`).

Tricky cases baked in: duplicate contact rows, search field keeps focus, soft
keyboard may cover Send, seed bubble already contains target text.

## Build

```bash
cd test-apps/fake-chats
./gradlew assembleDebug
```

## CI

`.github/workflows/fake-chats-emu-matrix.yml` runs the matrix **3 times** on an
API-34 emulator (KVM). Driver: `scripts/fake_chats_emu_e2e.sh` +
`scripts/fake_chats_emu_matrix.py`.
