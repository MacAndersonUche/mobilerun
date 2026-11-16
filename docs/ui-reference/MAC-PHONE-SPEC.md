# Mac phone UI spec (cloud.mobilerun.ai recording)

Mobile-first dark UI. Bottom sheets with drag handle for menus/settings. Sticky bottom chat input.

## 1) Home — Your agents

- Header: title **Your agents** + avatar (opens Account sheet)
- **Getting started · x of 3** onboarding card (blue tint)
- Horizontal agent row: pixel-art avatars + names + **+ New**
- **COMING UP**: routines; empty = “No routine planned yet — Build one with \<agent\>”
- **DEVICES** card: Online (green) / Busy (gray) / Offline (red) counts
- **All activity** card: “Every run and chat of your agents”
- Integrate Needs-you, Dating, Social as same-language cards

## 2) Agent chat

- Header: back, avatar+name, settings icon
- Date dividers
- User bubbles right (dark gray)
- Agent responses as structured cards:
  - device row (phone icon, model, green Ready badge, latency ms)
  - collapsible Thoughts
  - action steps (check, title, Done badge, duration, subtext)
  - final text answer
  - suggested follow-up pills with arrow
- Bottom input: “Ask \<agent\>…” + sparkle + circular send
- Chat is the AI interaction agent (PC / hosted server toggle in settings)

## 3) Agent settings sheet — `\<name\> · Settings`

Tabs: **Devices** / **Routines** / **Agent**

Agent tab:

- Pixel avatar + color swatches (Shuffle / Reset)
- Name input
- “What \<name\> focuses on” textarea 0/1500
- Model picker radio cards: Best / Balanced / Saver → Gemini / Claude / OpenAI / Grok
- Rows: Skills, Files, red Force stop
- Modes: Normal / Dating / Social + speed preset
- Run on: Hosted server / My PC

## 4) Account sheet

- Developer platform card (Devices, API keys and runs)
- Profile card (avatar initial, name, badge, email, edit)
- List: Workspace, Notifications, Preferences, **AWS cost** (was Billing), Usage, Connect AI tools
- Help & support; Copy user ID; red Log out; footer logo

## Also keep (same language)

- Live device view panel
- Needs-you queue
- Dating / Social stats
