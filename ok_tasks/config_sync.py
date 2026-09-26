"""
Config sync module: anonymous Supabase upload/download of hot configs.

Features:
1. Auto-upload anonymous config + win rate to Supabase every 5 minutes
2. Fetch the hot config list (sorted by win rate or user count)
3. Apply a hot config locally

Uploads no personal info, only:
- base64-encoded config
- win-rate statistics
- config version
- anonymous user id (hash of machine traits)
"""
import os
import hashlib
import platform
import uuid

import requests
from ok import TriggerTask
from config_io import (
    _import_config_from_text,
    _export_config_to_text,
    refresh_task_config_widgets,
)

# Supabase config
SUPABASE_URL = "https://curzwmogotwmltaprmin.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_9Kn7mcglnMHGPEkJbxZhuA_erescsdk"
TABLE_NAME = "configs"

# Upload interval (seconds)
UPLOAD_INTERVAL = 300  # 5 minutes

# Minimum runs for valid data (raise later once there are more users)
MIN_ROUNDS = 5
SUPPORTED_GAME_LANGUAGES = ("简体中文", "繁体中文")


def _get_version():
    """Read the current version from src/config.py."""
    try:
        from src.config import version
        return version
    except Exception:
        return "dev"


def _get_user_hash() -> str:
    """Generate an anonymous user id: a one-time hash of machine traits.

    Combines MAC address, host name and user name, taking the first 16 hex
    chars of SHA256 as the user id. Cached after startup so one machine
    keeps the same id.
    """
    if not hasattr(_get_user_hash, '_cache'):
        try:
            import subprocess
            result = subprocess.run(['getmac'], capture_output=True, text=True, shell=True)
            mac_line = result.stdout.split('\n')[0] if result.stdout else ''
            mac = mac_line.split()[0] if mac_line else str(uuid.getnode())
        except Exception:
            mac = str(uuid.getnode())
        raw = f"{mac}|{platform.node()}|{os.environ.get('USERNAME', 'unknown')}"
        _get_user_hash._cache = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return _get_user_hash._cache


def _get_win_rate(task: TriggerTask) -> float:
    """Read the current win rate from task.node_status."""
    ns = getattr(task, 'node_status', None)
    if not ns:
        return 0.0
    total = ns.get('total_rounds', 0)
    success = ns.get('success_rounds', 0)
    if total < MIN_ROUNDS:
        return -1.0  # not enough data
    return success / total if total > 0 else 0.0


def _should_upload(task: TriggerTask) -> bool:
    """Check upload conditions:
    1. Global config "Upload Config Info" is True
    2. Enough battle runs recorded
    """
    try:
        lang_config = task.executor.global_config.get_config('Upload Config') or task.executor.global_config.get_config('配置上传')
        enabled = lang_config.get('Upload Config Info', lang_config.get('是否上传配置', True)) if lang_config else True
    except Exception:
        enabled = True
    win_rate = _get_win_rate(task)
    if win_rate < 0:
        task.log_debug(f"[Config Sync] Fewer than {MIN_ROUNDS} runs, skipping upload")
        return False
    return bool(enabled)


