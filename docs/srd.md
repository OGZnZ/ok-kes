# ok-kes Software Requirements Document (SRD)

## 1. Project Overview

ok-kes is a Chaos Zero Nightmare automation assistant built on the ok-py framework. It recognizes the game screen via OCR and simulates clicks/key presses to automate in-game features.

### 1.1 Project Positioning
- Target users: Chaos Zero Nightmare players
- Runtime: Windows 11, Python 3.12, miniconda3/oknikke environment
- Framework dependency: ok-script (a PySide6-based GUI automation framework)

### 1.2 Tech Stack

| Component | Technology |
|------|---------|
| GUI framework | ok-script (PySide6 + qfluentwidgets) |
| OCR | onnxocr-ppocrv5 |
| Traditional/Simplified conversion | OpenCC |
| Image processing | OpenCV + OpenVINO |
| Cloud storage | Supabase (PostgreSQL + REST API) |
| Version control | Git + GitHub |

---

## 2. Feature Modules

### 2.1 Auto Chaos Mode (ChaosMode)

**Files**: `ok_tasks/ChaosMode.py`, `ok_tasks/utils_chaos.py`

#### 2.1.1 Overview
Automatically runs Chaos Mode stages in the game, handling the full flow of battles, route selection, card operations, and more.

#### 2.1.2 Core Logic
The `run()` method triggers once per second:
1. OCR recognizes the current screen text; Traditional Chinese is converted to Simplified
2. About 50 page-handler functions are tried in order (the `PAGE_HANDLERS` list)
3. When a page matches, the corresponding action runs and the round ends

#### 2.1.3 Page-Handler Categories

| Category | Example functions | Purpose |
|------|----------|------|
| Generic actions | `handle_confirm`, `handle_next_step` | Click generic buttons such as Confirm and Next Step |
| Battle | `handle_battle_auto_check` | Check the Auto Battle toggle and hand card count |
| Route selection | `handle_route_selection` | Recognize node types by priority and pick a route |
| Card operations | `handle_select_card`, `handle_remove`, `handle_flash` | Remove/flash/copy cards |
| Shop | `handle_shop` | Buy cards at Derang Shop |
| Rest | `handle_rest` | Free rest recovery |
| Events | `handle_event_task` | Event task selection |
| Masks | `handle_mask_card`, `handle_chaos_mask_engraving` | Mask card selection and engraving |
| Mental/trauma | `handle_mental_breakdown`, `handle_trauma_center` | Mental breakdown treatment |
| Expedition results | `handle_expedition_result` | Record wins/losses and update win-rate stats |
| Rewards | `handle_chaos_reward_claim`, `handle_chaos_reward_settlement` | Claim rewards |

#### 2.1.4 Configuration Options

| Option | Type | Default | Notes |
|--------|------|--------|------|
| Task priority | List | ["Copy","Credit gain","Remove"] | Event task selection priority |
| Blacklisted tasks | List | ["Curse cards","Stress"] | Event task filter; options whose text contains a keyword are skipped |
| Flash priority | JSON | {"Sword Rain":["Generate 2 Aurora Swords"]} | Card flash-effect priority |
| Remove card list | List | ["Sword Curtain","Sword Light",...] | Target cards for removal |
| Flash card list | List | ["Unfold Aurora","Sword Rain",...] | Target cards for flashing |
| Copy card list | List | ["Unfold Aurora","Sword Rain",...] | Target cards for copying |
| Route priority | List | ["Rest","Event","Normal enemy","Boss"] | Route node selection order |
| Prefer gold for healing | Boolean | True | Healing method at the trauma center |
| Treat breakdowns | Boolean | True | Visit the trauma center on mental breakdown |
| Prefer removing basic cards | Boolean | True | Prefer basic cards when removing |
| Enter shop | Boolean | False | Whether to enter shops along the route |
| Keep save data above TB value | Number | 62000 | Keep save data valued above this; 0 keeps everything |
| Claim rewards (verification cards only) | Boolean | False | Reward-claiming strategy |
| Designated mask card | String | "Discard up to 2 cards" | Preferred mask effect |
| Mask card engraving | String | "Total damage of own attack cards +30%" | Preferred engraving effect |
| First floor only | Boolean | False | Exit after clearing the final boss once |

---

### 2.2 Auto Sortie Mode (SortieMode)

