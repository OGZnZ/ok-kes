import base64
import json
import os

from ok import og
from ok.util.config import Config
from ok.util.file import get_relative_path, read_json_file, write_json_file


LOCAL_CONFIG_PROFILES_FILE = "local_config_profiles.json"
UI_ONLY_CONFIG_KEYS = {"配置操作"}


def refresh_task_config_widgets(task):
    """Refresh a task card's config widgets in place without deleting or rebuilding the card."""
    main_window = getattr(og, "main_window", None)
    trigger_tab = getattr(main_window, "trigger_tab", None)
    if trigger_tab is None:
        return

    for task_card in getattr(trigger_tab, "card_widgets", []):
        if getattr(task_card, "task", None) is not task:
            continue
        for widget in getattr(task_card, "config_widgets", []):
            update_value = getattr(widget, "update_value", None)
            if callable(update_value):
                update_value()
        apply_visibility = getattr(
            task_card,
            "_ConfigContentMixin__apply_sub_config_visibility",
            None,
        )
        if callable(apply_visibility):
            apply_visibility()
        adjust_size = getattr(task_card, "_adjust_config_content_size", None)
        if callable(adjust_size):
            adjust_size()
        break


def _migrate_flash_priority(data):
    """Convert the legacy flash-priority JSON string into an order-matched list."""
    value = data.get("闪光优先级")
    if not isinstance(value, str):
        return data
    try:
        old_priority = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        data["闪光优先级"] = []
        return data
    if not isinstance(old_priority, dict):
        data["闪光优先级"] = []
        return data
    data["闪光优先级"] = [
        f"{card_name}：{description}"
        for card_name, descriptions in old_priority.items()
        if isinstance(card_name, str)
        for description in (
            descriptions if isinstance(descriptions, (list, tuple)) else []
        )
        if isinstance(description, str) and description
    ]
    return data


def migrate_flash_priority_config_file(task):
    """Migrate the local legacy config file before the framework validates types against defaults."""
    config_file = get_relative_path(
        Config.config_folder,
        f"{task.__class__.__name__}.json",
    )
    data = read_json_file(config_file)
    if not isinstance(data, dict) or not isinstance(data.get("闪光优先级"), str):
        return
    _migrate_flash_priority(data)
    write_json_file(config_file, data)


def migrate_game_language_config_file(task):
    """Migrate the legacy global game language into the current mode config, runs only once."""
    config_file = get_relative_path(
        Config.config_folder,
        f"{task.__class__.__name__}.json",
    )
    data = read_json_file(config_file)
    if not isinstance(data, dict):
        data = {}
    if "游戏语言" in data:
        return

    legacy_config_file = get_relative_path(Config.config_folder, "游戏语言.json")
    legacy_data = read_json_file(legacy_config_file)
    game_language = "简体中文"
    if isinstance(legacy_data, dict):
        legacy_language = legacy_data.get("游戏语言")
        if legacy_language in {"简体中文", "繁体中文"}:
            game_language = legacy_language
    data["游戏语言"] = game_language
    write_json_file(config_file, data)


def _export_config_to_text(task):
    """Export the task's user config as base64-encoded text."""
    config_file = task.config.config_file
    if not os.path.exists(config_file):
        task.log_info("Config file does not exist, cannot export")
        return None
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        task.log_info(f"Failed to read config file: {e}")
        return None
    # Keep only user config entries (drop internal state starting with _)
    clean = {
        k: v
        for k, v in data.items()
        if not k.startswith('_') and k not in UI_ONLY_CONFIG_KEYS
    }
    if "游戏语言" in getattr(task, "default_config", {}):
        clean["游戏语言"] = task.config.get(
            "游戏语言",
            task.default_config["游戏语言"],
        )
    json_str = json.dumps(clean, ensure_ascii=False, separators=(',', ':'))
    encoded = base64.b64encode(json_str.encode('utf-8')).decode('ascii')
    return encoded


def _import_config_from_text(task, encoded_text):
    """Import config from base64-encoded text into the task config file."""
    try:
        json_str = base64.b64decode(encoded_text.encode('ascii')).decode('utf-8')
        data = json.loads(json_str)
    except Exception as e:
        task.log_info(f"Decode failed, invalid config code: {e}")
        return False
    if not isinstance(data, dict):
        task.log_info("Invalid config data format")
        return False
    _migrate_flash_priority(data)

    # Legacy shared configs may contain fields removed in the current version. ConfigCard
    # resolves widget types from default_config, so deprecated fields without defaults parse as None.
    allowed_config = getattr(task, "default_config", {})
    ignored_keys = []
    sanitized_data = {}
    for key, value in data.items():
        if key not in allowed_config or key in UI_ONLY_CONFIG_KEYS:
            ignored_keys.append(key)
            continue
        default_value = allowed_config[key]
        if type(value) is not type(default_value):
            ignored_keys.append(key)
            continue
        sanitized_data[key] = value
    if ignored_keys:
        task.log_info(f"Ignored invalid or deprecated fields during import: {', '.join(ignored_keys)}")
    data = sanitized_data

    # Write the config file
    config_file = task.config.config_file
    try:
        # Merge: keep internal state starting with _, overwrite user config
        existing = {}
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
            except Exception:
                pass
        existing = {
            key: value
            for key, value in existing.items()
            if (key.startswith('_') or key in allowed_config)
            and key not in UI_ONLY_CONFIG_KEYS
        }
        for k, v in data.items():
            existing[k] = v
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        # Refresh the task.config cache
        for key in list(task.config):
            if not key.startswith('_') and key not in allowed_config:
                dict.pop(task.config, key, None)
        task.config.update(data)
        return True
    except Exception as e:
        task.log_info(f"Failed to write config file: {e}")
        return False