def upload_config(task: TriggerTask, mode: str) -> bool:
    """Upload the current config to Supabase.

    Args:
        task: TriggerTask instance
        mode: "chaos" or "sortie"

    Returns:
        bool: whether the upload succeeded
    """
    if not _should_upload(task):
        return False

    config_b64 = _export_config_to_text(task)
    if not config_b64:
        return False

    win_rate = _get_win_rate(task)
    if win_rate < 0:
        return False

    ns = getattr(task, 'node_status', {})
    total_rounds = ns.get('total_rounds', 0)

    user_hash = _get_user_hash()
    config_ver = _get_version()

    # Read the game language of the current mode config
    game_lang = str(task.config.get('游戏语言', '简体中文')).strip() or '简体中文'

    # Sortie Mode records the first lead member, Chaos Mode records the save-farming member
    first_member = ""
    if mode == "sortie":
        try:
            member_list = task.config.get('出战主战员优先级', [])
            if isinstance(member_list, (list, tuple)) and len(member_list) > 0:
                first_member = str(member_list[0]).strip()
        except Exception:
            pass
    elif mode == "chaos":
        try:
            first_member = str(task.config.get('刷存档主战员', '') or '').strip()
        except Exception:
            pass

    payload = {
        "mode": mode,
        "config_b64": config_b64,
        "config_ver": config_ver,
        "game_lang": game_lang,
        "first_member": first_member,
        "win_rate": round(win_rate, 4),
        "total_rounds": total_rounds,
        "user_hash": user_hash,
    }

    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }

    try:
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}",
            json=payload,
            headers=headers,
            timeout=10,
        )
        if resp.status_code in (200, 201, 204):
            task.log_debug(f"[Config Sync] Upload succeeded (mode={mode}, win_rate={win_rate:.1%})")
            return True
        else:
            task.log_info(f"[Config Sync] Upload failed: HTTP {resp.status_code} {resp.text[:200]}")
            return False
    except requests.RequestException as e:
        task.log_info(f"[Config Sync] Upload error: {e}")
        return False


def fetch_popular_configs(
    mode: str,
    sort_by: str = "winrate",
    limit: int = 20,
    version: str = None,
) -> list:
    """Fetch the hot config list from Supabase.

    Args:
        mode: "chaos" or "sortie"
        sort_by: "winrate" (avg win rate desc) or "users" (user count desc)
        limit: number of entries to return
        version: optional config version filter

    Returns:
        list[dict]: each entry holds config_b64, avg_win_rate, user_count, etc.
    """
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    }

    # Fetch per language so global win-rate truncation cannot wipe out smaller languages
    base_params = {
        "select": "config_b64,config_ver,game_lang,first_member,win_rate,total_rounds,user_hash",
        "mode": f"eq.{mode}",
        "total_rounds": f"gte.{MIN_ROUNDS}",
        "order": "win_rate.desc",
        "limit": limit,
    }
    if version:
        base_params["config_ver"] = f"eq.{version}"

    records = []
    try:
        for game_lang in SUPPORTED_GAME_LANGUAGES:
            params = dict(base_params)
            params["game_lang"] = f"eq.{game_lang}"
            resp = requests.get(
                f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}",
                headers=headers,
                params=params,
                timeout=10,
            )
            if resp.status_code != 200:
                continue
            records.extend(resp.json())
    except requests.RequestException:
        return []

    if not records:
        return []

    # Aggregate identical configs per game language so Simplified and Traditional data don't overwrite each other
    groups = {}
    for r in records:
        game_lang = r.get("game_lang") or "简体中文"
        key = (r["config_b64"], game_lang)
        if key not in groups:
            groups[key] = {
                "config_b64": r["config_b64"],
                "config_ver": r.get("config_ver", "unknown"),
                "game_lang": game_lang,
                "first_member": r.get("first_member", ""),
                "win_rates": [],
                "users": set(),
            }
        groups[key]["win_rates"].append(r["win_rate"])
        groups[key]["users"].add(r["user_hash"])

    # Compute aggregated results
    result = []
    for key, g in groups.items():
        user_count = len(g["users"])
        if user_count < 1:
            continue
        result.append({
            "config_b64": g["config_b64"],
            "config_ver": g["config_ver"],
            "game_lang": g["game_lang"],
            "first_member": g["first_member"],
            "avg_win_rate": round(sum(g["win_rates"]) / len(g["win_rates"]), 4),
            "user_count": user_count,
            "total_submissions": len(g["win_rates"]),
        })

    # Sort
    if sort_by == "users":
        result.sort(key=lambda x: (-x["user_count"], -x["avg_win_rate"]))
    else:  # winrate
        result.sort(key=lambda x: (-x["avg_win_rate"], -x["user_count"]))

    # Keep limit entries per language so the final sort cannot drop smaller languages again
    language_counts = {}
    limited_result = []
    for r in result:
        game_lang = r.get("game_lang", "简体中文")
        count = language_counts.get(game_lang, 0)
        if count >= limit:
            continue
        language_counts[game_lang] = count + 1
        limited_result.append(r)

    return limited_result