**Files**: `ok_tasks/SortieMode.py`, `ok_tasks/utils_sortie.py`

#### 2.2.1 Overview
Automatically runs Sortie Mode stages in the game, including hand recognition and card play, battle member selection, and more.

#### 2.2.2 Core Logic
Same as ChaosMode: page handling driven by the `PAGE_HANDLERS` list.

#### 2.2.3 Highlighted Features

**Hand recognition and card play** (`handle_battle_page`):
- OCR recognizes card names in the hand area
- Key recognition (number hotkeys shown on cards)
- Stuck-card detection (if the same card stays unplayed for 3 rounds in a row, play a fallback card)
- EP energy detection (release the Ego skill at full energy)
- Frozen-frame detection and recovery

**Battle member selection** (`handle_member_selection`, `handle_battle_member_config`):
- Select battle members by priority
- Blacklist support (skip designated characters)
- Refresh candidate slots
- Pre-battle member configuration

**Card operations**:
- `handle_battle_hand_select`: In-battle hand selection
- `handle_get_card`: Priority-based selection on the card-gain page
- `handle_draw_card_event`: Draw-event selection
- `handle_discard_hand_card`: Discard hand cards
- `handle_curiosity_activate`: Nia's Curiosity card selection
- `handle_extra_card_use`: Play extra cards

**Other**:
- `handle_boss_selection`: Pick a leader at random
- `handle_rest_sortie`: Flash/rest selection at rest areas
- `handle_sortie_reward_settlement`: Reward settlement
- `handle_rational_supply`, `handle_ether_supply`: Resource refills

#### 2.2.4 Configuration Options

| Option | Type | Default | Notes |
|--------|------|--------|------|
| Route priority | List | ["Rest","Event","Normal enemy","Boss"] | Node selection order |
| Member priority | List | ["Mika","Nia",...] | Rendezvous member selection |
| Sortie member priority | List | ["Headmarie","Nine",...] | Pre-battle member configuration |
| Card-gain priority | List | ["Unfold Aurora","Sword Rain",...] | Selection when gaining cards |
| Card-play priority | List | ["Sword Rain","Source of Water",...] | In-battle play order |
| Discard card priority | List | ["Unfold Aurora",...] | Discard targets |
| Task priority | List | ["Pick 3 random fates",...] | Event task selection |
| Blacklisted tasks | List | ["Curse cards","Stress"] | Event task filter |
| Blacklisted members | List | ["Diana","Adelheid"] | Skipped characters |
| Remove/copy/flash card lists | List | ... | Targets for each card operation |
| Prefer removing basic cards | Boolean | True | Prefer basic cards when removing |
| Claim rewards | Boolean | False | Reward-claiming toggle |
| Enter shop | Boolean | False | Enter shops along the route |
| First floor only | Boolean | True | Exit after the final boss |
| HP threshold for flash priority | String | "60" | HP percentage threshold |

---

### 2.3 Config Sync & Hot Configs

**Files**: `ok_tasks/config_sync.py`, `ok_tasks/config_io.py`

#### 2.3.1 Upload Mechanism
- **Trigger**: Automatic upload check every 300 seconds (5 minutes) while a mode is running
- **Minimum rounds**: 2 (`MIN_ROUNDS = 2`, configurable)
- **Uploaded content**: config base64 + win rate + version number + game language + anonymous user hash
- **Never uploaded**: Personal identity info, game accounts, screenshots, IP addresses

#### 2.3.2 Anonymous User ID
`_get_user_hash()`: combines MAC address + host name + user name, taking the first 16 chars of the SHA256 hash.

#### 2.3.3 Cloud Storage (Supabase)

| Field | Type | Notes |
|------|------|------|
| id | BIGINT | Auto-increment primary key |
| mode | TEXT | "chaos" or "sortie" |
| config_b64 | TEXT | Base64-encoded config |
| config_ver | TEXT | Version number |
| game_lang | TEXT | Game language |
| win_rate | REAL | Win rate (0.0–1.0) |
| total_rounds | INTEGER | Total battle rounds |
| user_hash | TEXT | Anonymous user ID |
| created_at | TIMESTAMPTZ | Creation time |
| updated_at | TIMESTAMPTZ | Update time |

**Unique constraint**: `(user_hash, mode, config_b64)` — one record per user per config

#### 2.3.4 Hot Config Display
- Sort orders: by average win rate descending / by user count descending
- Display cap: 20 entries
- Shown info: rank, win rate, user count, game language, version