def make_export_callback(task):
    """Build the export-config button callback."""
    def export():
        from PySide6.QtWidgets import QMessageBox, QApplication
        encoded = _export_config_to_text(task)
        if encoded is None:
            QMessageBox.warning(None, "Export Failed", "Config file is missing or cannot be read")
            return
        # Copy to clipboard
        QApplication.clipboard().setText(encoded)
        QMessageBox.information(
            None, "Export Successful",
            "Config copied to clipboard, paste it to share with others.\n\n"
            f"(code length: {len(encoded)} chars)"
        )
        task.log_info(f"Config exported, {len(encoded)} chars total")
    return export


def make_import_callback(task):
    """Build the import-config button callback."""
    def import_config():
        from PySide6.QtWidgets import QInputDialog, QMessageBox, QApplication
        # Try prefilling with clipboard text
        clipboard_text = QApplication.clipboard().text()
        text, ok = QInputDialog.getMultiLineText(
            None, "Import Config", "Paste the config code shared by others:",
            clipboard_text if clipboard_text else ""
        )
        if not ok or not text.strip():
            return
        text = text.strip()
        success = _import_config_from_text(task, text)
        if success:
            QMessageBox.information(None, "Import Successful", "Config imported and applied!")
            task.log_info("Config imported successfully")
            refresh_task_config_widgets(task)
        else:
            QMessageBox.warning(None, "Import Failed", "Invalid code or write failure, please check and retry.")
    return import_config


def _local_profiles_file():
    """Return the local profile storage path, independent of task config files."""
    return get_relative_path(Config.config_folder, LOCAL_CONFIG_PROFILES_FILE)


def _read_local_profiles(task):
    """Read all local config profiles; return an empty structure when the file is corrupt."""
    data = read_json_file(_local_profiles_file())
    if isinstance(data, dict):
        return data
    if data is not None:
        task.log_info("Local config profile file is invalid, treating as empty")
    return {}


def _write_local_profiles(task, data):
    """Write all local config profiles."""
    try:
        write_json_file(_local_profiles_file(), data)
        return True
    except Exception as exc:
        task.log_info(f"Failed to write local config profiles: {exc}")
        return False


def _current_config_snapshot(task):
    """Snapshot all effective configs of the current mode, excluding framework-internal fields."""
    snapshot = {}
    for key, default_value in getattr(task, "default_config", {}).items():
        if key.startswith("_") or key in UI_ONLY_CONFIG_KEYS:
            continue
        value = task.config.get(key, default_value)
        # All configs are JSON types; round-trip through serialization for an
        # independent copy so lists cannot be mutated afterwards.
        snapshot[key] = json.loads(json.dumps(value, ensure_ascii=False))
    return snapshot


def _game_language(task):
    """Get the game language currently selected by the user."""
    try:
        return str(task.config.get("游戏语言", "简体中文")).strip() or "简体中文"
    except Exception:
        return "简体中文"


def _app_version():
    """Get the current app version for generating default profile names."""
    try:
        configured_version = (og.config or {}).get("version")
        if configured_version:
            return str(configured_version).strip()
    except Exception:
        pass
    try:
        from src.config import version
        return str(version).strip() or "dev"
    except Exception:
        return "dev"


def _default_local_profile_name(task, mode):
    """Generate a default profile name from mode, member, language and version."""
    if mode == "chaos":
        member_name = str(task.config.get("刷存档主战员", "")).strip()
    else:
        members = task.config.get("出战主战员优先级", [])
        member_name = str(members[0]).strip() if isinstance(members, list) and members else ""
    member_name = member_name or "Unspecified member"
    return f"{member_name}-{_game_language(task)}-{_app_version()}"


