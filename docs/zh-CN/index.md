# ok-kes

![ok-kes icon](https://raw.githubusercontent.com/baoxin1100/ok-kes/master/icons/icon.png){ .hero-logo }

An image-recognition-based automation assistant for Chaos Zero Nightmare, with background mode support. The tool simulates user actions through Windows APIs — it never reads game memory and never modifies game files.

!!! warning "Please Note"
    This project is open-source and free, intended for personal learning and communication only. Users must understand and accept the risks of third-party automation tools on their own.

## Quick Start

1. Go to [GitHub Releases](https://github.com/baoxin1100/ok-kes/releases) and download the latest `ok-kes-win32-portable-v*.exe`; do not download the Source Code archive.
2. Run the program as administrator.
3. International server players: set "Game Language" to Traditional Chinese in the automation mode you use.
4. Enable Auto Chaos Mode, Auto Sortie Mode, or Semi-Auto Story Mode as needed.

## Main Features

### Auto Chaos Mode

- Auto handle routes, events, battles, rest areas, shops, and reward settlement.
- Manage card acquisition, removal, copying, and flashing per your configuration.
- Support equipment selection, target members, mask cards, and save-data flows.
- Support config import, export, and hot configs.

### Auto Sortie Mode

- Auto Battle and play cards by card priority.
- Auto select battle members, cards, and route nodes.
- Auto handle rest areas, shops, supply refills, and reward settlement.

### Semi-Auto Story Mode

- Auto advance dialogues and view events.
- When hitting battles or chaos stages, manually switch to the matching automation mode.

## Requirements

- Windows with the game running at a 16:9 resolution.
- 1920×1080 recommended; 1600×900 and 1280×720 also supported.
- Disable GPU filters, sharpening, and monitoring overlays drawn over the game screen.
- Chaos Mode requires auto-battle and auto-story to be enabled in the game.
- Auto Battle depends on hotkey recognition; show hotkeys in the game settings.

## FAQ

### The tool cannot recognize the game screen

Check that the game language is configured correctly, and disable GPU filters, HDR enhancement, sharpening, and screen overlays. The game must stay at a supported 16:9 resolution.

### Program files get blocked or deleted

Add the program directory to the exclusions of Windows Defender or your antivirus software, then re-download the full program.

### How to share configs

Use "Export Config" on the mode config page to copy the config text; other users can apply it via "Import Config". You can also use hot configs after enabling config upload.

## Community & Feedback

- QQ Group: `901988096` (Join answer: `烟火焰`)
- [QQ Channel](https://pd.qq.com/s/eopggnxcu)
- [GitHub Issues](https://github.com/baoxin1100/ok-kes/issues)

Developers can continue with the [development guide](../development/index.md) and [software requirements and design](../srd.md).