#### 2.3.5 Config Import & Export
- `_export_config_to_text()`: export as base64 encoding
- `_import_config_from_text()`: import from base64 (merged into the current config)
- Button behavior: all config operations live in the UI config buttons

---

### 2.4 Shared Features

#### 2.4.1 Multi-Language Support
- OpenCC (Traditional-to-Simplified) normalizes OCR text processing
- i18n implements UI translation via `.po` / `.mo` files
- Chaos Mode and Sortie Mode each configure a "Game Language" supporting Simplified and Traditional Chinese

#### 2.4.2 Card Recognition Enhancement (Sword Rain merge)
In `select_card`, if OCR recognizes "Sword Rain" as two separated single-character boxes, they are merged automatically into one `Box(name="Sword Rain")` and the old single-character boxes are removed, so later matching recognizes the card correctly.

#### 2.4.3 Frozen-Frame Detection
`is_frame_stuck()`: detects frozen frames from pixel changes (change ratio < 0.5% for 30 seconds straight), used for battle recovery and log output.

---

## 3. Architecture

### 3.1 Overall Architecture

```
main.py (entry point)
  └── ok.OK(config) ──→ GUI launch
        ├── ChaosMode (TriggerTask)
        │     └── run() → iterate utils_chaos.PAGE_HANDLERS
        ├── SortieMode (TriggerTask)
        │     └── run() → iterate utils_sortie.PAGE_HANDLERS
        └── Global config (Settings)
              └── Config upload toggle
```

### 3.2 Task Scheduling
- Inherits `ok.TriggerTask`, triggering `run()` once per second
- Each frame: OCR → Traditional-to-Simplified → try page handlers in order → return on match
- End of frame: check whether a config upload is due

### 3.3 Mutual Exclusion
- Enabling ChaosMode automatically disables SortieMode
- Enabling SortieMode automatically disables ChaosMode

### 3.4 Data Flow

```
User edits config → saved to configs/ JSON files
      ↓
Every 5 minutes → read config → base64 encode → upload to Supabase
      ↓
Hot Configs button → fetch from Supabase → aggregate → show list → user picks → import config
```

---

## 4. Configuration Overview

### 4.1 Global Config (src/config.py)

| Config group | Option | Type | Default |
|----------|--------|------|--------|
| Config upload | Upload config | Toggle | True |

### 4.2 Chaos Mode Config (18 options)

Game language, task priority, blacklisted tasks, flash priority, remove card list, flash card list, copy card list, route priority, prefer gold for healing, treat breakdowns, prefer removing basic cards, enter shop, keep save data above TB value, claim rewards (verification cards only), designated mask card, mask card engraving, first floor only, export config, import config, hot configs

### 4.3 Sortie Mode Config (20 options)

Game language, route priority, member priority, sortie member priority, card-gain priority, remove card list, copy card list, flash card list, claim rewards, card-play priority, discard card priority, enter shop, card-reward priority, task priority, blacklisted tasks, blacklisted members, prefer removing basic cards, HP threshold for flash priority, first floor only, export config, import config, hot configs

---

## 5. Environment Requirements

### 5.1 Runtime
- OS: Windows 11
- Python: 3.12 (miniconda3/oknikke)
- Game window: 16:9 resolution, minimum 1280x720, 1920x1080 recommended
- Network: optional (needed for config upload and hot configs)

### 5.2 Dependencies

```
ok-script>=1.0.163
onnxocr-ppocrv5>=0.0.18
OpenCC>=1.2.0
opencv-python>=4.12.0
openvino>=2026.0.0
requests (for config sync)
```

### 5.3 Declared OCR Library Config

```python
'ocr': {
    'lib': 'onnxocr',
    'auto_simplify': True,
    'params': {
        'use_openvino': True,
    }
}
```

### 5.4 Windows Interaction Config

```python
'interaction': ['Pynput', 'PostMessage', 'Genshin', 'PyDirect', 'ForegroundPostMessage']
'capture_method': ['WGC', 'BitBlt_RenderFull', 'BitBlt']
```

---

## 6. Version History

| Version | Date | Changes |
|------|------|----------|
| v1.3.5 | 2026-07-22 | New hot-config sync; better Sword Rain card recognition; new task blacklist; code dedup |
| v1.3.4 | - | - |
| ... | - | - |
