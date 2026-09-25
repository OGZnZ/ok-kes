# ok-kes Usage Guide

This guide covers downloading and installing ok-kes, the app UI, game settings, and how to configure Chaos Mode and Sortie Mode.

## Download & Install

1. Download the app. The app supports auto-update: after downloading an older version, it updates to the latest version on launch. Download from: [GitHub](https://github.com/baoxin1100/ok-kes/releases), [MirrorChyan](https://mirrorchyan.com/zh/projects?rid=ok-kes), or [Quark cloud drive](https://pan.quark.cn/s/13b266aa8e80).
2. Install the tool into a pure-English directory path.

## App UI Overview

![App launch screen](../images/usage-guide/software-interface.png)

- Launch the game in **windowed mode**; pick the game window in the window-selection area; set the interaction method to **PostMessage**, then click **Start**.
- **Export Logs** exports the tool's runtime logs. If you hit a bug, export the logs and @ the group owner in the QQ group.
- Under **Settings** in the bottom-left corner you can pick the OCR backend. The default is "Auto": OpenVINO when memory is 12 GB or more, ONNX Runtime when below 12 GB. OpenVINO uses more memory (about 6–8 GB); ONNX Runtime uses less memory (about 1–2 GB) but more CPU.

## Mode UI Overview

![Mode screen](../images/usage-guide/mode-interface.png)

- The tool has three modes: **Auto Chaos Mode** (Season Chaos, Zero System, Chaos Manifestation), **Auto Sortie Mode**, and **Semi-Auto Story Mode**.
- Open the matching mode's screen before enabling it. You can enable it on a screen with an "Enter" button, or after entering the mode. Enabling it on the game's main page does nothing and the toggle switches itself off, preventing accidental clicks.
- **Config actions**: the tool supports **Import Config Code**, **Export Config Code**, **Hot Configs**, **Save Config**, and **Switch Config**. Hot configs are uploaded automatically by tool users. If you do not want to upload anything, disable uploading in the tool settings; hot configs become unavailable after that.

![Semi-auto story mode entry](../images/usage-guide/story-mode.png)

- **Semi-Auto Story Mode** must be enabled on the screen shown above. On battle stages, manually click your team members or it gets stuck on the member-selection screen (no need to disable the mode); on chaos stages, manually enable "Auto Chaos Mode".

## Game Settings

![Enable hotkey display](../images/usage-guide/shortcut-display.png)

- On PC, Sortie Mode's Auto Battle depends on key recognition. Open the game settings as shown above and set **Hotkey Display** to ON — this noticeably improves card-play accuracy and battle win rates.

![Enable auto dialogue](../images/usage-guide/auto-dialogue.png)

- After entering the game, **manually enable auto dialogue** in the top-right corner of the game.

![Remove number mappings in the hand area on the MuMu emulator](../images/usage-guide/mumu-key-mapping.png)

- On the MuMu emulator, **manually remove the number mappings in the hand area**, as shown above.

## Config Reference

### Chaos Mode Config

!!! note "CN vs. international server configs"

    The CN and international servers use different translations, so member configs do not transfer between them. When adapting a CN config for the international server, either Simplified or Traditional text works (no need to convert Simplified to Traditional). Example: the CN card 【剑雨】 matches the international card 【劍之雨】; an international config can use 【劍之雨】 or 【剑之雨】, but not 【剑雨】 directly.

- **Config actions**: the tool supports **Import Config Code**, **Export Config Code**, **Hot Configs**, **Save Config**, and **Switch Config**. Hot configs are uploaded automatically by tool users. If you do not want to upload anything, disable uploading in the tool settings; hot configs become unavailable after that.
- **Game Language**: Simplified Chinese for the CN server, Traditional Chinese for the international server.
- **Save-data farming member**: accepts exactly one battle member. Later equipment assignment, card copying, flashing, removal, and similar features prioritize that member by default. Chaos Mode cannot auto-pick teams — **pick the team manually**, and the name entered must be one of the three battle members.

![Save-data farming member config](../images/usage-guide/target-member-config.png)

- **Minimum save-data value tier**: matches the data-value tiers shown below; tiers below the requirement refresh automatically.

| Season Chaos | Zero System |
| :---: | :---: |
| ![Season Chaos save-data value](../images/usage-guide/save-data-level-chaos.png) | ![Zero System save-data value](../images/usage-guide/save-data-level-zero-system.png) |

- **Keep save data above TB value**: save data below this value is recycled into gold automatically.
- **Claim rewards (verification cards only)**: to claim rewards with stamina, manually convert stamina into verification cards first. When verification cards run out, the feature switches itself off and Chaos farming continues.
- **Task priority**: matches the option-card content shown below. You can enter any partial fields from the title or body, but all fields must follow the original text order, with no symbols added between the title and body. Key fields are enough — overly complete text can fail to match when OCR drops characters.

![Event task options](../images/usage-guide/event-options.png)

> Example: with only 【移除】 configured, the first and third options match. From left to right, the first option wins. To prefer the third option instead, configure 【"移除2张","移除"】.

![Event task sub-sequence matching example](../images/usage-guide/event-option-subsequence.png)

> A common mistake: with 【随机获得1张欲望卡牌】 configured, the first option matches instead of the second — because 【随机获得1张欲望卡牌】 is a sub-sequence of 【随机获得1张欲望：控制卡牌】, so the first option counts as a "hit". To hit the second option, use text the first option lacks. Adding the title works here: 【裹挟欲望卡牌】, where "裹挟" is the title and "欲望卡牌" is the description, hitting the second option precisely.

- **Blacklisted tasks**: some task options can repeat forever (e.g. certain stress-gaining events); blacklisted options are never picked.
- **Flash priority**: sets the pick priority when cards flash. When the screen below appears, it decides which card to take. Write "card name + card description" — incomplete text is fine as long as it distinguishes the card. Overly complete text can fail to match when OCR drops characters. Avoid symbols: 【剑雨伤害次数增加】 already matches the third flash precisely. **Note**: OCR currently drops the character "一" easily, so avoid entering it — write "一缕光芒" as "缕光芒".

![Flash priority example](../images/usage-guide/flash-priority.png)

- **Remove card list**: removal priority in the deck; full card names recommended.
- **Flash card list**: flash priority in the deck; full card names recommended.
- **Copy card list**: copy priority in the deck; full card names recommended.
- **Cards needing meditation**: cards that should re-gain their flash through meditation; full card names recommended. When a listed card lacks its "Flash priority" flash, the tool records it as needing meditation and tries to pick meditation at later rest areas.
- **Meditate above credit amount**: meditation is picked only when current credits exceed both this value and the meditation cost. When both rest and meditation are available, rest wins below 50% HP, otherwise meditation wins.
- **Equipment slot 1–3 priorities**: gear is replaced following the priority lists. Unlisted legendary gear cannot replace listed common gear; listed common gear replaces unlisted legendary gear; for unlisted gear, higher quality replaces lower quality.
- **Card-reward priority**: priority for neutral and desire cards such as Dream Frontier and equipment packs. Unlisted neutral cards are skipped.
- **Farm specific flash on first floor**: farms the first entry of "Flash priority" by default and can farm god-tier flashes; if it does not drop on the first floor, the tool escapes and retries automatically. Example: to farm the cost-reduction god flash of the Jester's "Demon Dice", set the first "Flash priority" entry to 【恶魔骰子此卡费用减少】.
- **Farm empty slots**: farms empty slots for a member; see the [Naga empty-slot config](https://pd.qq.com/s/cnchz38cl) for a reference. Keep the "Farm starting card" config empty while this is on.
- **Prefer gold for healing**: when on, breakdowns are healed with gold; when off, travel passes are used first.
- **Treat breakdowns**: whether broken-down members visit the trauma center.
- **Prefer removing basic cards**: when every card in "Remove card list" is gone, the farming member's basic cards are removed first; otherwise removal is skipped.
- **Enter shop**: whether to enter shops to remove cards and buy goods.
- **Designated mask card**: mask card selection on the Fantasy Theater map. No need for the full card text — key fields that distinguish the cards are enough.
- **Mask card engraving**: picks the mask card engraving. Partial text of the wanted engraving is enough; only one engraving can be farmed for now.
- **Farm starting card**: after configuring a card name, the first event's "legendary card pick-1-of-3" is refreshed until the configured card appears, e.g. "Dream Frontier".
- **First floor only**: enable when farming materials to clear Chaos materials faster.
- **Route priority**: usually needs no changes. The tool picks the route with the most events or most rest areas following the configured order; material farmers can adjust it, e.g. moving elite nodes earlier.
- **Stop after N rounds (0 = never)**: sets how many Chaos rounds to farm.
- **Auto-pause before floor boss**: auto-pauses before a boss; rarely needed.

### Sortie Mode Config

- **Config actions**: the tool supports **Import Config Code**, **Export Config Code**, **Hot Configs**, **Save Config**, and **Switch Config**. Hot configs are uploaded automatically by tool users. If you do not want to upload anything, disable uploading in the tool settings; hot configs become unavailable after that.
- **Game Language**: Simplified Chinese for the CN server, Traditional Chinese for the international server.
- **Sortie member priority**: picks who leads the sortie. Usually one battle member is enough, but OCR can misread names, so multiple names are allowed. Example: 【九】 ("Nine") may be recognized as 【力】, so configure both variants.
- **Member priority**: teammate priority; multiple names allowed with strict matching — use full names.
- **Claim rewards**: when on, sortie rewards are claimed with "brains" first; after brains run out, stamina is consumed; after stamina runs out, the toggle switches itself off and Sortie farming continues.
- **Card-play priority**: Auto Battle play priority.
- **Card-gain priority**: card pick priority for post-battle card-gain events. If no configured card matches, the pick is skipped.
- **Remove card list**: removal priority in the deck; full card names recommended.
- **Flash card list**: flash priority in the deck; full card names recommended.
- **Copy card list**: copy priority in the deck; full card names recommended.
- **Equipment slot 1–3 priorities**: gear is replaced following the priority lists. Unlisted legendary gear cannot replace listed common gear; listed common gear replaces unlisted legendary gear; for unlisted gear, higher quality replaces lower quality.
- **First floor only**: on by default — escapes automatically after the first-floor boss and reward claim.
- **Enter shop**: whether to enter shops to remove cards and buy goods.
- **Prefer removing basic cards**: when every card in "Remove card list" is gone, the farming member's basic cards are removed first; otherwise removal is skipped.
- **Stop after N rounds (0 = never)**: sets how many Sortie rounds to farm.
- **Card-reward priority**: priority for neutral card pick events; no match means skip.
- **Discard card priority**: priority for in-battle discard events such as Adagio.
- **Task priority**: event option priority. You can enter any partial fields from the title or body, but all fields must follow the original text order, with no symbols between the title and body. Key fields are enough — overly complete text can fail to match when OCR drops characters.
- **Blacklisted tasks**: Sortie Mode demands high win rates, so options like curse cards and stress gain are usually blacklisted.
- **Blacklisted members**: teammates to blacklist. Some members' cards may be unsupported, or some teammates may fail too often — blacklist them here.
- **HP threshold for flash priority (percent)**: rest areas offer flash or rest; the tool adjusts the pick by HP percentage.
- **Route priority**: usually needs no changes — the tool plans the best route automatically.
- **Auto-pause before floor boss**: rarely needed. Pause before a boss and take over manually for better boss win rates.

## Tool Community

The tool's official community is the [QQ channel](https://pd.qq.com/s/eopggnxcu), also searchable by channel ID `pd66522118`, or scan the QR code below with QQ. The QQ channel posts tool update news, and users can share Chaos Mode and Sortie Mode configs there.

![QQ channel QR code](../images/usage-guide/qq-channel-qr-code.png)

![QQ channel](../images/usage-guide/qq-channel.png)

### Importing a Community Config Code

For a post like the one below: expand the post and copy the full config code, then click "Import Config Code" for the matching mode. The popup dialog auto-fills the latest clipboard content — click OK to import the config.

![Community config post](../images/usage-guide/config-post.png)

![Copy the full config code](../images/usage-guide/config-code.png)

The channel encourages users to post their configs, chat about the game, and suggest tool improvements.