def check_upload_disabled_and_warn(task: TriggerTask) -> bool:
    """Warn when config upload is disabled; return True in that case."""
    try:
        lang_config = task.executor.global_config.get_config('Upload Config') or task.executor.global_config.get_config('配置上传')
        upload_enabled = lang_config.get('Upload Config Info', lang_config.get('是否上传配置', True)) if lang_config else True
    except Exception:
        upload_enabled = True
    if not upload_enabled:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(
            None, "Hot Configs Unavailable",
            "Enable \"Upload Config\" in the settings page at the bottom left first to use Hot Configs.\n\n"
            "Once enabled, you can browse and download configs shared by high-win-rate players."
        )
        return True
    return False


def check_upload_if_needed(task: TriggerTask, mode: str):
    """Auto-upload the config every UPLOAD_INTERVAL seconds."""
    import time
    now = time.time()
    if now - getattr(task, '_last_upload_time', 0) >= UPLOAD_INTERVAL:
        task._last_upload_time = now
        upload_config(task, mode)


def show_hot_configs_dialog(task: TriggerTask, mode: str):
    """Pop up the hot config picker dialog.

    Args:
        task: TriggerTask instance
        mode: "chaos" or "sortie"
    """
    from PySide6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
        QListWidgetItem, QPushButton, QMessageBox, QComboBox, QApplication,
    )
    from PySide6.QtCore import Qt

    if check_upload_disabled_and_warn(task):
        return

    mode_name = "Chaos Mode" if mode == "chaos" else "Sortie Mode"
    dialog = QDialog()
    dialog.setWindowTitle(f"Hot Configs - {mode_name}")
    dialog.resize(650, 500)

    layout = QVBoxLayout(dialog)

    # Filter row: sort order + lead member filter
    filter_layout = QHBoxLayout()
    sort_label = QLabel("Sort by:")
    sort_combo = QComboBox()
    sort_combo.addItem("Win rate (desc)", "winrate")
    sort_combo.addItem("User count (desc)", "users")
    filter_layout.addWidget(sort_label)
    filter_layout.addWidget(sort_combo)

    # Language filter
    lang_filter_label = QLabel("Language:")
    lang_filter_combo = QComboBox()
    lang_filter_combo.addItem("All", "")
    filter_layout.addWidget(lang_filter_label)
    filter_layout.addWidget(lang_filter_combo)

    # Member filter: first lead member for Sortie Mode, save-farming member for Chaos Mode
    member_filter_label = QLabel(
        "Lead Member:" if mode == "sortie" else "Save-farming Member:"
    )
    member_filter_combo = QComboBox()
    member_filter_combo.addItem("All", "")
    filter_layout.addWidget(member_filter_label)
    filter_layout.addWidget(member_filter_combo)

    filter_layout.addStretch()
    layout.addLayout(filter_layout)

    # Loading hint
    loading_label = QLabel("Loading hot configs, please wait...")
    loading_label.setStyleSheet("color: gray; padding: 20px;")
    loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(loading_label)

    # List
    config_list = QListWidget()
    config_list.setVisible(False)
    layout.addWidget(config_list)

    # Buttons
    btn_layout = QHBoxLayout()
    refresh_btn = QPushButton("Refresh")
    apply_btn = QPushButton("Apply Selected Config")
    apply_btn.setEnabled(False)
    cancel_btn = QPushButton("Cancel")
    btn_layout.addWidget(refresh_btn)
    btn_layout.addStretch()
    btn_layout.addWidget(apply_btn)
    btn_layout.addWidget(cancel_btn)
    layout.addLayout(btn_layout)

    # Cache all results
    all_results = []

    def load_configs():
        nonlocal all_results
        sort_by = sort_combo.currentData()
        all_results = fetch_popular_configs(mode=mode, sort_by=sort_by, limit=200)
        # Refresh language filter options
        current_lang = lang_filter_combo.currentData() or ""
        lang_filter_combo.blockSignals(True)
        lang_filter_combo.clear()
        lang_filter_combo.addItem("All", "")
        langs = sorted(set(r.get("game_lang", "简体中文") for r in all_results if r.get("game_lang")))
        for lang in langs:
            lang_filter_combo.addItem(lang, lang)
        idx = lang_filter_combo.findData(current_lang)
        if idx >= 0:
            lang_filter_combo.setCurrentIndex(idx)
        lang_filter_combo.blockSignals(False)
        # Refresh member filter options
        if member_filter_combo is not None:
            current_member = member_filter_combo.currentData() or ""
            member_filter_combo.blockSignals(True)
            member_filter_combo.clear()
            member_filter_combo.addItem("All", "")
            members = sorted(set(r.get("first_member", "") for r in all_results if r.get("first_member")))
            for m in members:
                member_filter_combo.addItem(m, m)
            # Restore the previous filter selection
            idx = member_filter_combo.findData(current_member)
            if idx >= 0:
                member_filter_combo.setCurrentIndex(idx)
            member_filter_combo.blockSignals(False)
        apply_filters()

    def apply_filters():
        filtered = all_results
        # Language filter
        selected_lang = lang_filter_combo.currentData()
        if selected_lang:
            filtered = [r for r in filtered if r.get("game_lang", "简体中文") == selected_lang]
        # Member filter
        selected_member = member_filter_combo.currentData() if member_filter_combo else ""
        if selected_member:
            filtered = [r for r in filtered if r.get("first_member", "") == selected_member]
        config_list.clear()
        loading_label.setVisible(False)
        if not filtered:
            item = QListWidgetItem("No hot config data yet (at least 5 valid runs are required)")
            config_list.addItem(item)
            return
        for i, r in enumerate(filtered[:20], 1):
            wr = r["avg_win_rate"]
            uc = r["user_count"]
            ver = r.get("config_ver", "?")
            gl = r.get("game_lang", "简体中文")
            fm = r.get("first_member", "")
            if fm:
                member_label = "Member" if mode == "sortie" else "Save-farming member"
                text = f"#{i}  Win rate: {wr:.0%}  Users: {uc}  {member_label}: {fm}  Language: {gl}  Version: {ver}"
            else:
                text = f"#{i}  Win rate: {wr:.0%}  Users: {uc}  Language: {gl}  Version: {ver}"
            item = QListWidgetItem(text)
            item.setData(0x100, r)  # 36 = Qt.UserRole
            config_list.addItem(item)

    def on_filter_changed():
        loading_label.setVisible(True)
        config_list.setVisible(False)
        load_configs()
        config_list.setVisible(True)

    def on_apply():
        selected = config_list.selectedItems()
        if not selected:
            return
        r = selected[0].data(0x100)
        if not r:
            return
        reply = QMessageBox.question(
            dialog, "Confirm Apply",
            f"Apply the selected config (win rate: {r['avg_win_rate']:.0%}, users: {r['user_count']})\nThe current config will be overwritten.\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            success = _import_config_from_text(task, r["config_b64"])
            if success:
                QMessageBox.information(dialog, "Import Successful", "Hot config applied!")
                refresh_task_config_widgets(task)
                dialog.accept()
            else:
                QMessageBox.warning(dialog, "Import Failed", "Config parse failed, please retry.")

    # Bind events
    sort_combo.currentIndexChanged.connect(on_filter_changed)
    lang_filter_combo.currentIndexChanged.connect(on_filter_changed)
    if member_filter_combo is not None:
        member_filter_combo.currentIndexChanged.connect(on_filter_changed)
    config_list.itemSelectionChanged.connect(lambda: apply_btn.setEnabled(len(config_list.selectedItems()) > 0))
    refresh_btn.clicked.connect(on_filter_changed)
    apply_btn.clicked.connect(on_apply)
    cancel_btn.clicked.connect(dialog.reject)

    # Initial load
    loading_label.setVisible(True)
    load_configs()
    config_list.setVisible(True)
    loading_label.setVisible(False)

    dialog.exec_()