def _apply_local_profile(task, profile):
    """Load a local profile reusing the import config validation, persistence and cache refresh."""
    encoded = base64.b64encode(
        json.dumps(profile, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return _import_config_from_text(task, encoded)


def make_save_local_config_callback(task, mode):
    """Build the save-local-config-profile button callback."""
    def save_local_config():
        from PySide6.QtWidgets import QInputDialog, QMessageBox

        default_name = _default_local_profile_name(task, mode)
        proposed_name = default_name
        while True:
            entered_name, accepted = QInputDialog.getText(
                None,
                "Save Config",
                "Enter a name for the local config:",
                text=proposed_name,
            )
            if not accepted:
                return
            profile_name = entered_name.strip() or default_name

            all_profiles = _read_local_profiles(task)
            mode_profiles = all_profiles.get(mode)
            if not isinstance(mode_profiles, dict):
                mode_profiles = {}

            if profile_name in mode_profiles:
                reply = QMessageBox.question(
                    None,
                    "Duplicate Config Name",
                    f"Local config \"{profile_name}\" already exists.\n\n"
                    "Choose \"Yes\" to overwrite it, \"No\" to rename.",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                    QMessageBox.No,
                )
                if reply == QMessageBox.Cancel:
                    return
                if reply == QMessageBox.No:
                    proposed_name = profile_name
                    continue

            mode_profiles[profile_name] = _current_config_snapshot(task)
            all_profiles[mode] = mode_profiles
            if _write_local_profiles(task, all_profiles):
                QMessageBox.information(
                    None,
                    "Save Successful",
                    f"Current config saved as \"{profile_name}\".",
                )
                task.log_info(f"Local config saved: {profile_name}")
            else:
                QMessageBox.warning(None, "Save Failed", "Failed to write the local config file.")
            return

    return save_local_config


def make_switch_local_config_callback(task, mode):
    """Build the load/delete-local-config-profile button callback."""
    def switch_local_config():
        from PySide6.QtWidgets import (
            QDialog,
            QHBoxLayout,
            QListWidget,
            QListWidgetItem,
            QMessageBox,
            QPushButton,
            QVBoxLayout,
        )

        dialog = QDialog()
        dialog.setWindowTitle("Switch Config")
        dialog.resize(480, 360)
        layout = QVBoxLayout(dialog)
        profile_list = QListWidget()
        layout.addWidget(profile_list)

        button_layout = QHBoxLayout()
        load_button = QPushButton("Load Selected Config")
        delete_button = QPushButton("Delete Selected Config")
        cancel_button = QPushButton("Cancel")
        load_button.setEnabled(False)
        delete_button.setEnabled(False)
        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(delete_button)
        button_layout.addWidget(load_button)
        layout.addLayout(button_layout)

        def reload_profile_list():
            profile_list.clear()
            mode_profiles = _read_local_profiles(task).get(mode, {})
            if not isinstance(mode_profiles, dict):
                return
            for profile_name in mode_profiles:
                profile_list.addItem(QListWidgetItem(profile_name))

        def selected_profile_name():
            selected_items = profile_list.selectedItems()
            return selected_items[0].text() if selected_items else ""

        def update_button_state():
            has_selection = bool(selected_profile_name())
            load_button.setEnabled(has_selection)
            delete_button.setEnabled(has_selection)

        def load_selected_profile():
            profile_name = selected_profile_name()
            if not profile_name:
                return
            mode_profiles = _read_local_profiles(task).get(mode, {})
            profile = mode_profiles.get(profile_name) if isinstance(mode_profiles, dict) else None
            if not isinstance(profile, dict):
                QMessageBox.warning(dialog, "Load Failed", "The selected local config does not exist or is invalid.")
                reload_profile_list()
                return
            if _apply_local_profile(task, profile):
                refresh_task_config_widgets(task)
                QMessageBox.information(dialog, "Load Successful", f"Loaded \"{profile_name}\".")
                task.log_info(f"Local config loaded: {profile_name}")
                dialog.accept()
            else:
                QMessageBox.warning(dialog, "Load Failed", "Failed to write the local config.")

        def delete_selected_profile():
            profile_name = selected_profile_name()
            if not profile_name:
                return
            reply = QMessageBox.question(
                dialog,
                "Confirm Delete",
                f"Delete local config \"{profile_name}\"?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            all_profiles = _read_local_profiles(task)
            mode_profiles = all_profiles.get(mode, {})
            if isinstance(mode_profiles, dict):
                mode_profiles.pop(profile_name, None)
                all_profiles[mode] = mode_profiles
            if _write_local_profiles(task, all_profiles):
                task.log_info(f"Deleted local config: {profile_name}")
                reload_profile_list()
                update_button_state()
            else:
                QMessageBox.warning(dialog, "Delete Failed", "Failed to write the local config file.")

        profile_list.itemSelectionChanged.connect(update_button_state)
        profile_list.itemDoubleClicked.connect(lambda _item: load_selected_profile())
        load_button.clicked.connect(load_selected_profile)
        delete_button.clicked.connect(delete_selected_profile)
        cancel_button.clicked.connect(dialog.reject)
        reload_profile_list()
        dialog.exec_()

    return switch_local_config
