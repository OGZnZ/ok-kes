from ok import TriggerTask

import re
import random
import time
import sys
import cv2
import os
import numpy as np
from opencc import OpenCC

_jp2t = OpenCC('jp2t')  # Japanese Kanji to Traditional Chinese
_t2s = OpenCC('t2s')  # Traditional to Simplified Chinese

def _normalize_text(text):
    """Convert Japanese Kanji glyphs to Traditional Chinese, then unify to Simplified."""
    return _t2s.convert(_jp2t.convert(text))


def _edit_distance(s1, s2, max_dist=1):
    """Calculate whether Levenshtein distance between two strings is <= max_dist."""
    if abs(len(s1) - len(s2)) > max_dist:
        return False
    if not s1 or not s2:
        return max(len(s1), len(s2)) <= max_dist
    m, n = len(s1), len(s2)
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        curr = [i] + [0] * n
        for j in range(1, n + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[n] <= max_dist


def is_subsequence(first: str, second: str) -> bool:
    """Determine whether the first string is a subsequence of the second."""
    second_iter = iter(second)
    return all(char in second_iter for char in first)


def _move_and_click(task: TriggerTask, x, y):
    """Move cursor to target position, wait for UI response, then click."""
    page_handler = sys._getframe(1).f_code.co_name
    task.log_info(
        f"Page handler '{page_handler}' triggered click event, target coords=({x:.3f}, {y:.3f})"
    )
    task.move_relative(x, y)
    task.sleep(0.5)
    task.click(x, y)


def _simplify_texts(texts):
    """Batch convert OCR results to Simplified via jp2t -> t2s (in-place modification)."""
    for b in texts:
        b.name = _normalize_text(b.name)
    return texts


def _get_config_value(task: TriggerTask, key, default):
    """Read runtime config: task.config first, default_config second, fallback last. Converts string to Simplified before returning."""
    if hasattr(task, 'config') and key in task.config:
        value = task.config[key]
    else:
        value = getattr(task, 'default_config', {}).get(key, default)
    if isinstance(value, str):
        value = _normalize_text(value).strip()
    elif isinstance(value, (list, tuple)):
        value = [
            _normalize_text(v).strip() if isinstance(v, str) else v
            for v in value
        ]
    return value


def _get_card_list(task: TriggerTask, key):
    """Read list config, return empty list on failure."""
    value = _get_config_value(task, key, [])
    return list(value) if isinstance(value, (list, tuple)) else []


def _get_card_reward_priority(task: TriggerTask):
    """Read card reward priority, placing farm starting card config at highest priority."""
    priority = _get_card_list(task, "卡牌奖励优先级")
    initial_card_name = _get_config_value(task, "刷初始卡牌", "")
    initial_card_name = initial_card_name.strip() if isinstance(initial_card_name, str) else ""
    if initial_card_name:
        priority = [
            initial_card_name,
            *(name for name in priority if name != initial_card_name),
        ]
    return priority


# Game language -> mapping file path
_GAME_LANG_FILE_MAP = {
    "繁体中文": os.path.join(os.path.dirname(__file__), 'assets', 'game_text_map', 'zh_tw.py'),
}
# Loaded mapping cache {language: SERVER_TEXT_MAP dict}
_LOADED_MAPS = {}


def _load_game_text_map(game_lang):
    """Load mapping table for specified language (cached)."""
    if game_lang not in _LOADED_MAPS:
        file_path = _GAME_LANG_FILE_MAP.get(game_lang)
        if file_path and os.path.exists(file_path):
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location(f"_game_map_{game_lang}", file_path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                _LOADED_MAPS[game_lang] = getattr(mod, 'SERVER_TEXT_MAP', {})
            except Exception:
                _LOADED_MAPS[game_lang] = {}
        else:
            _LOADED_MAPS[game_lang] = {}
    return _LOADED_MAPS[game_lang]


def _get_game_language(task: TriggerTask):
    """Get game language configured in current mode."""
    try:
        return str(task.config.get('游戏语言', '简体中文')).strip() or '简体中文'
    except Exception:
        return '简体中文'


def _get_game_text(task: TriggerTask, default_text):
    """Return server-specific search text according to currently configured game language."""
    game_lang = _get_game_language(task)

    if game_lang == '简体中文':
        return default_text

    mapping = _load_game_text_map(game_lang)
    return mapping.get(default_text, default_text)


def _migrate_route_boss_to_elite(task: TriggerTask):
    """Migrate "boss" to "Elite" in user's "Route Priority" config for backwards compatibility."""
    try:
        if hasattr(task, 'config') and '路线优先级' in task.config:
            priority = task.config['路线优先级']
            if isinstance(priority, (list, tuple)):
                new_priority = ["精英" if v == "boss" else v for v in priority]
                if new_priority != list(priority):
                    task.config['路线优先级'] = new_priority
                    from ok.gui.Communicate import communicate
                    communicate.task_list_updated.emit()
                    task.log_info(f"Migrated route priority config: boss -> elite {new_priority}")
    except Exception:
        pass


def _get_route_priority(task: TriggerTask):
    """Read route node priority config, return list; fallback to default order on error."""
    value = _get_config_value(task, '路线优先级', ["休息", "事件", "小怪", "精英"])
    return list(value) if isinstance(value, (list, tuple)) else ["休息", "事件", "小怪", "精英"]


# ------------------------- General Utilities -------------------------

def _get_current_credit(task: TriggerTask):
    """Read current credit points, taking maximum from two possible positions."""
    credit = 0
    for pos_x, pos_y in [(0.794, 0.054), (0.734, 0.053)]:
        box = find_box_at_point(task, pos_x, pos_y)
        if box and box.name.isdigit():
            val = int(box.name)
            if val > credit:
                credit = val
    return credit


def _neutral_card_limit(task: TriggerTask):
    """Chaos mode allows purchasing at most 3 neutral cards per run in shop."""
    return 3 if task.name == "自动卡厄思模式" else None


def _neutral_card_limit_reached(task: TriggerTask):
    """Determine whether neutral cards acquired this run reached fixed limit."""
    limit = _neutral_card_limit(task)
    if limit is None:
        return False
    acquired = getattr(task, "node_status", {}).get("neutral_card_count", 0)
    return acquired >= limit


def _record_removed_cards(task: TriggerTask, count=1):
    """Record actual count of cards removed in this run."""
    node_status = getattr(task, "node_status", None)
    if not isinstance(node_status, dict):
        return
    count = max(1, int(count))
    node_status["removed_card_count"] = (
        node_status.get("removed_card_count", 0) + count
    )
    task.log_info(
        f"Cards removed this run increased by {count}, total now {node_status['removed_card_count']}"
    )


def _record_neutral_card(task: TriggerTask):
    """Record actual acquisition of one neutral card this run."""
    node_status = getattr(task, "node_status", None)
    if not isinstance(node_status, dict):
        return
    node_status["neutral_card_count"] = (
        node_status.get("neutral_card_count", 0) + 1
    )
    task.log_info(
        f"Neutral cards acquired this run increased by 1, total now {node_status['neutral_card_count']}"
    )


def _parse_discounted_price(price_text):
    """Parse OCR digits that may concatenate pre- and post-discount prices."""
    price_text = price_text.strip()
    if not re.fullmatch(r"\d+", price_text):
        return None
    if len(price_text) == 6:
        return int(price_text[-3:])
    if len(price_text) in (4, 5):
        return int(price_text[-2:])
    return int(price_text)


def _get_current_hp_percent(task: TriggerTask):
    """Read current HP percentage, return False if unrecognizable."""
    hp_box = find_box_at_point(task, 0.209, 0.040)
    if not hp_box:
        return False
    hp_match = re.search(r'(\d+)/(\d+)', hp_box.name)
    if not hp_match:
        return False
    current_hp = int(hp_match.group(1))
    max_hp = int(hp_match.group(2))
    if max_hp <= 0:
        return False
    hp_percent = int(current_hp * 100 / max_hp)
    task.log_info(f"Current HP: {current_hp}/{max_hp} = {hp_percent}%")
    return hp_percent


def find_box_at_point(task: TriggerTask, rel_x, rel_y):
    """Find box containing relative point; return smallest area box (most precise) if multiple hit."""
    px, py = rel_x * task.width, rel_y * task.height
    hits = [b for b in task.all_texts
            if b.x <= px <= b.x + b.width and b.y <= py <= b.y + b.height]
    return min(hits, key=lambda b: b.area()) if hits else None


def find_target_card(task: TriggerTask):
    """Find target card features, returning feature box list and relative click positions."""
    search_box = task.box_of_screen(0.090, 0.179, 0.927, 0.342)
    target_boxes = task.find_feature(feature_name="target", box=search_box) or []
    click_positions = []
    for target_box in target_boxes:
        center_x = (target_box.x + target_box.width / 2) / task.width
        center_y = (target_box.y + target_box.height / 2) / task.height
        click_positions.append((
            min(1.0, max(0.0, center_x - 0.0975)),
            min(1.0, max(0.0, center_y + 0.2460)),
        ))
    return target_boxes, click_positions


def _recognize_cards_by_features(
    task: TriggerTask,
    region,
    page,
    feature_types,
    min_feature_distance,
    name_offsets,
    type_offsets,
    description_offsets,
    name_only_feature_thresholds=None,
    allow_empty_type_threshold=None,
):
    """Recognize cards by specified features and relative positions."""
    search_box = task.box_of_screen(*region)
    feature_candidates = []
    for feature_name, feature_type in feature_types.items():
        feature_boxes = task.find_feature(
            feature_name=feature_name,
            box=search_box,
            threshold=0.65,
        ) or []
        for feature_box in feature_boxes:
            feature_candidates.append((feature_name, feature_type, feature_box))

    def feature_distance(first, second):
        first_x = (first.x + first.width / 2) / task.width
        first_y = (first.y + first.height / 2) / task.height
        second_x = (second.x + second.width / 2) / task.width
        second_y = (second.y + second.height / 2) / task.height
        return (
            (first_x - second_x) ** 2 + (first_y - second_y) ** 2
        ) ** 0.5

    filtered_features = []
    for candidate in sorted(
        feature_candidates,
        key=lambda item: item[2].confidence,
        reverse=True,
    ):
        if any(
            feature_distance(candidate[2], kept[2]) < min_feature_distance
            for kept in filtered_features
        ):
            continue
        filtered_features.append(candidate)

    cards = []
    log_prefix = f"{page}: " if page else ""
    for feature_name, feature_type, feature_box in filtered_features:
        center_x = (feature_box.x + feature_box.width / 2) / task.width
        center_y = (feature_box.y + feature_box.height / 2) / task.height
        name_region = (
            max(0.0, center_x + name_offsets[0]),
            max(0.0, center_y + name_offsets[1]),
            min(1.0, center_x + name_offsets[2]),
            min(1.0, center_y + name_offsets[3]),
        )
        type_region = (
            max(0.0, center_x + type_offsets[0]),
            max(0.0, center_y + type_offsets[1]),
            min(1.0, center_x + type_offsets[2]),
            min(1.0, center_y + type_offsets[3]),
        )
        desc_region = (
            max(0.0, center_x + description_offsets[0]),
            max(0.0, center_y + description_offsets[1]),
            min(1.0, center_x + description_offsets[2]),
            min(1.0, center_y + description_offsets[3]),
        )
        card_name = _get_region_text(task, name_region).strip()
        task.log_info(
            f"{log_prefix}Card recognition debug: feature={feature_name}, center=({center_x:.4f},{center_y:.4f}), confidence={feature_box.confidence:.4f}, name_region={tuple(round(v, 4) for v in name_region)}, name_ocr={_region_text_debug_info(task, name_region)}, type_region={tuple(round(v, 4) for v in type_region)}, type_ocr={_region_text_debug_info(task, type_region)}, desc_region={tuple(round(v, 4) for v in desc_region)}"
        )
        if not card_name:
            task.log_info(f"{log_prefix}Card recognition debug: excluded feature because name is empty")
            continue
        card_type = _get_region_text(task, type_region).strip()
        description = _get_region_text(task, desc_region)
        name_only_threshold = (name_only_feature_thresholds or {}).get(
            feature_name
        )
        allow_name_only = (
            name_only_threshold is not None
            and feature_box.confidence > name_only_threshold
        )
        allow_empty_type = (
            allow_empty_type_threshold is not None
            and feature_box.confidence > allow_empty_type_threshold
        )
        if not allow_name_only and (
            not description or (not card_type and not allow_empty_type)
        ):
            task.log_info(
                f"{log_prefix}Card recognition debug: excluded feature due to missing type or description, type='{card_type}', desc='{description}'"
            )
            continue
        cards.append({
            "name": card_name,
            "type": card_type,
            "description": description,
            "feature_name": feature_name,
            "feature_type": feature_type,
            "confidence": feature_box.confidence,
            "feature_box": feature_box,
            "x": (name_region[0] + name_region[2]) / 2,
            "y": (name_region[1] + name_region[3]) / 2,
            "name_region": name_region,
            "type_region": type_region,
            "description_region": desc_region,
        })
    cards.sort(key=lambda card: card["feature_box"].x)
    if cards:
        task.log_info(f"{log_prefix}Recognized {len(cards)} cards")
        for index, card in enumerate(cards, 1):
            task.log_info(
                f"{log_prefix}Card {index}: name='{card['name']}', type='{card['type'] or card['feature_type']}', desc='{card['description']}', feature={card['feature_name']}, confidence={card['confidence']:.4f}"
            )
    return cards


def recognize_cards(
    task: TriggerTask,
    region=(0.021, 0.172, 0.988, 0.432),
    page="",
):
    """Recognize cards in card selection page."""
    return _recognize_cards_by_features(
        task=task,
        region=region,
        page=page,
        feature_types={
            "attack": "攻击/基础攻击",
            "skill": "技能/基础技能",
            "enhance": "强化",
            "hex": "咒术",
            "abnormal": "状态异常",
        },
        min_feature_distance=(
            (0.618 - 0.454) ** 2 + (0.304 - 0.306) ** 2
        ) ** 0.5,
        name_offsets=(-0.0150, -0.0635, 0.1450, -0.0175),
        type_offsets=(0.0120, -0.0205, 0.1090, 0.0245),
        description_offsets=(-0.0565, 0.1190, 0.1495, 0.4900),
    )


def recognize_cards_in_deck(
    task: TriggerTask,
    region=(0.274, 0.108, 0.929, 0.874),
    page="",
):
    """Recognize cards in deck area, marking cards selected with gold border."""
    cards = _recognize_cards_by_features(
        task=task,
        region=region,
        page=page,
        feature_types={
            "attack_in_deck": "攻击/基础攻击",
            "skill_in_deck": "技能/基础技能",
            "enhance_in_deck": "强化",
            "hex_in_deck": "咒术",
            "hex_in_deck_tw": "诅咒",
        },
        min_feature_distance=(
            (0.464 - 0.326) ** 2 + (0.175 - 0.175) ** 2
        ) ** 0.5,
        name_offsets=(-0.0090, -0.0435, 0.0900, -0.0105),
        type_offsets=(0.0070, -0.0175, 0.0880, 0.0175),
        description_offsets=(-0.0370, 0.0515, 0.1000, 0.3295),
        name_only_feature_thresholds={
            "hex_in_deck": 0.90,
            "hex_in_deck_tw": 0.90,
        },
        allow_empty_type_threshold=0.90,
    )
    _mark_selected_card_by_gold_border(task, cards, page=page)
    return cards


def recognize_event_options(
    task: TriggerTask,
    region=(0.198, 0.840, 0.803, 1.000),
    page="",
):
    """Recognize up to 3 event descriptions by event option features."""
    event_region = task.box_of_screen(*region)
    event_features = []
    for feature_name in ("event1", "event2", "event3", "event4", "event5", "event6", "event7", "event8"):
        for feature_box in task.find_feature(
            feature_name=feature_name,
            box=event_region,
            threshold=0.70,
        ) or []:
            center_x = (feature_box.x + feature_box.width / 2) / task.width
            center_y = (feature_box.y + feature_box.height / 2) / task.height
            event_features.append(
                (feature_name, feature_box, center_x, center_y)
            )

    filtered_features = []
    for candidate in sorted(
        event_features,
        key=lambda item: item[1].confidence,
        reverse=True,
    ):
        if any(
            (
                (candidate[2] - kept[2]) ** 2
                + (candidate[3] - kept[3]) ** 2
            ) ** 0.5 < 0.207
            for kept in filtered_features
        ):
            continue
        filtered_features.append(candidate)
        if len(filtered_features) >= 3:
            break

    filtered_features.sort(key=lambda item: item[2])
    event_options = []
    for feature_name, feature_box, center_x, center_y in filtered_features:
        description_region = (
            max(0.0, center_x - 0.119),
            max(0.0, center_y - 0.208),
            min(1.0, center_x + 0.122),
            min(1.0, center_y - 0.021),
        )
        description = _get_region_text(task, description_region).strip()
        if not description:
            continue
        event_options.append({
            "x": center_x,
            "y": center_y,
            "description": description,
            "description_region": description_region,
            "feature_name": feature_name,
            "confidence": feature_box.confidence,
        })

    if event_options:
        prefix = f"{page}: " if page else ""
        task.log_info(f"{prefix}Recognized {len(event_options)} event options")
        for index, event_option in enumerate(event_options, 1):
            task.log_info(
                f"{prefix}Event option {index}: desc='{event_option['description']}', feature={event_option['feature_name']}, confidence={event_option['confidence']:.4f}"
            )
    return event_options


def recognize_map_connections(
    task: TriggerTask,
    region=(0.019, 0.633, 0.380, 0.972),
    feature_threshold=0.85,
    line_threshold=0.30,
    special_feature_threshold=0.65,
):
    """Recognize minimap nodes and generate connectivity based on lit line continuity."""
    if task.frame is None:
        task.log_info("Minimap connectivity recognition failed: current frame is empty")
        return {"nodes": [], "connections": [], "adjacency": {}}

    node_types = {
        "position_in_map": "当前位置",
        "settlement_in_map": "结算",
        "enemy_in_map": "小怪",
        "safezoom_in_map": "休息",
        "elite_in_map": "精英",
        "event_in_map": "事件",
    }
    # Value > 0 indicates priority entry, < 0 lowers priority; subsequent new flags only need registration here without modifying recognition logic.
    special_feature_priorities = {
        "kalei_in_map": 1,
        "shop_in_map": 1,
        "seal_in_map": 1,
        "hard_in_map": -1,
    }
    search_box = task.box_of_screen(*region)
    candidates = []
    for feature_name, node_type in node_types.items():
        for feature_box in task.find_feature(
            feature_name=feature_name,
            box=search_box,
            threshold=feature_threshold,
        ) or []:
            center_x = (feature_box.x + feature_box.width / 2) / task.width
            center_y = (feature_box.y + feature_box.height / 2) / task.height
            # Current position is teardrop icon; line connects to bottom tip rather than center.
            if feature_name == "position_in_map":
                center_y += (feature_box.height / task.height) * 0.36
            candidates.append({
                "feature_name": feature_name,
                "type": node_type,
                "x": center_x,
                "y": center_y,
                "confidence": float(feature_box.confidence),
                "feature_box": feature_box,
            })

    position_candidates = [
        candidate for candidate in candidates
        if candidate["feature_name"] == "position_in_map"
    ]
    position_x = None
    passed_feature_x_limit = None
    if position_candidates:
        position_x = max(
            position_candidates,
            key=lambda item: item["confidence"],
        )["x"]
        passed_feature_x_limit = position_x + 0.027
        original_candidate_count = len(candidates)
        candidates = [
            candidate for candidate in candidates
            if candidate["feature_name"] == "position_in_map"
            or candidate["x"] >= passed_feature_x_limit
        ]
        task.log_info(
            f"Minimap current pos X={position_x:.4f}, filtering visited nodes with X < {passed_feature_x_limit:.4f}, excluded {original_candidate_count - len(candidates)} normal node features"
        )

    # Same node may match multiple templates. Deduplicate based on distance between reference points (0.229, 0.674) and (0.257, 0.674), keeping highest confidence.
    feature_dedup_distance = (
        (0.257 - 0.229) ** 2 + (0.674 - 0.674) ** 2
    ) ** 0.5
    nodes = []
    for candidate in sorted(
        candidates,
        key=lambda item: item["confidence"],
        reverse=True,
    ):
        if any(
            (
                (candidate["x"] - kept["x"]) ** 2
                + (candidate["y"] - kept["y"]) ** 2
            ) ** 0.5 < feature_dedup_distance
            for kept in nodes
        ):
            continue
        nodes.append(candidate)
    # Minimap proceeds left to right. Cluster into columns by X coord, then sort top-to-bottom within columns to ensure node numbers match selectable order.
    columns = []
    for node in sorted(nodes, key=lambda item: item["x"]):
        column = next(
            (
                existing
                for existing in columns
                if abs(node["x"] - existing["center_x"]) < 0.025
            ),
            None,
        )
        if column is None:
            columns.append({"center_x": node["x"], "nodes": [node]})
            continue
        column["nodes"].append(node)
        column["center_x"] = sum(
            item["x"] for item in column["nodes"]
        ) / len(column["nodes"])

    nodes = []
    for column_index, column in enumerate(columns):
        column_nodes = sorted(column["nodes"], key=lambda item: item["y"])
        for row_index, node in enumerate(column_nodes, start=1):
            node["column"] = column_index
            node["row"] = row_index
            node["id"] = len(nodes)
            node["special_features"] = []
            node["special_priority"] = 0
            nodes.append(node)

    # Each special flag binds only to nearest node. A node can hold multiple flags simultaneously.
    special_features = []
    for feature_name, priority in special_feature_priorities.items():
        for feature_box in task.find_feature(
            feature_name=feature_name,
            box=search_box,
            threshold=special_feature_threshold,
        ) or []:
            special_feature = {
                "feature_name": feature_name,
                "priority": priority,
                "x": (feature_box.x + feature_box.width / 2) / task.width,
                "y": (feature_box.y + feature_box.height / 2) / task.height,
                "confidence": float(feature_box.confidence),
                "feature_box": feature_box,
            }
            if (
                passed_feature_x_limit is not None
                and special_feature["x"] < passed_feature_x_limit
            ):
                task.log_info(
                    f"Minimap special feature {feature_name} is in visited area, "
                    f"X={special_feature['x']:.4f}, excluded"
                )
                continue
            special_features.append(special_feature)
    filtered_special_features = []
    for special_feature in sorted(
        special_features,
        key=lambda item: item["confidence"],
        reverse=True,
    ):
        if any(
            (
                (special_feature["x"] - kept["x"]) ** 2
                + (special_feature["y"] - kept["y"]) ** 2
            ) ** 0.5 < feature_dedup_distance
            for kept in filtered_special_features
        ):
            continue
        filtered_special_features.append(special_feature)
    special_features = filtered_special_features
    for special_feature in special_features:
        nearest_node = min(
            nodes,
            key=lambda node: (
                (node["x"] - special_feature["x"]) ** 2
                + (node["y"] - special_feature["y"]) ** 2
            ),
            default=None,
        )
        if nearest_node is None:
            continue
        distance = (
            (nearest_node["x"] - special_feature["x"]) ** 2
            + (nearest_node["y"] - special_feature["y"]) ** 2
        ) ** 0.5
        if distance > 0.035:
            continue
        special_feature["node_id"] = nearest_node["id"]
        nearest_node["special_features"].append(special_feature)
        nearest_node["special_priority"] += special_feature["priority"]

    gray = cv2.cvtColor(task.frame[:, :, :3], cv2.COLOR_BGR2GRAY)
    frame_height, frame_width = gray.shape[:2]
    perpendicular_radius = max(2, round(frame_height * 0.004))

    def line_brightness_ratio(first, second):
        start_x = first["x"] * frame_width
        start_y = first["y"] * frame_height
        end_x = second["x"] * frame_width
        end_y = second["y"] * frame_height
        delta_x = end_x - start_x
        delta_y = end_y - start_y
        pixel_distance = (delta_x ** 2 + delta_y ** 2) ** 0.5
        if pixel_distance <= 0:
            return 0.0
        perpendicular_x = -delta_y / pixel_distance
        perpendicular_y = delta_x / pixel_distance
        sample_count = max(8, round(pixel_distance * 0.40))
        bright_samples = 0
        for progress in np.linspace(0.30, 0.70, sample_count):
            sample_x = start_x + delta_x * progress
            sample_y = start_y + delta_y * progress
            band_values = []
            for offset in range(-perpendicular_radius, perpendicular_radius + 1):
                pixel_x = int(round(sample_x + perpendicular_x * offset))
                pixel_y = int(round(sample_y + perpendicular_y * offset))
                if 0 <= pixel_x < frame_width and 0 <= pixel_y < frame_height:
                    band_values.append(gray[pixel_y, pixel_x])
            if band_values and max(band_values) >= 110:
                bright_samples += 1
        return bright_samples / sample_count

    connections = []
    adjacency = {node["id"]: [] for node in nodes}

    def has_intermediate_node(first, second):
        vector_x = second["x"] - first["x"]
        vector_y = second["y"] - first["y"]
        vector_length_squared = vector_x ** 2 + vector_y ** 2
        if vector_length_squared <= 0:
            return False
        for other in nodes:
            if other is first or other is second:
                continue
            progress = (
                (other["x"] - first["x"]) * vector_x
                + (other["y"] - first["y"]) * vector_y
            ) / vector_length_squared
            if not 0.12 < progress < 0.88:
                continue
            projected_x = first["x"] + vector_x * progress
            projected_y = first["y"] + vector_y * progress
            if (
                (other["x"] - projected_x) ** 2
                + (other["y"] - projected_y) ** 2
            ) ** 0.5 < 0.025:
                return True
        return False

    def has_intermediate_special_feature(first, second):
        """Determine whether candidate connection passes through a special flag belonging to a third node."""
        vector_x = second["x"] - first["x"]
        vector_y = second["y"] - first["y"]
        vector_length_squared = vector_x ** 2 + vector_y ** 2
        if vector_length_squared <= 0:
            return False
        endpoint_ids = {first["id"], second["id"]}
        for special_feature in special_features:
            if special_feature.get("node_id") in endpoint_ids:
                continue
            progress = (
                (special_feature["x"] - first["x"]) * vector_x
                + (special_feature["y"] - first["y"]) * vector_y
            ) / vector_length_squared
            if not 0.12 < progress < 0.88:
                continue
            projected_x = first["x"] + vector_x * progress
            projected_y = first["y"] + vector_y * progress
            if (
                (special_feature["x"] - projected_x) ** 2
                + (special_feature["y"] - projected_y) ** 2
            ) ** 0.5 < 0.015:
                return True
        return False

    for first_index, first in enumerate(nodes):
        for second in nodes[first_index + 1:]:
            # Keep only directed edges from current column to adjacent right column, do not generate reverse adjacency.
            if second["column"] != first["column"] + 1:
                continue
            delta_x = abs(first["x"] - second["x"])
            delta_y = abs(first["y"] - second["y"])
            distance = (delta_x ** 2 + delta_y ** 2) ** 0.5
            if not 0.035 <= distance <= 0.210 or delta_x > 0.125:
                continue
            # Map connections are horizontal or diagonal; nodes in same column across different rows do not connect directly.
            if delta_y > 0.025 and delta_x < 0.025:
                continue
            if has_intermediate_node(first, second):
                continue
            if has_intermediate_special_feature(first, second):
                continue
            brightness_ratio = line_brightness_ratio(first, second)
            if brightness_ratio < line_threshold:
                continue
            connection = {
                "from": first["id"],
                "to": second["id"],
                "brightness_ratio": brightness_ratio,
            }
            connections.append(connection)
            adjacency[first["id"]].append(second["id"])

    task.log_info(f"Minimap recognized {len(nodes)} nodes, {len(connections)} lit connections")
    for node in nodes:
        task.log_info(
            f"Minimap node {node['id']}: type={node['type']}, col {node['column'] + 1} row {node['row']}, pos=({node['x']:.4f}, {node['y']:.4f}), feature={node['feature_name']}, confidence={node['confidence']:.4f}, special_flags={[item['feature_name'] for item in node['special_features']]}, special_priority={node['special_priority']}"
        )
    for connection in connections:
        task.log_info(
            f"Minimap connection: node {connection['from']} -> node {connection['to']}, brightness ratio={connection['brightness_ratio']:.2%}"
        )
    task.log_info(f"Minimap directed adjacency: {adjacency}")
    return {
        "nodes": nodes,
        "connections": connections,
        "adjacency": adjacency,
    }


def find_best_map_route(map_info, target_node_type):
    """Find directed route with maximum target type nodes, returning next column node to choose."""
    nodes = map_info.get("nodes", [])
    adjacency = map_info.get("adjacency", {})
    node_by_id = {node["id"]: node for node in nodes}
    current_node = next(
        (node for node in nodes if node["type"] == "当前位置"),
        None,
    )
    if current_node is None:
        return {
            "target_type": target_node_type,
            "target_count": 0,
            "special_priority_score": 0,
            "route": [],
            "next_node_id": None,
            "next_row": None,
        }

    route_cache = {}

    def best_route_from(node_id):
        if node_id in route_cache:
            return route_cache[node_id]
        node = node_by_id[node_id]
        is_target = node["type"] == target_node_type
        own_score = int(is_target)
        own_special_score = node.get("special_priority", 0) if is_target else 0
        next_node_ids = adjacency.get(node_id, [])
        if not next_node_ids:
            result = (own_score, own_special_score, [node_id])
            route_cache[node_id] = result
            return result

        candidates = []
        for next_node_id in next_node_ids:
            child_score, child_special_score, child_route = best_route_from(
                next_node_id
            )
            candidates.append((
                own_score + child_score,
                own_special_score + child_special_score,
                node_by_id[next_node_id]["row"],
                [node_id, *child_route],
            ))
        # Compare target node count first, then special priority; if still tied, choose route with higher next node.
        best_score, best_special_score, _, best_route = min(
            candidates,
            key=lambda item: (-item[0], -item[1], item[2]),
        )
        result = (best_score, best_special_score, best_route)
        route_cache[node_id] = result
        return result

    target_count, special_priority_score, route = best_route_from(
        current_node["id"]
    )
    next_node = node_by_id[route[1]] if len(route) > 1 else None
    return {
        "target_type": target_node_type,
        "target_count": target_count,
        "special_priority_score": special_priority_score,
        "route": route,
        "next_node_id": next_node["id"] if next_node else None,
        "next_row": next_node["row"] if next_node else None,
    }


def find_best_map_route_by_priority(map_info, node_type_priority):
    """Compute optimal route weighted by node types, returning next column node to choose."""
    nodes = map_info.get("nodes", [])
    adjacency = map_info.get("adjacency", {})
    node_by_id = {node["id"]: node for node in nodes}
    current_node = next(
        (node for node in nodes if node["type"] == "当前位置"),
        None,
    )
    if current_node is None:
        return None

    route_cache = {}
    priority_weights = {
        node_type: len(node_type_priority) - index
        for index, node_type in enumerate(node_type_priority)
    }
    highest_priority_weight = max(priority_weights.values(), default=1)
    shop_bonus = highest_priority_weight * 2

    def best_route_from(node_id):
        if node_id in route_cache:
            return route_cache[node_id]
        node = node_by_id[node_id]
        own_counts = tuple(
            int(node["type"] == node_type)
            for node_type in node_type_priority
        )
        own_shop_count = int(any(
            item["feature_name"] == "shop_in_map"
            for item in node.get("special_features", [])
        ))
        own_special_score = sum(
            item["priority"]
            for item in node.get("special_features", [])
            if item["feature_name"] != "shop_in_map"
        )
        own_weighted_score = (
            priority_weights.get(node["type"], 0)
            + own_shop_count * shop_bonus
            + own_special_score
        )
        next_node_ids = adjacency.get(node_id, [])
        if not next_node_ids:
            result = (
                own_weighted_score,
                own_shop_count,
                own_counts,
                own_special_score,
                [node_id],
            )
            route_cache[node_id] = result
            return result

        candidates = []
        for next_node_id in next_node_ids:
            (
                child_weighted_score,
                child_shop_count,
                child_counts,
                child_special_score,
                child_route,
            ) = best_route_from(next_node_id)
            total_counts = tuple(
                own + child
                for own, child in zip(own_counts, child_counts)
            )
            candidates.append((
                own_weighted_score + child_weighted_score,
                own_shop_count + child_shop_count,
                total_counts,
                own_special_score + child_special_score,
                node_by_id[next_node_id]["row"],
                [node_id, *child_route],
            ))
        (
            best_weighted_score,
            best_shop_count,
            best_counts,
            best_special_score,
            _,
            best_route,
        ) = min(
            candidates,
            key=lambda item: (
                -item[0],
                -item[1],
                tuple(-count for count in item[2]),
                -item[3],
                item[4],
            ),
        )
        result = (
            best_weighted_score,
            best_shop_count,
            best_counts,
            best_special_score,
            best_route,
        )
        route_cache[node_id] = result
        return result

    (
        weighted_score,
        shop_count,
        type_counts,
        special_priority_score,
        route,
    ) = best_route_from(current_node["id"])
    next_node = node_by_id[route[1]] if len(route) > 1 else None
    return {
        "priority": list(node_type_priority),
        "priority_weights": priority_weights,
        "shop_bonus": shop_bonus,
        "weighted_score": weighted_score,
        "shop_count": shop_count,
        "type_counts": dict(zip(node_type_priority, type_counts)),
        "special_priority_score": special_priority_score,
        "route": route,
        "next_node_id": next_node["id"] if next_node else None,
        "next_row": next_node["row"] if next_node else None,
        "next_node_type": next_node["type"] if next_node else None,
        "next_special_features": [
            item["feature_name"]
            for item in next_node.get("special_features", [])
        ] if next_node else [],
    }


def _mark_selected_card_by_gold_border(
    task: TriggerTask,
    cards,
    page="",
    threshold=0.25,
):
    """Calculate gold border score for card and write selection state into card info."""
    for card in cards:
        card["selected"] = False
        card["gold_border_score"] = 0.0
        card["gold_border_edges"] = {}
    if not cards or task.frame is None:
        return

    frame = task.frame[:, :, :3]
    frame_height, frame_width = frame.shape[:2]
    band_x = max(2, round(frame_width * 0.004))
    band_y = max(2, round(frame_height * 0.006))

    def gold_ratio(left, top, right, bottom):
        left = max(0, min(frame_width, round(left)))
        right = max(0, min(frame_width, round(right)))
        top = max(0, min(frame_height, round(top)))
        bottom = max(0, min(frame_height, round(bottom)))
        if right <= left or bottom <= top:
            return 0.0
        hsv = cv2.cvtColor(frame[top:bottom, left:right], cv2.COLOR_BGR2HSV)
        gold_mask = cv2.inRange(
            hsv,
            np.array((8, 100, 160), dtype=np.uint8),
            np.array((38, 255, 255), dtype=np.uint8),
        )
        return float(cv2.countNonZero(gold_mask)) / gold_mask.size

    scored_cards = []
    for card in cards:
        feature_box = card["feature_box"]
        center_x = feature_box.x + feature_box.width / 2
        center_y = feature_box.y + feature_box.height / 2
        card_left = center_x - frame_width * 0.047
        card_right = center_x + frame_width * 0.103
        card_top = center_y - frame_height * 0.061
        card_bottom = center_y + frame_height * 0.330

        edge_scores = {
            "top": gold_ratio(
                card_left, card_top - band_y, card_right, card_top + band_y
            ),
            "bottom": gold_ratio(
                card_left, card_bottom - band_y, card_right, card_bottom + band_y
            ),
            "left": gold_ratio(
                card_left - band_x, card_top, card_left + band_x, card_bottom
            ),
            "right": gold_ratio(
                card_right - band_x, card_top, card_right + band_x, card_bottom
            ),
        }
        visible_edge_scores = [
            edge_scores["left"],
            edge_scores["right"],
        ]
        score = sum(visible_edge_scores) / len(visible_edge_scores)
        strong_edge_count = sum(value >= 0.08 for value in visible_edge_scores)
        card["gold_border_score"] = score
        card["gold_border_edges"] = edge_scores
        scored_cards.append((score, strong_edge_count, card))

    prefix = f"{page}: " if page else ""
    for score, strong_edge_count, card in scored_cards:
        if score >= threshold and strong_edge_count == 2:
            card["selected"] = True

    for card in cards:
        edge_scores = card["gold_border_edges"]
        task.log_info(
            f"{prefix}Card '{card['name']}' selected={card['selected']}, gold border score={card['gold_border_score']:.4f}, top={edge_scores['top']:.4f}, bottom={edge_scores['bottom']:.4f}, left={edge_scores['left']:.4f}, right={edge_scores['right']:.4f}"
        )

    if not any(card["selected"] for card in cards):
        task.log_info(f"{prefix}Gold border for selected card not detected")


def find_text(task: TriggerTask, pattern):
    """Find first box matching regex across all recognized texts."""
    return next((b for b in task.all_texts if re.search(pattern, b.name)), None)


def _clean_match(name, target):
    """Compare text against target after stripping non-alphanumeric and non-CJK symbols."""
    cleaned = re.sub(r'[^\u4e00-\u9fff\w]', '', name)
    return cleaned == target


def _get_region_text(task: TriggerTask, region):
    """Get all OCR text in specified region, returning stripped concatenated string."""
    x1, y1, x2, y2 = region
    texts = [
        b.name.strip() for b in task.all_texts
        if x1 <= (b.x + b.width / 2) / task.width <= x2
        and y1 <= (b.y + b.height / 2) / task.height <= y2
        and b.name.strip()
    ]
    return "".join(texts)


def _region_text_debug_info(task: TriggerTask, region):
    """Return OCR box info in region text concatenation for debugging region offsets."""
    x1, y1, x2, y2 = region
    matched = []
    for box in task.all_texts:
        center_x = (box.x + box.width / 2) / task.width
        center_y = (box.y + box.height / 2) / task.height
        if x1 <= center_x <= x2 and y1 <= center_y <= y2 and box.name.strip():
            matched.append(
                f"「{box.name.strip()}」"
                f"(center={center_x:.4f},{center_y:.4f}, confidence={box.confidence:.4f})"
            )
    return ", ".join(matched) if matched else "None"


_CARD_TYPE_KEYWORDS = {
    "攻击", "强化", "技能", "技", "咒术", "诅咒",
    "攻", "击", "基础", "基本", "状态", "异常",
}


def _card_has_type_below(task: TriggerTask, box):
    """Determine whether a card type tag exists below text box (card name feature)."""
    box_bottom_y = (box.y + box.height) / task.height
    box_cx = (box.x + box.width / 2) / task.width
    for b in task.all_texts:
        cx = (b.x + b.width / 2) / task.width
        cy = (b.y + b.height / 2) / task.height
        dy = cy - box_bottom_y
        dx = abs(cx - box_cx)
        if -0.005 <= dy <= 0.040 and dx <= 0.045 and len(b.name) <= 4:
            for kw in _CARD_TYPE_KEYWORDS:
                if kw in b.name:
                    return True
    return False


def region_white_ratio(task: TriggerTask, region):
    """Calculate white pixel ratio in specified region."""
    if task.frame is None:
        return 1.0
    region_box = task.box_of_screen(*region)
    pixels = task.frame[
        region_box.y:region_box.y + region_box.height,
        region_box.x:region_box.x + region_box.width,
        :3,
    ]
    if pixels.size == 0:
        return 1.0
    channel_min = pixels.min(axis=2)
    channel_max = pixels.max(axis=2)
    white_mask = (channel_min >= 240) & ((channel_max - channel_min) <= 15)
    return float(np.count_nonzero(white_mask)) / white_mask.size


def _point_is_white(task: TriggerTask, x, y, page):
    """Determine if specified point matches white color used by card selection scrollbar."""
    pixel_x = min(task.width - 1, max(0, round(x * task.width)))
    pixel_y = min(task.height - 1, max(0, round(y * task.height)))
    blue, green, red = (
        int(value) for value in task.frame[pixel_y, pixel_x, :3]
    )
    is_white = min(blue, green, red) >= 240 and (
        max(blue, green, red) - min(blue, green, red)
    ) <= 15
    task.log_info(
        f"{page}: Point ({x:.3f}, {y:.3f}) color=B{blue}/G{green}/R{red}, is_white={is_white}"
    )
    return is_white


def _scroll_card_page(task: TriggerTask, x, y, amount, page, distance=0.25):
    """Move cursor to card selection area and scroll."""
    direction = "down" if amount < 0 else "up"
    if task.is_adb():
        to_y = max(0.05, y - distance) if amount < 0 else min(0.95, y + distance)
        task.log_info(
            f"{page}: ADB swiping from ({x:.3f}, {y:.3f}) to ({x:.3f}, {to_y:.3f}), scrolling {direction}"
        )
        task.swipe_relative(x, y, x, to_y, duration=1, settle_time=1)
        task.sleep(1)
    else:
        task.log_info(f"{page}: Scrolling {direction} at ({x:.3f}, {y:.3f})")
        task.move_relative(x, y)
        task.sleep(0.05)
        task.scroll_relative(x, y, amount)
        task.sleep(0.5)


def select_card(task: TriggerTask, card_names, count=1, action=""):
    """Select cards using deck features, supporting scroll search, basic card removal, and fallback selection."""
    selected = 0
    max_scrolls = 20
    page = f"select_card-{action}" if action else "select_card"
    prefer_remove_base = (
        action == "移除"
        and _get_config_value(task, "优先移除基础牌", True)
    )
    prefer_target_member_row = (
        action == "移除"
        and _get_config_value(task, "刷空档", False) is True
    )
    base_card_type = _get_game_text(task, "基础")
    target_member_box = task.box_of_screen(0.079, 0.092, 0.209, 0.675)
    flash_priority = (
        _get_card_list(task, "闪光优先级")
        if action in ("闪光", "灵光")
        else []
    )

    def record_pending_removal():
        if action == "移除":
            task._pending_removed_card_count = (
                getattr(task, "_pending_removed_card_count", 0) + 1
            )

    def filter_flash_priority_cards(cards):
        """When flashing, exclude cards already matching flash priority to avoid duplicate selection."""
        if not flash_priority:
            return cards

        filtered_cards = []
        for card in cards:
            combined_text = f"{card['name']}：:{card['description']}"
            matched_keyword = next(
                (
                    keyword.strip()
                    for keyword in flash_priority
                    if isinstance(keyword, str)
                    and keyword.strip()
                    and is_subsequence(keyword.strip(), combined_text)
                ),
                None,
            )
            if matched_keyword:
                task.log_info(
                    f"{page}: Card '{card['name']}' name/desc matched flash priority '{matched_keyword}', excluding card"
                )
                continue
            filtered_cards.append(card)
        return filtered_cards

    def refresh_cards():
        task.all_texts = _simplify_texts(task.ocr())
        cards = recognize_cards_in_deck(task, page=page)
        return filter_flash_priority_cards(cards)

    def click_cards(cards, predicate, reason):
        nonlocal selected
        clicked = False
        for card in cards:
            if selected >= count:
                break
            if card["selected"] or not predicate(card):
                continue
            task.log_info(f"{page}: {reason}「{card['name']}」")
            _move_and_click(task, card["x"], card["y"])
            task.sleep(0.3)
            card["selected"] = True
            selected += 1
            record_pending_removal()
            clicked = True
        return clicked

    def click_priority_cards(cards):
        nonlocal selected
        clicked = False
        for target in card_names:
            if selected >= count:
                break
            target = target.strip() if isinstance(target, str) else ""
            if not target:
                continue
            for card in cards:
                if selected >= count:
                    break
                if card["selected"]:
                    continue
                card_name = card["name"].strip()
                if target not in card_name and card_name not in target:
                    continue
                task.log_info(
                    f"{page}: Matched priority '{target}', clicking target card '{card['name']}'"
                )
                _move_and_click(task, card["x"], card["y"])
                task.sleep(0.3)
                card["selected"] = True
                selected += 1
                record_pending_removal()
                clicked = True
        return clicked

    def click_target_member_row_cards(cards):
        """When farming empty slots, prioritize removing cards in same row as target member."""
        if not prefer_target_member_row or selected >= count:
            return False
        if not task.feature_exists("target_member_in_select_card"):
            return False
        target_member = task.find_one(
            feature_name="target_member_in_select_card",
            box=target_member_box,
            threshold=0.6,
        )
        if not target_member:
            return False
        target_y = (
            target_member.y + target_member.height / 2
        ) / task.height
        task.log_info(
            f"{page}: Empty-slot farming found target member, confidence={target_member.confidence:.4f}, center Y={target_y:.4f}"
        )
        return click_cards(
            cards,
            lambda card: abs(card["y"] - target_y) <= 0.25,
            "Empty-slot farming prioritizing same-row card removal, clicking",
        )

    def sync_visible_selected(cards):
        nonlocal selected
        if selected == 0:
            selected = min(count, sum(card["selected"] for card in cards))

    def find_action_button():
        if not action:
            return None
        action_text = _get_game_text(task, action)
        return next(
            (
                box for box in task.all_texts
                if 0.495 <= (box.x + box.width / 2) / task.width <= 0.997
                and 0.878 <= (box.y + box.height / 2) / task.height <= 1.001
                and action_text in box.name
            ),
            None,
        )

    cards = refresh_cards()
    if not cards:
        if find_action_button():
            task.log_info(
                f"{page}: Initial recognition missed cards but '{action}' button present, continuing selection flow"
            )
        else:
            task.log_info(f"{page}: No cards or action buttons recognized, terminating selection")
            return False
    sync_visible_selected(cards)
    scrollbar_white_ratio = region_white_ratio(
        task, (0.976, 0.119, 0.988, 0.858)
    )
    single_page = scrollbar_white_ratio < 0.01
    task.log_info(
        f"{page}: Scrollbar region white ratio={scrollbar_white_ratio:.2%}, single page={single_page}"
    )

    down_scrolls = 0
    while True:
        click_target_member_row_cards(cards)
        if selected >= count:
            task.log_info(f"{page}: Selected {selected}/{count} cards")
            return True
        click_priority_cards(cards)
        if selected >= count:
            task.log_info(f"{page}: Selected {selected}/{count} cards")
            return True

        if single_page:
            task.log_info(f"{page}: Single page of cards, skipping downward scroll")
            break

        if _point_is_white(task, 0.982, 0.846, page):
            task.log_info(f"{page}: Reached bottom of card list")
            break

        if down_scrolls >= max_scrolls:
            task.log_info(f"{page}: Downward scroll reached limit of {max_scrolls}")
            break

        _scroll_card_page(task, 0.251, 0.735, -3, page)
        down_scrolls += 1
        cards = refresh_cards()
        if not cards:
            if find_action_button():
                task.log_info(
                    f"{page}: Cards missed after scrolling down but '{action}' button present, continuing scroll"
                )
                continue
            task.log_info(f"{page}: No cards or action buttons recognized after scrolling down, terminating selection")
            return False

    if action == "移除" and selected < count:
        bottom_to_top_cards = sorted(
            cards,
            key=lambda card: (card["y"], card["x"]),
            reverse=True,
        )
        click_cards(
            bottom_to_top_cards,
            lambda card: card["feature_name"] in {
                "hex_in_deck",
                "hex_in_deck_tw",
            },
            "Bottom page prioritizing hex card removal, clicking",
        )
        if selected >= count:
            return True

    if prefer_remove_base and selected < count:
        bottom_to_top_cards = sorted(
            cards,
            key=lambda card: (card["y"], card["x"]),
            reverse=True,
        )
        click_cards(
            bottom_to_top_cards,
            lambda card: base_card_type in card["type"],
            "Bottom page prioritizing basic card removal, clicking",
        )
        if selected >= count:
            return True

        up_scrolls = 0
        while not single_page:
            if _point_is_white(task, 0.982, 0.128, page):
                task.log_info(f"{page}: Reached top of card list")
                break

            if up_scrolls >= max_scrolls:
                task.log_info(f"{page}: Upward scroll reached limit of {max_scrolls}")
                break

            _scroll_card_page(task, 0.252, 0.179, 3, page)
            up_scrolls += 1
            cards = refresh_cards()
            if not cards:
                if find_action_button():
                    task.log_info(
                        f"{page}: Cards missed after scrolling up but '{action}' button present, continuing scroll"
                    )
                    continue
                task.log_info(f"{page}: No cards or action buttons recognized after scrolling up, terminating selection")
                return False
            click_target_member_row_cards(cards)
            if selected >= count:
                task.log_info(f"{page}: Selected {selected}/{count} cards")
                return True
            bottom_to_top_cards = sorted(
                cards,
                key=lambda card: (card["y"], card["x"]),
                reverse=True,
            )
            click_cards(
                bottom_to_top_cards,
                lambda card: base_card_type in card["type"],
                "Scrolled up and found basic card, clicking",
            )
            if selected >= count:
                return True

    task.all_texts = _simplify_texts(task.ocr())
    action_box = task.box_of_screen(0.424, 0.882, 1.000, 0.999)
    for button_name in ("跳过", "取消"):
        button = next(
            (
                box for box in task.all_texts
                if action_box.x <= box.x + box.width / 2 <= action_box.x + action_box.width
                and action_box.y <= box.y + box.height / 2 <= action_box.y + action_box.height
                and button_name in box.name
            ),
            None,
        )
        if button:
            task.log_info(f"{page}: Insufficient cards found, clicking '{button_name}'")
            task.click_box(button)
            if action == "移除":
                task._pending_removed_card_count = 0
            return True

    cards = recognize_cards_in_deck(task, page=f"{page}-fallback")
    cards = filter_flash_priority_cards(cards)
    fallback_cards = sorted(
        cards,
        key=lambda card: (card["y"], card["x"]),
        reverse=True,
    )
    click_cards(fallback_cards, lambda card: True, "Fallback card selection, clicking")
    task.log_info(f"{page}: Fallback handling complete, selected {selected}/{count} cards")
    return True


def calculate_dominant_hue(task: TriggerTask, region):
    """Calculate dominant hue of region, returning hue value (0-179), or -1 if none."""
    box = task.box_of_screen(*region)
    frame = task.frame[box.y:box.y + box.height, box.x:box.x + box.width, :3]
    hue, sat, val = cv2.split(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV))

    valid_hue = hue[(sat > 30) & (val > 30)]
    if len(valid_hue) == 0:
        return -1

    hist = cv2.calcHist([valid_hue.astype(np.float32)], [0], None, [180], [0, 180])
    return int(np.argmax(hist))


def is_button_active(task: TriggerTask, button_box):
    """Determine whether button is in clickable (active) state.

    Args:
        task: TriggerTask instance
        button_box: Box object for button text (pixel coords)

    Returns:
        bool: True if button is clickable (active), False if unclickable (inactive/gray)
    """
    # Calculate left detection region (button icon / background area)
    # Proportions calculated from reference box:
    # Button box: (0.898, 0.908, 0.941, 0.950) w=0.043, h=0.042
    # Left region: (0.866, 0.912, 0.895, 0.947) w=0.029, h=0.035
    # Left width = button width * 0.67, x = button x - left width * 1.1
    # Left height = button height * 0.83, y = button y + button height * 0.1

    left_width = int(button_box.width * 0.67)
    left_height = int(button_box.height * 0.83)
    left_x = button_box.x - int(left_width * 1.1)
    left_y = button_box.y + int(button_box.height * 0.1)

    # Ensure region is within screen bounds
    if left_x < 0:
        left_x = 0
    if left_y < 0:
        left_y = 0
    if left_x + left_width > task.width:
        left_width = task.width - left_x
    if left_y + left_height > task.height:
        left_height = task.height - left_y

    if left_width <= 0 or left_height <= 0:
        task.log_info(f"Button left region invalid: ({left_x}, {left_y}, {left_width}, {left_height})")
        return False

    # Extract region image
    region_img = task.frame[left_y:left_y + left_height, left_x:left_x + left_width, :3]
    if region_img.size == 0:
        task.log_info("Button left region image is empty")
        return False

    # Calculate average BGR color
    avg_color = cv2.mean(region_img)[:3]  # B, G, R mean values
    avg_b, avg_g, avg_r = avg_color

    # Determine if close to disabled gray (195, 195, 195)
    # Tolerance: channels between 190-200 with close values
    # target_gray = 195
    tolerance = 5  # Allow ±5 margin of error

    # Compute range boundaries
    lower_bound = 120 #target_gray - tolerance  # 190
    upper_bound = 200 #target_gray + tolerance  # 200

    # Verify each channel is within target range
    in_range = (
        lower_bound <= avg_b <= upper_bound and
        lower_bound <= avg_g <= upper_bound and
        lower_bound <= avg_r <= upper_bound
    )

    # Verify channels are close to each other (small max diff)
    max_diff = max(abs(avg_b - avg_g), abs(avg_g - avg_r), abs(avg_r - avg_b))
    is_close = max_diff < tolerance

    # If close to (195, 195, 195) gray, button is not clickable
    is_disabled_gray = in_range and is_close

    task.log_info(f"Button left region color: B={avg_b:.1f}, G={avg_g:.1f}, R={avg_r:.1f}, is_disabled_gray={is_disabled_gray} (range {lower_bound}-{upper_bound}, max_diff={max_diff:.1f})")

    # If disabled gray, button is unclickable; otherwise clickable
    return not is_disabled_gray


# def group_dialog_columns(task: TriggerTask, region, max_width_ratio=0.25, align_tolerance=0.04):
#     """Cluster text boxes in region by left edge into dialog columns."""
#     x1, y1, x2, y2 = region
#     boxes = [
#         box for box in task.all_texts
#         if x1 <= (box.x + box.width / 2) / task.width <= x2
#         and y1 <= (box.y + box.height / 2) / task.height <= y2
#         and box.width / task.width <= max_width_ratio
#         and len(box.name) > 2
#     ]
#     columns = []
#     for box in sorted(boxes, key=lambda item: item.x):
#         left = box.x / task.width
#         center_x = (box.x + box.width / 2) / task.width
#         if columns and left - columns[-1]["left"] <= align_tolerance:
#             columns[-1]["centers"].append(center_x)
#             columns[-1]["texts"].append(box.name)
#         else:
#             columns.append({"left": left, "centers": [center_x], "texts": [box.name]})
#     return [
#         {"x": sum(column["centers"]) / len(column["centers"]), "texts": column["texts"]}
#         for column in columns
#     ]


# ------------------------- Frame Stuck Detection -------------------------

def is_frame_stuck(task: TriggerTask, stuck_threshold_seconds=30, change_threshold=0.08):
    """
    Detect whether screen is frozen based on pixel changes.
    Caches _prev_frame_gray and _last_change_time on task.
    Returns True if change ratio < change_threshold for stuck_threshold_seconds.
    stuck_threshold_seconds: threshold in seconds to determine stuck, default 30s
    change_threshold: pixel change ratio threshold between frames, default 0.08 (8%)
    """
    if not hasattr(task, '_last_change_time'):
        task._last_change_time = time.time()
        task._prev_frame_gray = None

    frame = task.frame
    if frame is None:
        return False

    # Downscale grayscale image to reduce computation
    h, w = frame.shape[:2]
    small = cv2.resize(frame, (w // 4, h // 4))
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

    if task._prev_frame_gray is not None and gray.shape == task._prev_frame_gray.shape:
        diff = cv2.absdiff(gray, task._prev_frame_gray)
        _, thresh = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)
        change_ratio = cv2.countNonZero(thresh) / (gray.shape[0] * gray.shape[1])

        if change_ratio >= change_threshold:
            task._last_change_time = time.time()

    task._prev_frame_gray = gray

    return time.time() - task._last_change_time >= stuck_threshold_seconds


def handle_stuck_log(task: TriggerTask):
    """When screen frozen > 10s, sequentially attempt close page, special enemy, cards, or unknown page."""
    if not is_frame_stuck(task, stuck_threshold_seconds=10):
        return False

    stuck_seconds = int(time.time() - task._last_change_time)
    close_page = task.find_one(
        feature_name="close_page",
        box=task.box_of_screen(0.921, 0.003, 0.998, 0.100),
    )
    if close_page:
        task.log_info(
            f"Screen frozen for {stuck_seconds}s, detected close_page feature, clicking to close page"
        )
        task.click_box(close_page)
        task.sleep(1)
        return True

    from utils_sortie import handle_secret_enemy
    handle_secret_enemy(task)
    cards = recognize_cards(task, page="Stuck screen fallback")
    if cards:
        chosen_card = random.choice(cards)
        task.log_info(
            f"Stuck screen fallback: randomly clicking card '{chosen_card['name']}'"
        )
        _move_and_click(task, chosen_card["x"], chosen_card["y"])
    else:
        handle_unknown_page(task)
    # General random screen tap fallback temporarily disabled.
    # click_x = random.uniform(0.059, 0.985)
    # click_y = random.uniform(0.129, 0.981)
    # _move_and_click(task, click_x, click_y)
    task.log_info(f"Screen frozen, elapsed: {stuck_seconds}s")
    return False


# ------------------------- Page Handlers (General) -------------------------
# Convention: each function handles one page, returns True on success, False on miss.

def handle_auto_stop(task: TriggerTask):
    """Auto-stop function: if config 'Stop after N rounds (0 = do not stop)' != 0 and total_rounds reaches limit, auto-disable current task."""
    stop_rounds = _get_config_value(task, '几轮后停止(0为不停止)', 0)
    if stop_rounds and stop_rounds != 0:
        ns = getattr(task, 'node_status', None)
        if ns and ns.get('total_rounds', 0) >= stop_rounds:
            task.log_info(f"Reached configured stop rounds ({stop_rounds}), current total_rounds={ns['total_rounds']}, stopping task automatically")
            task.disable()
            return True
    return False


def log_credit(task: TriggerTask):
    """Record current credits (logging only, does not intercept)."""
    credit = _get_current_credit(task)
    if credit > 0:
        task.info_set("Current Credits", f"{credit}")
    return False


# def handle_stage_clear(task: TriggerTask):
#     """Victory page: check if text at (0.142,0.806) contains 'Battle Ended', success_rounds + 1."""
#     box = find_box_at_point(task, 0.142, 0.806)
#     if box and "Battle Ended" in box.name:
#         task.log_info("Detected victory page, success_rounds + 1")
#         if hasattr(task, 'node_status'):
#             task.node_status['success_rounds'] += 1
#     return False


def log_node_status(task: TriggerTask):
    """Record current win rate and status (logging only, does not intercept)."""
    ns = getattr(task, 'node_status', None)
    if ns:
        try:
            from src.config import version
            app_version = str(version).strip() or "dev"
        except Exception:
            app_version = "dev"
        task.info_set("Version", app_version)
        task.info_set("Game Language", _get_game_language(task))
        total = ns.get('total_rounds', 0)
        node_count = ns.get('node_count', 0)
        node_type = ns.get('node_type', "")
        task.info_set("Floor, Node, Type", f"Floor {ns['pass_final_boss_count']+1}, Node {node_count}, {node_type}")
        task.info_set("Reached Floor Boss", f"{ns['reach_final_boss']}")
        task.info_set("In Floor Boss Battle", f"{ns['final_boss_battle']}")
        task.info_set("Escaped", f"{ns['is_escaped']}")
        task.info_set("Specific Flash Obtained", ns.get("get_specific_flash", False))
        task.info_set("Save Target Portrait", ns.get("save_target_member", False))
        task.info_set("Cards Removed This Run", ns.get("removed_card_count", 0))
        task.info_set("Neutral Cards Acquired", ns.get("neutral_card_count", 0))
        equipment = _equipment_state(task)
        equipment_names = [
            _current_equipment_for_slot(task, equipment, slot)[0]
            for slot in range(3)
        ]
        task.info_set(
            "Equipment Info",
            ", ".join(
                f"Slot {slot + 1}: {name or 'Empty'}"
                for slot, name in enumerate(equipment_names)
            ),
        )
        meditation_state = _member_deck_state(task).get("冥想", {})
        if isinstance(meditation_state, dict):
            for card_name, pending in meditation_state.items():
                task.info_set(f"Meditation: {card_name}", pending)
        if total > 0:
            task.info_set("Current Win Rate", f"{ns['success_rounds']}/{total} ({ns['success_rounds']*100//total}%)")
        else:
            task.info_set("Current Win Rate", f"{ns['success_rounds']}/{total} NaN")
        task.log_info("")
    return False


def handle_battle_crash(task: TriggerTask):
    """Battle info desync / click retry: click screen center to recover."""
    if (find_text(task, r'出现错乱')
            or find_text(task, r'点击重试')
            or find_text(task, r'通讯不稳定.*重新尝试')):
        task.log_info("Battle info desynchronized, clicking to recover")
        _move_and_click(task, 0.5, 0.5)
        return True
    return False


def handle_close_page(task: TriggerTask):
    """Prompt 'Tap Screen' event: tap screen."""
    box = find_text(task, _get_game_text(task, '点击屏幕'))
    if box:
        task.log_info("Tap screen prompt detected, tapping screen")
        task.click_box(box)
        return True
    return False


def handle_refine_equipment_credit(task: TriggerTask):
    """Refine equipment credit page: click 'Accept as Credits'."""
    box = find_box_at_point(task, 0.598, 0.635)
    receive_text = _get_game_text(task, "以信用点接收")
    if box and receive_text in box.name:
        task.log_info(f"Detected refine equipment credit page, clicking {receive_text}")
        task.click_box(box)
        task.sleep(0.5)
        return True
    return False


def handle_center_confirm(task: TriggerTask):
    """Center Confirm button."""
    confirm_region = (0.009, 0.168, 0.977, 0.875)
    box = next(
        (
            text_box
            for text_box in task.all_texts
            if _clean_match(text_box.name, "确认")
            and confirm_region[0]
            <= (text_box.x + text_box.width / 2) / task.width
            <= confirm_region[2]
            and confirm_region[1]
            <= (text_box.y + text_box.height / 2) / task.height
            <= confirm_region[3]
        ),
        None,
    )
    if box:
        task.log_info("Detected center confirm button, clicking confirm")
        task.click_box(box)
        task.sleep(1)
        return True
    return False


def handle_settlement(task: TriggerTask):
    """Settlement button."""
    box = find_box_at_point(task, 0.941, 0.917)
    if box and _clean_match(box.name, "结算"):
        _move_and_click(task, 0.941, 0.917)
        if hasattr(task, 'node_status') and task.node_status.get('reach_final_boss', False):
            task.node_status['pass_final_boss_count'] += 1
            passed = task.node_status['pass_final_boss_count']
            task.log_info(f"Detected boss settlement page and reach_final_boss=True, cleared floor +1 (now: {passed})")
            reset_layer_status(task)
        task.sleep(1)
        return True
    return False


def handle_skip(task: TriggerTask):
    """Skip button."""
    box = find_box_at_point(task, 0.941, 0.917)
    if box and _clean_match(box.name, "跳过"):
        task.log_info("Skip page triggered skip event, clicking Skip button")
        task.click_box(box)
        task.sleep(1)
        return True
    return False


def handle_destiny_choice(task: TriggerTask):
    """Destiny choice reward page: randomly select a destiny title."""
    box = find_box_at_point(task, 0.499, 0.932)
    if box and _get_game_text(task, '请选择你的命运') in box.name:
        task.log_info("Detected destiny choice reward, performing corresponding action")
        task.sleep(2)  # Allow time for buttons to load

        # # Check whether confirm button is already active
        # # Search for "Confirm" text near confirm button click position
        # confirm_box = find_box_at_point(task, 0.884, 0.931)
        # if confirm_box and confirm_box.name == "Confirm":
        #     if is_button_active(task, confirm_box):
        #         task.log_info("Confirm button already active, skipping choice (confirm handled by other logic)")
        #         return False  # Button already active, let other logic click confirm
        # Randomly choose one in destiny title area
        titles = [
            b for b in task.all_texts
            if 0.202 <= (b.x + b.width / 2) / task.width <= 0.800
            and 0.474 <= (b.y + b.height / 2) / task.height <= 0.600
            and len(b.name.strip()) > 1
            and b.name not in ["确认", "返回", "跳过"]
        ]
        if titles:
            chosen = random.choice(titles)
            task.log_info(f"Randomly selected destiny: {chosen.name}")
            task.click_box(chosen)
            task.sleep(1)
            # Do not click confirm after choosing destiny, return False for other handlers
            return True
    return False


def _prioritize_target_member_click(task: TriggerTask, click_positions, search_region):
    """Match target member portrait and move nearest candidate click position to front."""
    if not click_positions:
        task.log_info("Save-farming member match failed: no candidate click positions to bind")
        return click_positions
    if not task.feature_exists("target_member_large"):
        task.log_info("Save-farming member match skipped: target_member_large feature not saved, keeping original member click order")
        return click_positions
    target_member = task.find_one(
        feature_name="target_member_large",
        box=task.box_of_screen(*search_region),
        threshold=0.35,
    )
    if not target_member:
        task.log_info(f"Save-farming member portrait match failed: target_member_large not found in {search_region} (threshold=0.35), keeping original click order")
        return click_positions

    center_x = (target_member.x + target_member.width / 2) / task.width
    center_y = (target_member.y + target_member.height / 2) / task.height
    target_position = min(
        click_positions,
        key=lambda position: (
            (position[0] - center_x) ** 2 + (position[1] - center_y) ** 2
        ),
    )
    task.log_info(f"Save-farming member portrait match succeeded, confidence={target_member.confidence:.4f}, bound click position {target_position} with highest priority")
    return [target_position] + [
        position for position in click_positions if position != target_position
    ]


def handle_main_member_flash(task: TriggerTask):
    """Member flash selection page: try members sequentially until confirm feature appears."""
    box = find_box_at_point(task, 0.495, 0.936)
    if not (box and _get_game_text(task, "请选择获得") in box.name):
        return False

    task.log_info("Detected member flash selection, performing action")
    confirm_box = task.box_of_screen(0.145, 0.044, 0.856, 0.214)
    click_positions = [(0.228, 0.510), (0.504, 0.504), (0.755, 0.508)]
    click_positions = _prioritize_target_member_click(
        task, click_positions, (0.173, 0.232, 0.858, 0.508)
    )

    for cx, cy in click_positions:
        task.log_info(f"Clicking position ({cx}, {cy})")
        _move_and_click(task, cx, cy)
        task.sleep(0.5)

        feature = task.wait_feature(
            "flashmemberconfirm",
            box=confirm_box,
            threshold=0.7,
            time_out=2,
        )
        if feature:
            task.log_info(f"Found flashmemberconfirm after clicking ({cx}, {cy})")
            return True
        task.log_info(f"flashmemberconfirm not found after clicking ({cx}, {cy}), continuing to try")

    task.log_info("flashmemberconfirm not found across all attempts")
    return True


def handle_card_reward(task: TriggerTask):
    """Card reward page: recognize cards by type features and select by priority."""
    page_title = _get_region_text(task, (0.345, 0.012, 0.642, 0.141))
    if "卡牌奖励" not in page_title:
        return False

    task.log_info("Detected card reward screen")
    cards = recognize_cards(task, page="Card reward page")
    if not cards:
        task.log_info("No cards recognized on card reward page, waiting for next frame")
        return True

    target_boxes, target_click_positions = find_target_card(task)
    if target_boxes:
        click_position = target_click_positions[0]
        task.log_info(f"Card reward page: detected target card, clicking position {click_position}")
        _move_and_click(task, *click_position)
        return True

    priority = _get_card_reward_priority(task)

    initial_card_name = _get_config_value(task, "刷初始卡牌", "")
    initial_card_name = initial_card_name.strip() if isinstance(initial_card_name, str) else ""
    node_status = getattr(task, "node_status", {})
    is_initial_node = (
        node_status.get("pass_final_boss_count", 0) == 0
        and node_status.get("node_count", 0) == 0
    )
    if initial_card_name and is_initial_node:
        initial_card = next(
            (card for card in cards if initial_card_name in card["name"]),
            None,
        )
        if initial_card:
            task.log_info(f"Farm starting card matched '{initial_card_name}', clicking card")
            _move_and_click(task, initial_card["x"], initial_card["y"])
            task.sleep(1)
            return True
        task.log_info(f"Farm starting card did not find '{initial_card_name}', pressing ESC to restart")
        _move_and_click(task, 0.960, 0.053)
        task.sleep(1)
        return True

    chosen_card = None
    for pri_name in priority:
        chosen_card = next(
            (
                card for card in cards
                if pri_name
                and pri_name in card["name"]
                and _edit_distance(pri_name, card["name"], max_dist=1)
            ),
            None,
        )
        if chosen_card:
            task.log_info(f"Selected card by priority: {chosen_card['name']} (config: {pri_name})")
            break

    if chosen_card is None:
        refresh_boxes = []
        for box in task.all_texts:
            center_x = (box.x + box.width / 2) / task.width
            center_y = (box.y + box.height / 2) / task.height
            if not (
                0.105 <= center_x <= 0.903
                and 0.764 <= center_y <= 0.851
            ):
                continue
            match = re.fullmatch(r"\s*(\d)\s*/\s*3\s*", box.name)
            if match and int(match.group(1)) != 0:
                refresh_boxes.append((box, int(match.group(1)), 3))
        if refresh_boxes:
            for refresh_box, remaining, maximum in refresh_boxes:
                task.log_info(f"Card reward page: no priority card matched, clicking reroll ({remaining}/{maximum})")
                task.click_box(refresh_box)
            return True

    if chosen_card is None and cards:
        task.log_info("No priority card matched, skipping non-priority cards")
        # Find box containing 'Skip' in (0.620, 0.883, 0.990, 0.983) and click
        skip_box = next((b for b in task.all_texts
                         if 0.620 <= (b.x + b.width / 2) / task.width <= 0.990
                         and 0.883 <= (b.y + b.height / 2) / task.height <= 0.983
                         and "跳过" in b.name), None)
        if skip_box:
            task.log_info("Card reward page triggered skip event, clicking Skip button")
            task.click_box(skip_box)
        else:
            task.log_info("Skip button not found, clicking fixed position")
            _move_and_click(task, 0.745, 0.933)
        task.sleep(0.5)
        return True

    if chosen_card:
        task.log_info(f"Card reward page triggered card selection, clicking '{chosen_card['name']}'")
        _move_and_click(task, chosen_card["x"], chosen_card["y"])
        task.sleep(1)
        return True
    return False


_EQUIPMENT_TYPE_SLOTS = {"攻击力": 0, "防御力": 1, "生命值": 2}
_EQUIPMENT_QUALITY_RANKS = {"": 0, "普通": 1, "史诗": 2, "传说": 3}
_EQUIPMENT_NORMAL_RGB = (61, 76, 138)
_EQUIPMENT_EPIC_RGB = (160, 88, 69)
_EQUIPMENT_EMPTY_RGB = (15, 15, 15)
_EQUIPMENT_RGB_TOLERANCE = 30


def _equipment_slot(task: TriggerTask, type_text):
    """Return equipment index from type text, or None if unrecognized."""
    return next((slot for equipment_type, slot in _EQUIPMENT_TYPE_SLOTS.items()
                 if _get_game_text(task, equipment_type) in type_text), None)


def _equipment_priority(task: TriggerTask, slot):
    """Read priority config for specified equipment slot."""
    priority = _get_config_value(task, f"装备{slot + 1}号位优先级", [])
    return list(priority) if isinstance(priority, (list, tuple)) else []


def _match_equipment_name(ocr_name, priority):
    """Match equipment name using bidirectional inclusion, returning standard name and priority index."""
    if not ocr_name:
        return None, None
    for index, config_name in enumerate(priority):
        if not config_name:
            continue
        if ocr_name in config_name or config_name in ocr_name:
            return config_name, index
    return None, None


def _equipment_rank(name, priority):
    """Return priority index of recorded equipment, placing unlisted equipment after configured ones."""
    _, rank = _match_equipment_name(name, priority)
    return rank if rank is not None else len(priority)


def _equipment_state(task: TriggerTask):
    """Get and correct target member equipment state dictionary."""
    member_status = getattr(task, "member_status", None)
    if not isinstance(member_status, dict):
        member_status = _initial_member_status()
        task.member_status = member_status
    equipment = member_status.setdefault("equipment", {})
    if not isinstance(equipment, dict):
        equipment = {
            "names": ["", "", ""],
            "descriptions": ["", "", ""],
            "qualities": ["", "", ""],
        }
        member_status["equipment"] = equipment
    elif "names" not in equipment or "descriptions" not in equipment:
        old_equipment = equipment
        equipment = {
            "names": ["", "", ""],
            "descriptions": ["", "", ""],
            "qualities": ["", "", ""],
        }
        for equipment_name, description in old_equipment.items():
            for slot in range(3):
                if _match_equipment_name(
                    equipment_name,
                    _equipment_priority(task, slot),
                )[0]:
                    equipment["names"][slot] = equipment_name
                    equipment["descriptions"][slot] = description
                    break
        member_status["equipment"] = equipment
    for key in ("names", "descriptions", "qualities"):
        values = equipment.get(key)
        if not isinstance(values, list):
            values = []
        equipment[key] = (values + ["", "", ""])[:3]
    if not isinstance(member_status.get("deck"), dict):
        member_status["deck"] = {}
    return equipment


def _member_deck_state(task: TriggerTask):
    """Get and correct target member deck state dictionary."""
    member_status = getattr(task, "member_status", None)
    if not isinstance(member_status, dict):
        member_status = _initial_member_status()
        task.member_status = member_status
    deck = member_status.setdefault("deck", {})
    if not isinstance(deck, dict):
        deck = {}
        member_status["deck"] = deck
    return deck


def _reset_meditation_state(task: TriggerTask):
    """Rebuild target member meditation state according to current config."""
    configured_cards = _get_config_value(task, "需要冥想的卡牌", [])
    if not isinstance(configured_cards, (list, tuple)):
        configured_cards = []

    meditation_state = {}
    for card_name in configured_cards:
        normalized_name = str(card_name).strip()
        if normalized_name and normalized_name not in meditation_state:
            meditation_state[normalized_name] = False

    _member_deck_state(task)["冥想"] = meditation_state


def _matching_meditation_card_names(task: TriggerTask, cards):
    """Return meditation config name matching recognized card name."""
    meditation_state = _member_deck_state(task).get("冥想", {})
    if not isinstance(meditation_state, dict):
        return []

    matched_names = []
    for configured_name in meditation_state:
        for card in cards:
            recognized_name = str(card.get("name", "")).strip()
            if (
                recognized_name
                and (configured_name in recognized_name or recognized_name in configured_name)
                and _edit_distance(configured_name, recognized_name, max_dist=1)
            ):
                matched_names.append(configured_name)
                break
    return matched_names


def _current_equipment_for_slot(task: TriggerTask, equipment, slot):
    """Read current equipment name and its priority for given slot."""
    priority = _equipment_priority(task, slot)
    names = equipment.get("names", [])
    equipment_name = names[slot] if slot < len(names) else ""
    if not equipment_name:
        return "", len(priority)
    return equipment_name, _equipment_rank(equipment_name, priority)


def _pixel_rgb(task: TriggerTask, point):
    """Read pixel at normalized coords, converting OpenCV BGR to RGB."""
    if task.frame is None:
        return None
    x = min(task.width - 1, max(0, round(point[0] * task.width)))
    y = min(task.height - 1, max(0, round(point[1] * task.height)))
    blue, green, red = (int(value) for value in task.frame[y, x, :3])
    return red, green, blue


def _rgb_is_close(rgb, target, tolerance=_EQUIPMENT_RGB_TOLERANCE):
    """Determine whether all RGB channels fall within specified tolerance."""
    return rgb is not None and all(
        abs(value - expected) <= tolerance
        for value, expected in zip(rgb, target)
    )


def _equipment_quality_at(task: TriggerTask, point, allow_empty=False):
    """Recognize equipment quality by point color; slot can additionally identify empty slot."""
    rgb = _pixel_rgb(task, point)
    if rgb is None:
        return None, None
    if allow_empty and _rgb_is_close(rgb, _EQUIPMENT_EMPTY_RGB):
        return "", rgb
    if _rgb_is_close(rgb, _EQUIPMENT_NORMAL_RGB):
        return "普通", rgb
    if _rgb_is_close(rgb, _EQUIPMENT_EPIC_RGB):
        return "史诗", rgb
    return "传说", rgb


def _member_equipment_qualities(task: TriggerTask, level_box):
    """Read qualities of member's 3 equipment slots relative to level text."""
    level_center_x = (level_box.x + level_box.width / 2) / task.width
    level_center_y = (level_box.y + level_box.height / 2) / task.height
    relative_offsets = (
        (0.130, -0.0655),
        (0.201, -0.0665),
        (0.270, -0.0655),
    )
    qualities = []
    for slot, (offset_x, offset_y) in enumerate(relative_offsets):
        point = (level_center_x + offset_x, level_center_y + offset_y)
        quality, rgb = _equipment_quality_at(task, point, allow_empty=True)
        qualities.append(quality)
        task.log_info(
            f"Equipment slot {slot + 1} color RGB={rgb}, quality={quality or 'Not equipped'}"
        )
    return qualities


def _should_install_equipment(task, current_name, current_quality, new_equipment):
    """Compare equipment priority first, then quality if priority is tied."""
    priority = new_equipment["priority"]
    _, current_rank = _match_equipment_name(current_name, priority)
    new_rank = new_equipment["rank"]
    if new_rank is not None or current_rank is not None:
        if new_rank is not None and (
            current_rank is None or new_rank < current_rank
        ):
            return True, "Configured priority is higher"
        if current_rank is not None and (
            new_rank is None or current_rank < new_rank
        ):
            return False, "Current equipment priority is higher"

    current_quality_rank = _EQUIPMENT_QUALITY_RANKS.get(current_quality or "", 0)
    new_quality_rank = _EQUIPMENT_QUALITY_RANKS.get(
        new_equipment.get("quality") or "", 0
    )
    return (
        new_quality_rank > current_quality_rank,
        f"Quality {new_equipment.get('quality') or 'Unknown'} {'higher than' if new_quality_rank > current_quality_rank else 'not higher than'} {current_quality or 'Not equipped'}",
    )


def _equipment_info(task: TriggerTask, name_region, type_region, description_region):
    """Read equipment name, type, and description from region, parsing slot, quality, and priority."""
    ocr_name = _get_region_text(task, name_region).strip()
    type_text = _get_region_text(task, type_region).strip()
    description = _get_region_text(task, description_region).strip()
    if not ocr_name or not type_text:
        return None
    slot = _equipment_slot(task, type_text)
    if slot is None:
        return None
    priority = _equipment_priority(task, slot)
    canonical_name, rank = _match_equipment_name(ocr_name, priority)
    quality, quality_rgb = _equipment_quality_at(task, (0.117, 0.409))
    task.log_info(f"Candidate equipment RGB={quality_rgb}, quality={quality or 'Unknown'}")
    return {
        "ocr_name": ocr_name,
        "name": canonical_name or ocr_name,
        "type": type_text,
        "description": description,
        "slot": slot,
        "priority": priority,
        "rank": rank,
        "quality": quality,
    }


def _find_member_level_tags(task: TriggerTask, region, page="Member selection page"):
    """Recognize leveltag in region, deduplicate by position, and return up to 3 top-to-bottom."""
    level_tags = task.find_feature(
        feature_name="leveltag",
        box=task.box_of_screen(*region),
        threshold=0.7,
    ) or []
    deduplicated_level_tags = []
    for level_tag in sorted(
        level_tags,
        key=lambda feature: feature.confidence,
        reverse=True,
    ):
        level_center_x = level_tag.x + level_tag.width / 2
        level_center_y = level_tag.y + level_tag.height / 2
        if any(
            (
                (level_center_x - (kept.x + kept.width / 2)) ** 2
                + (level_center_y - (kept.y + kept.height / 2)) ** 2
            ) ** 0.5
            < max(level_tag.width, level_tag.height, kept.width, kept.height)
            for kept in deduplicated_level_tags
        ):
            continue
        deduplicated_level_tags.append(level_tag)

    kept_level_tags = sorted(
        deduplicated_level_tags,
        key=lambda feature: feature.y,
    )[:3]
    task.log_info(
        f"{page} recognized {len(level_tags)} leveltag features, retained {len(kept_level_tags)} after deduplication"
    )
    for index, level_tag in enumerate(kept_level_tags, 1):
        task.log_info(
            f"Member #{index} leveltag: "
            f"center=({(level_tag.x + level_tag.width / 2) / task.width:.4f}, "
            f"{(level_tag.y + level_tag.height / 2) / task.height:.4f}), "
            f"confidence={level_tag.confidence:.4f}"
        )
    return kept_level_tags


def _find_target_member_index(
    task: TriggerTask,
    lv_texts,
    region,
    feature_name="target_member_small",
):
    """Match target member portrait in region, returning nearest level text index."""
    if not lv_texts or not task.feature_exists(feature_name):
        return None
    target_member_box = task.find_one(
        feature_name=feature_name,
        box=task.box_of_screen(*region),
        threshold=0.4,
    )
    if not target_member_box:
        return None

    target_center_x = target_member_box.x + target_member_box.width / 2
    target_center_y = target_member_box.y + target_member_box.height / 2
    target_member_index = min(
        range(len(lv_texts)),
        key=lambda index: (
            (lv_texts[index].x + lv_texts[index].width / 2 - target_center_x) ** 2
            + (lv_texts[index].y + lv_texts[index].height / 2 - target_center_y) ** 2
        ),
    )
    task.log_info(
        f"Save-farming member portrait match succeeded, confidence={target_member_box.confidence:.4f}, bound member {target_member_index + 1}"
    )
    return target_member_index


def handle_equipment(task: TriggerTask):
    """Equipment selection/equip screen: select by slot priority, maintaining target member equipment state."""
    title = find_box_at_point(task, 0.499, 0.126)
    if not (title and title.name == "装备"):
        return False

    task.log_info("Detected equipment screen")
    equipment = _equipment_state(task)
    equip_hint = find_box_at_point(task, 0.921, 0.135)

    if equip_hint and _get_game_text(task, '请选择主战员') in equip_hint.name:
        task.log_info("Detected equip screen")
        purchase_bottom_boxes = [
            box for box in task.all_texts
            if 0.013 <= (box.x + box.width / 2) / task.width <= 0.992
            and 0.881 <= (box.y + box.height / 2) / task.height <= 0.994
            and box.name.strip()
        ]
        cancel_box = next(
            (box for box in purchase_bottom_boxes if "取消" in box.name), None
        )
        purchase_box = next(
            (box for box in purchase_bottom_boxes if "购买" in box.name), None
        )
        price_box = next(
            (box for box in purchase_bottom_boxes
             if re.fullmatch(r"\d+", box.name.strip())),
            None,
        )
        is_purchase_page = bool(cancel_box and purchase_box)
        equipment_price = None
        current_credit = None
        if is_purchase_page:
            task.log_info("Detected purchase equipment screen")
            equipment_price = (
                _parse_discounted_price(price_box.name) if price_box else None
            )
            current_credit = _get_current_credit(task)
            task.log_info(
                f"Purchase equipment screen: credits={current_credit}, OCR price='{price_box.name if price_box else ''}', actual price={equipment_price}"
            )
            if equipment_price is None:
                task.log_info("Purchase equipment price not recognized, continuing purchase assuming price <= credits")
            elif equipment_price > current_credit:
                task.log_info(
                    f"Equipment price {equipment_price} exceeds credits {current_credit}, clicking Cancel"
                )
                task.click_box(cancel_box)
                task.sleep(1)
                return True

        bottom_buttons = [
            box for box in task.all_texts
            if 0.563 <= (box.x + box.width / 2) / task.width <= 0.998
            and 0.881 <= (box.y + box.height / 2) / task.height <= 0.997
            and box.name.strip()
        ]
        refine_boxes = [box for box in bottom_buttons if "提炼" in box.name]
        if refine_boxes and len(refine_boxes) == len(bottom_buttons):
            task.log_info("Equip screen has only refine button, clicking refine directly")
            task.click_box(refine_boxes[0])
            return True

        new_equipment = _equipment_info(
            task,
            (0.217, 0.379, 0.469, 0.436),
            (0.188, 0.444, 0.323, 0.489),
            (0.179, 0.492, 0.542, 0.668),
        )
        if not new_equipment:
            task.log_info("Failed to recognize equipment name or type to equip")
            if is_purchase_page:
                task.log_info("Purchase equipment cannot identify equipment info, clicking Cancel")
                task.click_box(cancel_box)
                task.sleep(1)
                return True
            return False
        equipment_desc = new_equipment["description"]
        task.log_info(f"Equipment to equip description: '{equipment_desc}'")

        lv_texts = _find_member_level_tags(
            task,
            (0.609, 0.290, 0.652, 0.789),
            page="Equip equipment page",
        )
        target_member_index = _find_target_member_index(
            task,
            lv_texts,
            (0.607, 0.192, 0.739, 0.856),
            feature_name="target_member_tiny",
        )
        tracks_target_member = "刷存档主战员" in getattr(task, "default_config", {})
        preferred_member_index = (
            target_member_index if tracks_target_member else (0 if lv_texts else None)
        )

        slot = new_equipment["slot"]
        current_name, _ = _current_equipment_for_slot(task, equipment, slot)
        current_quality = equipment["qualities"][slot]
        should_install_first = False
        install_reason = "Target member not found"
        if preferred_member_index is not None:
            live_qualities = _member_equipment_qualities(
                task, lv_texts[preferred_member_index]
            )
            for equipment_slot, live_quality in enumerate(live_qualities):
                if live_quality is None:
                    continue
                equipment["qualities"][equipment_slot] = live_quality
                if not live_quality:
                    if equipment["names"][equipment_slot]:
                        task.log_info(
                            f"Equipment slot {equipment_slot + 1} is empty, clearing recorded equipment"
                            f"「{equipment['names'][equipment_slot]}」"
                        )
                    equipment["names"][equipment_slot] = ""
                    equipment["descriptions"][equipment_slot] = ""
            current_name, _ = _current_equipment_for_slot(task, equipment, slot)
            current_quality = equipment["qualities"][slot]
            should_install_first, install_reason = _should_install_equipment(
                task,
                current_name,
                current_quality,
                new_equipment,
            )
            has_legendary_in_other_slot = any(
                quality == "传说" and equipment_slot != slot
                for equipment_slot, quality in enumerate(live_qualities)
            )
            if (
                new_equipment["quality"] == "传说"
                and has_legendary_in_other_slot
            ):
                should_install_first = False
                install_reason = "Member already has legendary equipment in another slot"
                task.log_info("Target member already has legendary equipment, equipping new legendary to another member")

        if should_install_first and preferred_member_index is not None:
            chosen = lv_texts[preferred_member_index]
            if not tracks_target_member or target_member_index is not None:
                equipment["names"][slot] = new_equipment["name"]
                equipment["descriptions"][slot] = equipment_desc
                equipment["qualities"][slot] = new_equipment["quality"] or ""
            member_label = (
                "刷存档主战员"
                if target_member_index is not None
                else "第一主战员"
            )
            task.log_info(
                f"Slot {slot + 1} equipment '{new_equipment['name']}' is better than current '{current_name}', reason={install_reason}, equipping to {member_label}"
            )
            _move_and_click(task, 0.756, (chosen.y + chosen.height / 2) / task.height)
            task.sleep(1)
            if is_purchase_page:
                task.log_info(
                    f"Purchase equipment assigned, price={equipment_price}, credits={current_credit}, clicking Purchase"
                )
                task.click_box(purchase_box)
                task.sleep(1)
                return True
            return False

        other_members = [
            level_box for index, level_box in enumerate(lv_texts)
            if index != preferred_member_index
        ]
        if other_members:
            chosen = random.choice(other_members)
            if tracks_target_member and target_member_index is None:
                task.log_info("Save-farming member not recognized, randomly equipping to another member")
            else:
                task.log_info(
                    f"Slot {slot + 1} no need to replace current '{current_name}', reason={install_reason}, randomly equipping to another member"
                )
            _move_and_click(task, 0.756, (chosen.y + chosen.height / 2) / task.height)
            task.sleep(1)
            if is_purchase_page:
                task.log_info(
                    f"Purchase equipment assigned to other member, price={equipment_price}, credits={current_credit}, clicking Purchase"
                )
                task.click_box(purchase_box)
                task.sleep(1)
                return True
            return False

        if is_purchase_page:
            task.log_info("Purchase equipment cannot be assigned to any member, clicking Cancel")
            task.click_box(cancel_box)
            task.sleep(1)
            return True

        refine_box = next(
            (b for b in task.all_texts
             if 0.522 <= (b.x + b.width / 2) / task.width <= 0.999
             and 0.879 <= (b.y + b.height / 2) / task.height <= 0.996
             and "提炼" in b.name),
            None
        )
        if refine_box:
            task.log_info(f"Slot {slot + 1} no need to replace and no other members available, clicking refine")
            task.click_box(refine_box)
            task.sleep(1)
            return True

        task.log_info("No selectable member or refine button found")
        return False

    candidates = []
    candidate_specs = [
        (
            (0.409, 0.219, 0.678, 0.276),
            (0.384, 0.275, 0.562, 0.319),
            (0.382, 0.324, 0.723, 0.496),
            (0.518, 0.454),
        ),
        (
            (0.410, 0.551, 0.699, 0.608),
            (0.384, 0.613, 0.573, 0.653),
            (0.380, 0.658, 0.720, 0.836),
            (0.521, 0.600),
        ),
    ]
    for name_region, type_region, description_region, click_position in candidate_specs:
        candidate = _equipment_info(
            task, name_region, type_region, description_region
        )
        if not candidate:
            task.log_info("Candidate equipment info incomplete on equip screen, waiting for next frame")
            return True
        candidate["click_position"] = click_position
        candidates.append(candidate)
    task.log_info(
        f"Detected equipment selection screen, candidate equipment: "
        f"{[(candidate['ocr_name'], candidate['slot'] + 1) for candidate in candidates]}"
    )

    chosen_index = None
    for slot in range(3):
        current_name, current_rank = _current_equipment_for_slot(task, equipment, slot)
        for index, candidate in enumerate(candidates):
            if candidate["slot"] != slot or candidate["rank"] is None:
                continue
            if not current_name or candidate["rank"] < current_rank:
                chosen_index = index
                task.log_info(
                    f"Prioritizing slot {slot + 1} equipment '{candidate['name']}', current '{current_name}'"
                )
                break
        if chosen_index is not None:
            break

    if chosen_index is None:
        empty_slot_candidates = [
            candidate for candidate in candidates
            if not _current_equipment_for_slot(task, equipment, candidate["slot"])[0]
        ]
        if empty_slot_candidates:
            chosen_candidate = random.choice(empty_slot_candidates)
            click_position = chosen_candidate["click_position"]
            task.log_info(
                f"No candidate met upgrade conditions, prioritizing vacant slot {chosen_candidate['slot'] + 1} equipment '{chosen_candidate['ocr_name']}'"
            )
        else:
            task.log_info("No candidate met upgrade conditions and slots are occupied, randomly selecting an equipment")
            click_position = random.choice([spec[3] for spec in candidate_specs])
    else:
        click_position = candidates[chosen_index]["click_position"]
    _move_and_click(task, *click_position)
    task.sleep(2)
    return False


# Card operation keyword -> config key mapping
_SELECT_CARD_CONFIG_KEYS = {
    "移除": "移除卡牌列表",
    "复制": "复制卡牌列表",
    "闪光": "闪光卡牌列表",
    "灵光": "闪光卡牌列表",
}


def _scroll_to_target_member_for_card_removal(task: TriggerTask):
    """Scroll member list before removing card until target member appears or bottom reached."""
    feature_name = "target_member_in_select_card"
    page = "Target member search for card removal"
    if not task.feature_exists(feature_name):
        task.log_info(f"{page}: Feature {feature_name} not yet saved, skipping search")
        return

    search_region = (0.079, 0.092, 0.209, 0.675)
    search_box = task.box_of_screen(*search_region)
    scroll_x = (search_region[0] + search_region[2]) / 2
    scroll_y = (search_region[1] + search_region[3]) / 2
    scrollbar_white_ratio = region_white_ratio(
        task, (0.976, 0.119, 0.988, 0.858)
    )
    single_page = scrollbar_white_ratio < 0.01
    task.log_info(
        f"{page}: Scrollbar region white ratio={scrollbar_white_ratio:.2%}, single page={single_page}"
    )

    max_scrolls = 20
    scroll_count = 0
    while True:
        target_member = task.find_one(
            feature_name=feature_name,
            box=search_box,
            threshold=0.5,
        )
        if target_member:
            task.log_info(
                f"{page}: Found target member, confidence={target_member.confidence:.4f}"
            )
            return
        if single_page:
            task.log_info(f"{page}: Single page only, target member not found")
            return
        if _point_is_white(task, 0.982, 0.846, page):
            task.log_info(f"{page}: Reached bottom, target member not found")
            return
        if scroll_count >= max_scrolls:
            task.log_info(f"{page}: Downward scroll reached limit of {max_scrolls}")
            return
        _scroll_card_page(
            task,
            scroll_x,
            scroll_y,
            -3,
            page,
            distance=(search_region[3] - search_region[1]) / 4,
        )
        scroll_count += 1


def handle_select_card(task: TriggerTask):
    """Unified card selection page: detect text at (0.198, 0.039), match config by keywords (remove/copy/flash), and select cards."""
    box = find_box_at_point(task, 0.198, 0.039)
    if not box:
        return False
    m = re.search(r'请选择(\d*)张*.*?(移除|复制|闪光|灵光).*?卡牌', box.name)
    if not m:
        return False
    count_text = m.group(1)
    action = m.group(2)
    count = int(count_text) if count_text else 1
    config_key = _SELECT_CARD_CONFIG_KEYS.get(action)
    if config_key is None:
        return False
    task.log_info(f"Detected card {action} selection, need to select {count} cards, config key={config_key}")

    # Log bottom-right card operation prompt
    action_tip = find_box_at_point(task, 0.945, 0.918)
    if action_tip:
        task.log_info(f"Bottom-right card operation prompt: '{action_tip.name}'")

    if (
        action in ("移除", "复制", "闪光", "灵光")
        and task.name == "自动卡厄思模式"
    ):
        _scroll_to_target_member_for_card_removal(task)

    select_card(task, _get_card_list(task, config_key), count=count, action=action)
    return True


def handle_copy_card_choice(task: TriggerTask):
    """Card duplication selection page: recognize cards by type features and select by priority."""
    box = find_box_at_point(task, 0.498, 0.133)
    copy_card_prompt = _get_game_text(task, "请选择要复制的卡牌")
    if not (box and copy_card_prompt in box.name):
        return False

    task.log_info("Detected card duplication selection page")
    target_boxes, target_click_positions = find_target_card(task)
    if target_boxes:
        click_position = target_click_positions[0]
        task.log_info(
            f"Card duplication selection: detected target card, clicking position {click_position}"
        )
        _move_and_click(task, *click_position)
        return True

    cards = recognize_cards(task, page="Card duplication selection page")

    priority = _get_config_value(task, '复制卡牌列表', [])
    for pri_name in priority:
        for card in cards:
            if card["name"] and pri_name in card["name"]:
                task.log_info(f"Card duplication selection: prioritizing '{card['name']}' (matched '{pri_name}')")
                _move_and_click(task, card["x"], card["y"])
                task.sleep(0.5)
                return True

    task.log_info("Card duplication selection: no priority matched, return False")
    return False


def handle_copy_member(task: TriggerTask):
    """Select member to duplicate card page."""
    box = find_box_at_point(task, 0.502, 0.932)
    copy_member_prompt = _get_game_text(task, "选择要复制卡牌的主战员")
    if not (box and copy_member_prompt in box.name):
        return False

    task.log_info("Detected card duplication member selection event, performing action")

    confirm_box = task.box_of_screen(0.145, 0.044, 0.856, 0.214)
    click_positions = [(0.228, 0.510), (0.504, 0.504), (0.755, 0.508)]
    click_positions = _prioritize_target_member_click(
        task, click_positions, (0.173, 0.232, 0.858, 0.508)
    )

    for i, (cx, cy) in enumerate(click_positions):
        task.log_info(f"Clicking position ({cx}, {cy})")
        _move_and_click(task, cx, cy)
        task.sleep(0.5)

        feature = task.wait_feature("copymemberconfirm", box=confirm_box, time_out=2)
        if feature:
            task.log_info(f"Successfully found copymemberconfirm after clicking ({cx}, {cy})")
            return True
        else:
            task.log_info(f"copymemberconfirm not found after clicking ({cx}, {cy}), continuing to try")

    task.log_info("copymemberconfirm not found across all attempts")
    return True


def handle_convert_card(task: TriggerTask):
    """Convert card page: skip transformation."""
    box = find_box_at_point(task, 0.226, 0.046)
    if box and _get_game_text(task, '转换的卡牌') in box.name:
        task.log_info("Detected card conversion selection, skipping")
        _move_and_click(task, 0.776, 0.926)
        task.sleep(0.5)
        _move_and_click(task, 0.661, 0.632)
        return True
    return False


def handle_negotiation(task: TriggerTask):
    """Negotiation failed page: click next step to skip."""
    title = find_box_at_point(task, 0.498, 0.683)
    if title and title.name in "失败":
        task.log_info("Detected dice roll failure, skipping dice roll")
        _move_and_click(task, 0.665, 0.899)
        return True
    return False


def handle_continue(task: TriggerTask):
    """General Continue button."""
    continue_region = (0.459, 0.858, 0.992, 0.988)
    continue_text = _get_game_text(task, '继续')
    box = next(
        (
            text_box
            for text_box in task.all_texts
            if _clean_match(text_box.name, continue_text)
            and continue_region[0]
            <= (text_box.x + text_box.width / 2) / task.width
            <= continue_region[2]
            and continue_region[1]
            <= (text_box.y + text_box.height / 2) / task.height
            <= continue_region[3]
        ),
        None,
    )
    if box:
        task.log_info("Detected next step prompt, clicking continue")
        task.click_box(box)
        task.sleep(1)
        return True
    return False


def handle_confirm(task: TriggerTask):
    """General Confirm button."""
    confirm_region = (0.267, 0.867, 0.991, 0.979)
    box = next(
        (
            text_box
            for text_box in task.all_texts
            if _clean_match(text_box.name, "确认")
            and confirm_region[0]
            <= (text_box.x + text_box.width / 2) / task.width
            <= confirm_region[2]
            and confirm_region[1]
            <= (text_box.y + text_box.height / 2) / task.height
            <= confirm_region[3]
        ),
        None,
    )
    if box:
        if is_button_active(task, box):
            task.log_info("Detected confirm prompt, clicking confirm")
            task.click_box(box)
            task.sleep(1)
            return True
        else:
            task.log_info("Confirm button inactive (gray), skipping click")
            return False
    return False

def handle_convert(task: TriggerTask):
    """General Convert button: click convert if active, else click skip at (0.776, 0.926)."""
    box = find_box_at_point(task, 0.945, 0.918)
    if box and _clean_match(box.name, "转换"):
        if is_button_active(task, box):
            task.log_info("Detected convert button, clicking convert")
            task.click_box(box)
            task.sleep(1)
            return True
        else:
            task.log_info("Convert button inactive (gray), clicking skip")
            _move_and_click(task, 0.776, 0.926)
            task.sleep(1)
            return True
    return False

def handle_remove(task: TriggerTask):
    """General Remove button."""
    box = find_box_at_point(task, 0.945, 0.918)
    if box and _clean_match(box.name, "移除"):
        if is_button_active(task, box):
            task.log_info("Detected remove prompt, clicking remove")
            task.click_box(box)
            removed_count = max(
                1,
                getattr(task, "_pending_removed_card_count", 0),
            )
            _record_removed_cards(task, removed_count)
            task._pending_removed_card_count = 0
            task.sleep(1)
            return True
        else:
            task.log_info("Remove button inactive (gray), skipping click")
            return False
    return False

def handle_three_choice_card_remove(task: TriggerTask):
    """3-choice card removal page: click active Remove button within specified region."""
    region = (0.507, 0.889, 0.740, 0.967)
    remove_box = next(
        (
            box for box in task.all_texts
            if region[0] <= (box.x + box.width / 2) / task.width <= region[2]
            and region[1] <= (box.y + box.height / 2) / task.height <= region[3]
            and "移除" in box.name
        ),
        None,
    )
    if not remove_box:
        return False
    if not is_button_active(task, remove_box):
        task.log_info("3-choice card removal page remove button inactive (gray), skipping click")
        return False

    task.log_info("Detected 3-choice card removal page, clicking remove")
    task.click_box(remove_box)
    _record_removed_cards(task, 1)
    task._pending_removed_card_count = 0
    return True

def handle_flash(task: TriggerTask):
    """General Flash button."""
    box = find_box_at_point(task, 0.945, 0.918)
    if box and _get_game_text(task, '闪光') in box.name:
        if is_button_active(task, box):
            task.log_info("Detected flash prompt, clicking flash")
            task.click_box(box)
            task.sleep(1)
            return True
        else:
            task.log_info("Flash button inactive (gray), skipping click")
            return False
    return False

def handle_reflash(task: TriggerTask):
    """General Re-flash button."""
    box = find_box_at_point(task, 0.945, 0.918)
    if box and _get_game_text(task, '重新闪光') in box.name:
        if is_button_active(task, box):
            task.log_info("Detected re-flash prompt, clicking re-flash")
            task.click_box(box)
            task.sleep(2)
            return True
        else:
            task.log_info("Re-flash button inactive (gray), skipping click")
            return False
    return False

def handle_grant_flash(task: TriggerTask):
    """General Grant Flash button."""
    box = find_box_at_point(task, 0.945, 0.918)
    if box and _clean_match(box.name, "赋予闪光"):
        if is_button_active(task, box):
            task.log_info("Detected grant flash prompt, clicking grant flash")
            task.click_box(box)
            task.sleep(1)
            return True
        else:
            task.log_info("Grant flash button inactive (gray), skipping click")
            return False
    return False

def handle_copy(task: TriggerTask):
    """General Duplicate button."""
    box = find_box_at_point(task, 0.945, 0.918)
    if box and _clean_match(box.name, "复制"):
        if is_button_active(task, box):
            task.log_info("Detected duplicate prompt, clicking duplicate")
            task.click_box(box)
            task.sleep(1)
            return True
        else:
            task.log_info("Duplicate button inactive (gray), skipping click")
            return False
    return False

def handle_enter(task: TriggerTask):
    """General Enter button."""
    enter_region = (0.017, 0.771, 0.996, 0.992)
    box = next(
        (
            text_box
            for text_box in task.all_texts
            if _clean_match(text_box.name, "进入")
            and enter_region[0]
            <= (text_box.x + text_box.width / 2) / task.width
            <= enter_region[2]
            and enter_region[1]
            <= (text_box.y + text_box.height / 2) / task.height
            <= enter_region[3]
        ),
        None,
    )
    if box:
        task.log_info("Detected enter button, clicking enter")
        task.click_box(box)
        reset_mission_status(task)
        task.sleep(1)
        return True
    return False

def handle_equipment_recast(task: TriggerTask):
    """Equipment recast page: click confirm recast."""
    box = find_box_at_point(task, 0.501, 0.128)
    if box and _get_game_text(task, '装备重铸') in box.name:
        task.log_info("Detected equipment recast page, clicking skip")
        _move_and_click(task, 0.749, 0.932)
        task.sleep(1)
        return True
    return False


def handle_event_task(task: TriggerTask):
    """Event task page: recognize option features and descriptions, selecting according to task priority."""
    bottom_box = find_box_at_point(task, 0.516, 0.971)
    if bottom_box and re.search(r'\d+/\d+', bottom_box.name):
        return False

    rewards = task.find_feature(feature_name="taskreward")
    if rewards:
        reward = rewards[0]
        cx = (reward.x + reward.width / 2) / task.width
        cy = (reward.y + reward.height / 2) / task.height
        if 0.437 <= cx <= 0.902 and 0.350 <= cy <= 0.614:
            task.log_info("Detected task reward icon, prioritizing click")
            task.click_box(reward)
            return True

    tasks_info = recognize_event_options(task, page="Event task page")
    if not tasks_info:
        return False

    selectable_tasks = []
    for task_info in tasks_info:
        event_x = task_info["x"]
        event_y = task_info["y"]
        forbidden_region = (
            max(0.0, event_x - 0.131),
            max(0.0, event_y - 0.257),
            min(1.0, event_x - 0.090),
            min(1.0, event_y - 0.189),
        )
        forbidden_feature = task.find_one(
            feature_name="forbidden_event",
            box=task.box_of_screen(*forbidden_region),
        )
        if forbidden_feature:
            task.log_info(
                f"Event option is forbidden, filtering description '{task_info['description']}', forbidden_event confidence={forbidden_feature.confidence:.4f}"
            )
            continue
        selectable_tasks.append(task_info)
    tasks_info = selectable_tasks
    if not tasks_info:
        task.log_info("All event options are forbidden on event task page, skipping selection")
        return False

    check_region = task.box_of_screen(0.396, 0.286, 0.960, 0.718)
    check_features = [
        feature
        for feature_name in ("check", "check2")
        if (feature := task.find_one(feature_name=feature_name, box=check_region))
    ]
    check_feature = max(
        check_features,
        key=lambda feature: feature.confidence,
        default=None,
    )
    if check_feature:
        task.log_info(
            f"Event task page detected check feature, confidence={check_feature.confidence:.4f}, prioritizing click"
        )
        task.click_box(check_feature)
        task.sleep(1)
        return True

    def click_event_option(event_task):
        left, top, right, bottom = event_task["description_region"]
        description_x = (left + right) / 2
        description_y = (top + bottom) / 2
        _move_and_click(task, description_x, description_y)

    def handle_initial_node_task(description_keyword, purpose):
        """Initial node: select task by description; press ESC to restart if target description not found."""
        matched_task = next(
            (
                task_info
                for task_info in tasks_info
                if description_keyword in task_info["description"]
            ),
            None,
        )
        if matched_task:
            task.log_info(
                f"{purpose}: selecting event task containing '{description_keyword}'"
            )
            click_event_option(matched_task)
        else:
            task.log_info(
                f"{purpose}: event task containing '{description_keyword}' not found, pressing ESC to restart"
            )
            _move_and_click(task, 0.959, 0.053)
        task.sleep(1)
        return True

    upper_event_task = next(
        (task_info for task_info in tasks_info if task_info["y"] < 0.925),
        None,
    )
    if upper_event_task is not None:
        task.log_info(
            f"Detected task with Y < 0.925, immediately selecting: {upper_event_task['description']}"
        )
        click_event_option(upper_event_task)
        task.sleep(1)
        return True

    initial_card_name = _get_config_value(task, "刷初始卡牌", "")
    initial_card_name = initial_card_name.strip() if isinstance(initial_card_name, str) else ""
    node_status = getattr(task, "node_status", {})
    is_initial_node = (
        node_status.get("pass_final_boss_count", 0) == 0
        and node_status.get("node_count", 0) == 0
    )
    reroll_empty_deck = _get_config_value(task, "刷空档", False)
    if initial_card_name and reroll_empty_deck is True and is_initial_node:
        task.log_info("'Farm Starting Card' and 'Farm Empty Slot' cannot run simultaneously; prioritizing 'Farm Starting Card' this round")
    if initial_card_name and is_initial_node:
        return handle_initial_node_task(
            "传说卡牌",
            f"刷初始卡牌「{initial_card_name}」",
        )

    if reroll_empty_deck is True and is_initial_node:
        return handle_initial_node_task("移除2张", "刷空档")

    # Check if treasure feature exists in task area
    treasure_box = task.box_of_screen(0.477, 0.336, 0.841, 0.540)
    treasure_features = task.find_feature(
        feature_name="treasure",
        box=treasure_box,
        threshold=0.7,
    )
    if treasure_features:
        task.log_info("Detected treasure feature in event task area, prioritizing click")
        task.click_box(treasure_features[0])
        task.sleep(2)
        return True

    # Read blacklisted tasks list
    blacklist = _get_config_value(task, '拉黑任务', ["咒术卡牌"])
    blacklist = list(blacklist) if isinstance(blacklist, (list, tuple)) else []
    if blacklist:
        # Filter out tasks whose descriptions contain blacklisted keywords
        filtered_tasks = [
            t for t in tasks_info
            if not any(is_subsequence(bk, t['description']) for bk in blacklist)
        ]
        if len(filtered_tasks) < len(tasks_info):
            task.log_info(f"Blacklisted task keywords: {blacklist}, {len(tasks_info)} before filter, {len(filtered_tasks)} after filter")
            for t in tasks_info:
                if t not in filtered_tasks:
                    task.log_info(f"  Blacklisted: desc: {t['description']}")
        # If all blacklisted, fallback to original list
        if not filtered_tasks:
            task.log_info("All tasks blacklisted, falling back to original list")
            filtered_tasks = tasks_info
        tasks_info = filtered_tasks

    equipment_priority = []
    for slot in range(1, 4):
        equipment_priority.extend(
            _get_card_list(task, f"装备{slot}号位优先级")
        )
    priority = [
        *equipment_priority,
        *_get_card_list(task, "任务优先级"),
    ]
    chosen = None
    for keyword in priority:
        for t in tasks_info:
            if is_subsequence(keyword, t['description']):
                chosen = t
                task.log_info(f"Prioritizing '{keyword}' -> desc: {t['description']}")
                break
        if chosen is not None:
            break

    if chosen is None and task.name == "自动卡厄思模式":
        attack_event_features = task.find_feature(
            feature_name="attack_event",
            threshold=0.95,
        ) or []
        if attack_event_features:
            attack_event = max(
                attack_event_features,
                key=lambda feature: feature.confidence,
            )
            task.log_info(
                f"Task priority not matched, detected attack_event feature, confidence={attack_event.confidence:.4f}, clicking to enter battle task"
            )
            task.click_box(attack_event)
            task.sleep(1)
            return True

    if chosen is None:
        chosen = random.choice(tasks_info)
        task.log_info(
            f"Priority description not matched, randomly selecting from {len(tasks_info)} available tasks: {chosen['description']}"
        )

    click_event_option(chosen)
    task.sleep(1)
    return True


def handle_route_selection(task: TriggerTask):
    """Route selection page: recognize node types, click all nodes sequentially by priority with 1s interval.
    Also tracks node count: increments node_count on leaving route page."""
    position_box = task.box_of_screen(0.335, 0.568, 0.453, 0.751)
    position_feature = task.find_feature(feature_name="position", box=position_box)
    cant_receive = find_box_at_point(task, 0.186, 0.850)
    is_route_page = position_feature or (cant_receive and "无法接收到梦境号" in cant_receive.name)

    # If not on route page but enter_new_node is True (just left route page), increment count
    if not is_route_page:
        if hasattr(task, 'node_status') and task.node_status.get('enter_new_node', False):
            task.node_status['enter_new_node'] = False
            task.node_status['node_count'] += 1
            task.log_info(f"Left route selection page, current node count: {task.node_status['node_count']}")
        return False

    # On route page, mark entering new node
    if hasattr(task, 'node_status'):
        task.node_status['enter_new_node'] = True

    task.log_info("Detected route selection page, clicking nodes sequentially by priority")

    # Update node state: set flash_or_rest=True upon entering route selection page
    if hasattr(task, 'node_status'):
        task.node_status['flash_or_rest'] = True
        task.log_info("Detected route selection page, set node_status['flash_or_rest']=True")
        # Check 'Enter Shop' config; if True, update shop state
        if _get_config_value(task, '进入商店', False):
            task.node_status['shop'] = True
            task.log_info("Enter Shop config is True, set node_status['shop']=True")
    task.sleep(1)

    route_box = task.box_of_screen(0.656, 0.053, 0.977, 0.908)
    node_feature_types = {
        "safezone": "休息",
        "enemy": "小怪",
        "elite": "精英",
        "event": "事件",
        "settlement": "结算",
    }
    nodes = []
    for feature_name, node_type in node_feature_types.items():
        for feature_box in task.find_feature(feature_name=feature_name, box=route_box):
            nodes.append({
                "feature_name": feature_name,
                "node_type": node_type,
                "box": feature_box,
                "special_features": [],
            })

    # When no normal node features are found, current route node is boss.
    if not nodes:
        task.log_info("Detected final boss node, clicking enter")
        if hasattr(task, 'node_status'):
            task.node_status['reach_final_boss'] = True
            task.node_status['node_type'] = "boss"

        # Check 'Auto-pause before floor boss' config
        pause_config = _get_config_value(task, '第几层boss前自动暂停', "不暂停")
        if pause_config != "不暂停":
            try:
                pause_layer = int(pause_config)
                current_layer = task.node_status.get('pass_final_boss_count', 0)
                if pause_layer - 1 == current_layer:
                    task.log_info(f"Configured to pause before floor {pause_layer} boss (cleared {current_layer}), pausing tool")
                    from ok import og
                    og.executor.pause()
                    task.sleep(5)
                    return True
            except (ValueError, TypeError):
                pass

        _move_and_click(task, 0.815, 0.492)
        task.sleep(2)
        return True

    def relative_center(box):
        return (
            (box.x + box.width / 2) / task.width,
            (box.y + box.height / 2) / task.height,
        )

    # Special feature priority: negative numbers higher than normal nodes, positive lower.
    special_feature_priorities = {
        "shop": -1,
        "kalei": -1,
        "seal": -1,
        "hard": 1,
    }

    # Each special feature belongs to nearest node type feature.
    for special_name in special_feature_priorities:
        for special_box in task.find_feature(feature_name=special_name, box=route_box):
            special_x, special_y = relative_center(special_box)
            nearest_node = min(
                nodes,
                key=lambda node: (
                    (relative_center(node["box"])[0] - special_x) ** 2
                    + (relative_center(node["box"])[1] - special_y) ** 2
                ),
            )
            nearest_node["special_features"].append(special_name)
            task.log_info(
                f"Special feature '{special_name}' assigned to '{nearest_node['node_type']}' node"
            )

    priority = _get_route_priority(task)
    task.log_info(f"Route priority config: {priority}")
    task.log_info(
        f"Recognized route nodes: "
        f"{[(node['node_type'], node['special_features']) for node in nodes]}"
    )

    priority_index = {node_type: index for index, node_type in enumerate(priority)}

    def sort_key(node):
        # Shop node has fixed highest priority, unaffected by user configured node order.
        shop_priority = 0 if "shop" in node["special_features"] else 1
        if node["node_type"] == "结算":
            type_priority = len(priority) + 1
        else:
            type_priority = priority_index.get(node["node_type"], len(priority))
        special_priority = min(
            (special_feature_priorities[name] for name in node["special_features"]),
            default=0,
        )
        center_x, center_y = relative_center(node["box"])
        return shop_priority, type_priority, special_priority, center_y, center_x

    # Plan route via minimap connectivity first, verify with right-side clickable nodes.
    # When inconsistent, fallback to current node recognition result.
    map_info = recognize_map_connections(task)
    route_plan = find_best_map_route_by_priority(map_info, priority)
    visible_nodes = sorted(nodes, key=lambda item: relative_center(item["box"])[1])
    node = None
    if route_plan and route_plan["next_row"] is not None:
        planned_index = route_plan["next_row"] - 1
        if 0 <= planned_index < len(visible_nodes):
            planned_node = visible_nodes[planned_index]
            expected_specials = {
                name.removesuffix("_in_map")
                for name in route_plan["next_special_features"]
            }
            actual_specials = set(planned_node["special_features"])
            type_matches = (
                planned_node["node_type"] == route_plan["next_node_type"]
            )
            specials_match = actual_specials == expected_specials
            task.log_info(
                f"Minimap planned route={route_plan['route']}, next col row {route_plan['next_row']}, expected={route_plan['next_node_type']}+{sorted(expected_specials)}, actual={planned_node['node_type']}+{sorted(actual_specials)}"
            )
            if type_matches and specials_match:
                node = planned_node
                task.log_info("Minimap plan matches current node recognition, proceeding by plan")
            else:
                task.log_info("Minimap plan inconsistent with current node recognition, using route priority fallback")
        else:
            task.log_info(
                f"Minimap requires entering next col row {route_plan['next_row']}, but only {len(visible_nodes)} nodes recognized, using priority fallback"
            )
    else:
        task.log_info("Minimap route planning failed, using current node route priority fallback")

    if node is None:
        node = sorted(nodes, key=sort_key)[0]

    # Update node_type to highest priority node type
    if hasattr(task, 'node_status'):
        task.node_status['node_type'] = node["node_type"]
        task.log_info(f"Updated node_type to '{node['node_type']}'")

    center_x, center_y = relative_center(node["box"])
    click_x = center_x - 0.095
    click_y = center_y - 0.0065
    task.log_info(
        f"Clicking {node['node_type']} node (specials: {node['special_features']}, pos: {click_x:.3f}, {click_y:.3f})"
    )
    _move_and_click(task, click_x, click_y)

    task.sleep(2)

    return True


def handle_obtain_reward(task: TriggerTask):
    """Claim reward page: click claim. If reach_final_boss is True, final boss was defeated; increment floor and reset floor state."""
    box = find_box_at_point(task, 0.924, 0.922)
    if box and _clean_match(box.name, "获得"):
        task.log_info("Detected claim reward page, clicking claim")
        task.click_box(box)
        task.sleep(1)
        return True
    return False


def handle_leave(task: TriggerTask):
    """Leave button."""
    box = find_box_at_point(task, 0.945, 0.918)
    if box and _clean_match(box.name, "离开"):
        if is_button_active(task, box):
            task.log_info("Detected leave button, clicking leave")
            task.click_box(box)
            task.sleep(1)
            return True
        else:
            task.log_info("Leave button inactive (gray), skipping click")
            return False
    return False
def handle_next_step(task: TriggerTask):
    """General Next Step button: match text within (0.833,0.885,0.954,0.957) with edit distance <= 2."""
    x1, y1, x2, y2 = 0.833, 0.885, 0.954, 0.957
    for b in task.all_texts:
        cx = (b.x + b.width / 2) / task.width
        cy = (b.y + b.height / 2) / task.height
        if x1 <= cx <= x2 and y1 <= cy <= y2:
            if _edit_distance(b.name, "下一步", max_dist=2):
                task.log_info(f"Detected next step button '{b.name}', clicking")
                task.click_box(b)
                task.sleep(1)
                return True
    return False


def handle_craft(task: TriggerTask):
    """Craft button."""
    box = find_box_at_point(task, 0.938, 0.903)
    if box and _clean_match(box.name, "合成"):
        if is_button_active(task, box):
            task.log_info("Detected craft button, clicking craft")
            task.click_box(box)
            task.sleep(1)
            return True
        else:
            task.log_info("Craft button inactive (gray), skipping click")
            return False
    return False

def handle_select(task: TriggerTask):
    """General Select button."""
    box = find_box_at_point(task, 0.945, 0.918)
    if box and _clean_match(box.name, "选择"):
        if is_button_active(task, box):
            task.log_info("Detected select button, clicking select")
            task.click_box(box)
            task.sleep(1)
            return True
        else:
            task.log_info("Select button inactive (gray), skipping click")
            return False
    return False


def _find_rest_feature(task: TriggerTask):
    """Find rest feature in rest area, logging confidence on hit."""
    search_box = task.box_of_screen(0.157, 0.503, 0.467, 0.863)
    rest_feature = task.find_one(feature_name="rest", box=search_box)
    if rest_feature:
        task.log_info(f"Detected rest feature, confidence: {rest_feature.confidence:.2%}")
    return rest_feature


def _wait_for_rest_confirm(task: TriggerTask):
    """Wait for confirm button after rest action."""
    confirm_boxes = task.wait_ocr(
        0.170, 0.554, to_x=0.855, to_y=0.769,
        match=re.compile(r"确认"), time_out=2,
    )
    if not confirm_boxes:
        task.log_info("Timed out waiting for rest confirm button")
        return False
    return True


def handle_rest(task: TriggerTask):
    """Rest screen: choose rest or meditation based on HP, credits, and meditation state."""
    rest_feature = _find_rest_feature(task)
    free_text = _get_region_text(task, (0.154, 0.602, 0.359, 0.847))
    flash_or_rest = (
        hasattr(task, 'node_status')
        and task.node_status.get('flash_or_rest', False)
    )
    can_rest = bool(rest_feature and "免费" in free_text and flash_or_rest)

    meditation_region = (0.671, 0.433, 0.945, 0.801)
    meditate_feature = task.find_one(
        feature_name="meditate",
        box=task.box_of_screen(*meditation_region),
    )
    meditation_cost_boxes = [
        text_box for text_box in task.all_texts
        if re.fullmatch(r"\d+", text_box.name.strip())
        and meditation_region[0] <= (text_box.x + text_box.width / 2) / task.width <= meditation_region[2]
        and meditation_region[1] <= (text_box.y + text_box.height / 2) / task.height <= meditation_region[3]
    ]
    if meditate_feature and meditation_cost_boxes:
        feature_center = (
            meditate_feature.x + meditate_feature.width / 2,
            meditate_feature.y + meditate_feature.height / 2,
        )
        meditation_cost_box = min(
            meditation_cost_boxes,
            key=lambda text_box: (
                (text_box.x + text_box.width / 2 - feature_center[0]) ** 2
                + (text_box.y + text_box.height / 2 - feature_center[1]) ** 2
            ),
        )
        meditation_cost = int(meditation_cost_box.name.strip())
    else:
        meditation_cost = None

    meditation_state = _member_deck_state(task).get("冥想", {})
    has_pending_meditation = (
        isinstance(meditation_state, dict)
        and any(value is True for value in meditation_state.values())
    )
    current_credit = _get_current_credit(task)
    meditation_credit_threshold = _get_config_value(
        task, "多少信用点以上冥想", 300,
    )
    try:
        meditation_credit_threshold = int(meditation_credit_threshold)
    except (TypeError, ValueError):
        meditation_credit_threshold = 300
    can_meditate = bool(
        flash_or_rest
        and meditate_feature
        and meditation_cost is not None
        and has_pending_meditation
        and current_credit > meditation_credit_threshold
        and current_credit > meditation_cost
    )

    if can_rest and can_meditate:
        hp_percent = _get_current_hp_percent(task)
        choose_rest = hp_percent is not False and hp_percent < 50
        task.log_info(
            f"Both rest and meditation available, current HP={hp_percent if hp_percent is not False else 'unrecognized'}%, choosing {'Rest' if choose_rest else 'Meditation'}"
        )
    else:
        choose_rest = can_rest

    if choose_rest:
        task.log_info("Detected rest screen, clicking rest")
        task.move_relative(
            (rest_feature.x + rest_feature.width / 2) / task.width,
            (rest_feature.y + rest_feature.height / 2) / task.height,
        )
        task.click_box(rest_feature)
        if not _wait_for_rest_confirm(task):
            return True
        task.node_status['flash_or_rest'] = False
        return True

    if can_meditate:
        pending_cards = [
            name for name, pending in meditation_state.items() if pending is True
        ]
        task.log_info(
            f"Detected cards available for meditation {pending_cards}, credits={current_credit}, cost={meditation_cost}, clicking meditation"
        )
        task.click_box(meditate_feature)
        if not _wait_for_rest_confirm(task):
            return True
        task.node_status['flash_or_rest'] = False
        return True

    if rest_feature and "免费" not in free_text:
        task.log_info("Detected rest feature, but 'Free' not found in rest region, skipping click")

    # Check if Delang Shop should be entered
    shop_box = find_box_at_point(task, 0.360, 0.138)
    if shop_box and "德朗商店" in shop_box.name and hasattr(task, 'node_status') and task.node_status.get('shop', False):
        task.log_info("Detected Delang Shop with node_status['shop']=True, entering shop")
        task.click_box(shop_box)
        task.sleep(2)
        return True
    return False


def handle_shop(task: TriggerTask):
    """Delang Shop: prioritize card removal, then purchase cards/equipment by config, finally try free refresh."""
    box = find_box_at_point(task, 0.729, 0.261)
    soldout = find_box_at_point(task, 0.727, 0.286)
    if (box and "移除卡牌" in box.name) or (soldout and "售" in soldout.name):
        task.log_info("handle_shop: page identified (remove card or sold out)")
        if soldout and "售" in soldout.name:
            task.log_info("Delang Shop: card removal sold out")
            task.node_status['shop'] = False
        else:
            current_credit = _get_current_credit(task)
            removed_card_count = task.node_status.get("removed_card_count", 0)
            task.log_info(f"handle_shop: current credits={current_credit}")
            cost_box = find_box_at_point(task, 0.724, 0.319)
            task.log_info(f"handle_shop: cost text at (0.724, 0.319)='{cost_box.name if cost_box else None}'")
            if cost_box and cost_box.name.isdigit():
                cost = int(cost_box.name)
                if removed_card_count >= 5:
                    task.log_info(f"Cards removed this run ({removed_card_count}) reached limit of 5, no longer removing cards with credits")
                elif cost <= current_credit and task.node_status['shop'] is True:
                    task.log_info(f"Delang Shop: remove card costs {cost} credits, current {current_credit}, sufficient, clicking remove")
                    task.click_box(box)
                    task.sleep(1)
                    task.node_status['shop'] = False
                    return True
                else:
                    task.log_info(f"Delang Shop: remove card costs {cost} credits, current {current_credit}, insufficient, browsing other items")
            else:
                task.log_info("handle_shop: failed to read card removal cost, browsing other items")
            task.node_status['shop'] = False

        current_credit = _get_current_credit(task)
        task.log_info(f"Delang Shop browsing items: current credits={current_credit}")
        credit_icons = sorted(
        task.find_feature(
            feature_name="credit_icon",
            box=task.box_of_screen(0.019, 0.761, 0.979, 0.890),
        ) or [],
        key=lambda feature: feature.x,
        )

        card_type_features = []
        card_type_region = task.box_of_screen(0.032, 0.669, 0.968, 0.799)
        for feature_name in (
            "attack_in_shop",
            "skill_in_shop",
            "enhance_in_shop",
        ):
            for feature in task.find_feature(
            feature_name=feature_name,
            box=card_type_region,
            ) or []:
                card_type_features.append((feature_name, feature))

        card_icon_indexes = set()
        for feature_name, feature in card_type_features:
            if not credit_icons:
                break
            feature_x = feature.x + feature.width / 2
            feature_y = feature.y + feature.height / 2
            closest_index = min(
            range(len(credit_icons)),
            key=lambda index: (
                credit_icons[index].x + credit_icons[index].width / 2 - feature_x
            ) ** 2 + (
                credit_icons[index].y + credit_icons[index].height / 2 - feature_y
            ) ** 2,
            )
            card_icon_indexes.add(closest_index)
            task.log_info(f"Delang Shop: feature {feature_name} bound to credit icon {closest_index + 1}")

        card_priority = _get_card_reward_priority(task)
        equipment_priorities = [_equipment_priority(task, slot) for slot in range(3)]
        for index, credit_icon in enumerate(credit_icons):
            icon_x = (credit_icon.x + credit_icon.width / 2) / task.width
            icon_y = (credit_icon.y + credit_icon.height / 2) / task.height
            price_box = find_box_at_point(task, icon_x + 0.099, icon_y - 0.001)
            price = _parse_discounted_price(price_box.name) if price_box else None
            item_name = _get_region_text(task, (
            max(0.0, icon_x - 0.013),
            max(0.0, icon_y - 0.247),
            min(1.0, icon_x + 0.120),
            min(1.0, icon_y - 0.105),
            )).strip()
            is_card = index in card_icon_indexes
            item_type = "Card" if is_card else "Equipment"
            task.log_info(f"Delang Shop item {index + 1}: type={item_type}, name='{item_name}', price={price}")
            if not item_name or price is None or price >= current_credit:
                continue

            if is_card:
                if _neutral_card_limit_reached(task):
                    neutral_card_count = task.node_status.get(
                        "neutral_card_count", 0,
                    )
                    neutral_card_limit = _neutral_card_limit(task)
                    task.log_info(f"Neutral cards acquired ({neutral_card_count}) reached limit {neutral_card_limit}, skipping shop cards")
                    continue
                matched_name = next(
                (name for name in card_priority
                 if name and (name in item_name or item_name in name)),
                None,
                )
            else:
                matched_name = next(
                (canonical_name
                 for priority in equipment_priorities
                 for canonical_name, rank in [_match_equipment_name(item_name, priority)]
                 if rank is not None),
                None,
                )
            if not matched_name:
                continue

            task.log_info(
            f"Delang Shop: {item_type} '{item_name}' matched config '{matched_name}', price {price} < credits {current_credit}, clicking credit icon"
            )
            task.click_box(credit_icon)
            task.sleep(1)
            return True

        free_box = next(
        (text_box for text_box in task.all_texts
         if 0.012 <= (text_box.x + text_box.width / 2) / task.width <= 0.258
         and 0.892 <= (text_box.y + text_box.height / 2) / task.height <= 0.979
         and "免费" in text_box.name),
        None,
        )
        if free_box:
            task.log_info("Delang Shop has no matching items, clicking 'Free' to reroll")
            task.click_box(free_box)
            task.sleep(1)
            return True
    return False


def handle_view_original(task: TriggerTask):
    """Card flash (view original) event: recognize cards by type features and select by flash priority."""
    box1 = find_box_at_point(task, 0.890, 0.051)
    box2 = find_box_at_point(task, 0.896, 0.131)
    if not ((box1 and (_get_game_text(task, '查看原件') in box1.name or _get_game_text(task, '查看之前的闪光') in box1.name)) or (box2 and (_get_game_text(task, '查看原件') in box2.name or _get_game_text(task, '查看之前的闪光') in box2.name))):
        return False

    cards = recognize_cards(task, page="Card flash page")
    if not cards:
        return False

    flash_priority = []
    for keyword in _get_card_list(task, '闪光优先级'):
        if not isinstance(keyword, str):
            continue
        normalized_keyword = re.sub(r"\s+", "", keyword)
        if normalized_keyword:
            flash_priority.append(normalized_keyword)
    chosen_card = None
    for desc_keyword in flash_priority:
        for card in cards:
            if is_subsequence(
                desc_keyword,
                card['name'] + "：:" + card['description'],
            ):
                chosen_card = card
                task.log_info(f"Prioritizing '{card['name']}' ({desc_keyword})")
                if (
                    _get_config_value(task, "首层刷特定闪光", False) is True
                    and flash_priority
                    and desc_keyword == flash_priority[0]
                ):
                    task.node_status["get_specific_flash"] = True
                    task.log_info("Matched first flash priority item, recorded specific flash obtained")
                break
            if chosen_card:
                break
        if chosen_card:
            break

    target_boxes, target_click_positions = find_target_card(task)
    matched_meditation_cards = _matching_meditation_card_names(task, cards)
    if matched_meditation_cards:
        meditation_state = _member_deck_state(task)["冥想"]
        meditation_completed = chosen_card is None and not target_boxes
        for configured_name in matched_meditation_cards:
            meditation_state[configured_name] = meditation_completed
            task.log_info(
                f"Meditation card '{configured_name}' status updated to {'Pending' if meditation_completed else 'Not needed'}"
            )

    if target_boxes:
        click_position = target_click_positions[0]
        task.log_info(
            f"Card flash event: detected target card, clicking position {click_position}"
        )
        _move_and_click(task, *click_position)
        return True

    if not chosen_card:
        chosen_card = random.choice(cards)
        task.log_info(f"Randomly selected '{chosen_card['name']}'")

    _move_and_click(task, chosen_card['x'], chosen_card['y'])
    return True


def handle_escape(task: TriggerTask):
    """Evacuation page: click evacuate after detecting evacuate button."""
    escape_box = find_box_at_point(task, 0.952, 0.928)
    if escape_box and (
        _get_game_text(task, '逃脱') in escape_box.name
        or "脱逃" in escape_box.name
    ):
        task.log_info("Detected evacuation page, clicking evacuate")
        task.click_box(escape_box)
        task.node_status["is_escaped"] = True
        task.sleep(0.5)
        return True
    return False


# def handle_battle_failed(task: TriggerTask):
#     """Battle defeat page: record failure and reset boss state."""
#     box = find_box_at_point(task, 0.291, 0.718)
#     if box and box.name == "Battle Defeat":
#         task.log_info("Detected battle defeat, recording failure and resetting boss state")
#         if hasattr(task, 'node_status'):
#             task.node_status['total_rounds'] += 1
#             task.log_info(f"Battle defeat, total_rounds={task.node_status['total_rounds']}")
#             task.node_status['pass_final_boss_count'] = 0
#             task.node_status['reach_final_boss'] = False
#             task.node_status['final_boss_battle'] = False
#     return False

def handle_expedition_result(task: TriggerTask):
    """Expedition result page: if (0.625, 0.122) has 'Expedition Result', it is this page.
    If (0.928, 0.122) has 'Complete', success_rounds + 1."""
    expedition_result_text = _get_game_text(task, "探险结果")
    title_box = find_box_at_point(task, 0.625, 0.122)
    if not (title_box and expedition_result_text in title_box.name):
        return False
    task.sleep(2)
    task.all_texts = _simplify_texts(task.ocr())
    title_box = find_box_at_point(task, 0.625, 0.122)
    if not (title_box and expedition_result_text in title_box.name):
        return False

    task.log_info("Detected expedition result page")
    complete_box = find_box_at_point(task, 0.928, 0.122)
    failed_box = find_box_at_point(task, 0.296, 0.719)
    if hasattr(task, 'node_status'):
        task.node_status['total_rounds'] += 1
    if complete_box and "完成" in complete_box.name:
        if hasattr(task, 'node_status'):
            task.node_status['success_rounds'] += 1
            task.log_info("Sortie Mode expedition result: Success")
    elif complete_box and "失败" in complete_box.name:
        if not _get_config_value(task, '只打第一层', False):
            task.log_info("Sortie Mode expedition result: Failed")
        elif task.node_status.get('pass_final_boss_count', 0) == 0:
            task.log_info("Sortie Mode expedition result: Failed")
    elif not complete_box and not failed_box:
        if _get_config_value(task, '只打第一层', False) and task.node_status.get('pass_final_boss_count', 0) >= 1:  # Cleared first floor mission
            task.log_info("Chaos Mode expedition result: Success")
        elif not _get_config_value(task, '只打第一层', False) and not task.node_status.get('is_escaped', 0):  # Completed mission and did not escape
            task.node_status['success_rounds'] += 1
            task.log_info("Chaos Mode expedition result: Success")
        else:
            task.log_info("Chaos Mode expedition result: Failed")
    else:
        task.log_info("Chaos Mode expedition result: Failed")
    task.log_info(f"Expedition complete, success/total runs: {task.node_status['success_rounds']}/{task.node_status['total_rounds']}")
    if hasattr(task, 'node_status'):
        reset_mission_status(task)
    return False


def _initial_node_status():
    """Return initial copy of node_status."""
    return {"shop": False, "flash_or_rest": False, "reach_final_boss": False, "final_boss_battle": False,
            "pass_final_boss_count": 0, "total_rounds": 0, "success_rounds": 0,
            "node_count": 0, "enter_new_node": False, "node_type": "", "is_escaped": False,
            "save_target_member": False, "target_mask_card_position": -1,
            "get_specific_flash": False, "removed_card_count": 0,
            "neutral_card_count": 0}


def _initial_member_status():
    """Return initial copy of target member status."""
    return {
        "equipment": {
            "names": ["", "", ""],
            "descriptions": ["", "", ""],
            "qualities": ["", "", ""],
        },
        "deck": {},
    }


def _finish_only_first_layer(task: TriggerTask) -> bool:
    """Check and perform Floor 1 exit: if pass_final_boss_count >= 1 and 'Floor 1 Only' is True, success_rounds + 1, click exit and return True."""
    if not (
        hasattr(task, 'node_status')
        and task.node_status.get('pass_final_boss_count', 0) >= 1
    ):
        return False

    if (
        _get_config_value(task, "首层刷特定闪光", False) is True
        and task.node_status.get("get_specific_flash", False) is False
    ):
        task.node_status['success_rounds'] += 1
        task.log_info("Specific flash not obtained and Floor 1 cleared, exiting to restart")
        _move_and_click(task, 0.959, 0.051)
        task.sleep(1)
        return True

    if _get_config_value(task, '只打第一层', False):
        task.node_status['success_rounds'] += 1
        task.log_info(f"Floor 1 only mission complete, success_rounds + 1 (current: {task.node_status['success_rounds']}), exiting settlement screen")
        _move_and_click(task, 0.959, 0.051)
        task.sleep(1)
        return True
    return False


def reset_all_status(task: TriggerTask):
    """Reset all status: restore node_status and member_status."""
    if getattr(task, 'node_status', None) is not None:
        task.node_status = _initial_node_status()
    task.member_status = _initial_member_status()
    _reset_meditation_state(task)
    task._pending_removed_card_count = 0


def reset_mission_status(task: TriggerTask):
    """Reset task status: keep task stats and target member feature, reset other states."""
    ns = getattr(task, 'node_status', None)
    if ns is not None:
        keep = {'total_rounds': ns.get('total_rounds', 0),
                'success_rounds': ns.get('success_rounds', 0),
                'save_target_member': ns.get('save_target_member', False)}
        task.node_status = _initial_node_status()
        task.node_status['total_rounds'] = keep['total_rounds']
        task.node_status['success_rounds'] = keep['success_rounds']
        task.node_status['save_target_member'] = keep['save_target_member']
    task.member_status = _initial_member_status()
    _reset_meditation_state(task)
    task._pending_removed_card_count = 0


def reset_layer_status(task: TriggerTask):
    """Reset floor status: keep clear count, task stats, and target member feature."""
    ns = getattr(task, 'node_status', None)
    if ns is not None:
        keep = {'pass_final_boss_count': ns.get('pass_final_boss_count', 0),
                'total_rounds': ns.get('total_rounds', 0),
                'success_rounds': ns.get('success_rounds', 0),
                'save_target_member': ns.get('save_target_member', False),
                'target_mask_card_position': ns.get('target_mask_card_position', -1),
                'get_specific_flash': ns.get('get_specific_flash', False),
                'removed_card_count': ns.get('removed_card_count', 0),
                'neutral_card_count': ns.get('neutral_card_count', 0)}
        task.node_status = _initial_node_status()
        task.node_status['pass_final_boss_count'] = keep['pass_final_boss_count']
        task.node_status['total_rounds'] = keep['total_rounds']
        task.node_status['success_rounds'] = keep['success_rounds']
        task.node_status['save_target_member'] = keep['save_target_member']
        task.node_status['target_mask_card_position'] = keep['target_mask_card_position']
        task.node_status['get_specific_flash'] = keep['get_specific_flash']
        task.node_status['removed_card_count'] = keep['removed_card_count']
        task.node_status['neutral_card_count'] = keep['neutral_card_count']


def handle_close_button(task: TriggerTask):
    """General close button: click close when detected."""
    box = find_box_at_point(task, 0.512, 0.929)
    if box and box.name == "关闭":
        task.log_info("Detected close button, clicking to close")
        task.click_box(box)
        task.sleep(1)
        return True
    return False


def handle_card_assign(task: TriggerTask):
    """Card assignment page: reroll or skip by priority, prioritizing target member."""
    title_box = find_box_at_point(task, 0.863, 0.133)
    assign_prompt = _get_game_text(task, "请选择要接受卡牌的主战员")
    if not (title_box and assign_prompt in title_box.name):
        return False

    task.log_info("Detected card assignment page")

    purchase_title_region = (0.326, 0.057, 0.671, 0.210)
    purchase_title_boxes = [
        b for b in task.all_texts
        if purchase_title_region[0] <= (b.x + b.width / 2) / task.width <= purchase_title_region[2]
        and purchase_title_region[1] <= (b.y + b.height / 2) / task.height <= purchase_title_region[3]
    ]
    is_purchase_page = any("购买卡牌" in b.name for b in purchase_title_boxes)
    purchase_box = None
    cancel_box = None
    card_price = None
    current_credit = None
    if is_purchase_page:
        task.log_info("Detected purchase card page")
        current_credit = _get_current_credit(task)
        purchase_bottom_boxes = [
            b for b in task.all_texts
            if 0.016 <= (b.x + b.width / 2) / task.width <= 0.995
            and 0.878 <= (b.y + b.height / 2) / task.height <= 0.996
        ]
        cancel_box = next((b for b in purchase_bottom_boxes if "取消" in b.name), None)
        purchase_box = next((b for b in purchase_bottom_boxes if "购买" in b.name), None)
        price_box = next(
            (b for b in purchase_bottom_boxes if re.fullmatch(r"\d+", b.name.strip())),
            None,
        )
        if price_box:
            card_price = _parse_discounted_price(price_box.name)
        task.log_info(
            f"Card purchase page: current credits={current_credit}, "
            f"OCR price='{price_box.name if price_box else ''}', actual price={card_price}"
        )

        if not (cancel_box and purchase_box):
            task.log_info("Purchase card page did not fully recognize cancel and purchase buttons")
            if cancel_box:
                task.log_info("Purchase card page triggered recognition failure cancel, clicking Cancel")
                task.click_box(cancel_box)
                task.sleep(1)
                return True
            return False
        if card_price is None:
            task.log_info("Purchase card page did not recognize price, continuing purchase assuming price <= credits")
        if _neutral_card_limit_reached(task):
            neutral_card_count = task.node_status.get("neutral_card_count", 0)
            neutral_card_limit = _neutral_card_limit(task)
            task.log_info(f"Neutral cards acquired ({neutral_card_count}) reached limit {neutral_card_limit}, clicking Cancel")
            task.click_box(cancel_box)
            task.sleep(1)
            return True

    assigned_cards = recognize_cards(
        task,
        region=(0.101, 0.217, 0.291, 0.365),
        page="Card assignment page",
    )
    assigned_card = assigned_cards[0] if assigned_cards else None
    card_name = assigned_card["name"] if assigned_card else ""
    card_desc = assigned_card["description"] if assigned_card else ""
    task.log_info(f"Card to assign: name='{card_name}', desc='{card_desc}'")

    bottom_boxes = [
        b for b in task.all_texts
        if 0.290 <= (b.x + b.width / 2) / task.width <= 0.998
        and 0.878 <= (b.y + b.height / 2) / task.height <= 0.997
    ]
    refresh_text = _get_game_text(task, "刷新")
    refresh_box = next((b for b in bottom_boxes if refresh_text in b.name), None)
    skip_box = next((b for b in bottom_boxes if "跳过" in b.name), None)
    refresh_count = None
    for bottom_box in bottom_boxes:
        count_match = re.search(r'(\d+)/(\d+)', bottom_box.name)
        if count_match:
            refresh_count = (int(count_match.group(1)), int(count_match.group(2)))
            break

    reward_priority_config = _get_card_list(task, "卡牌奖励优先级")
    has_reward_priority = any(
        isinstance(item, str) and item.strip()
        for item in reward_priority_config
    )
    priority = _get_card_reward_priority(task)
    matched_card_name = next(
        (config_name for config_name in priority
         if card_name and config_name
         and (config_name in card_name or card_name in config_name)),
        None,
    )
    if matched_card_name:
        task.log_info(f"Card '{card_name}' matched reward priority '{matched_card_name}'")
    else:
        task.log_info(f"Card '{card_name}' did not match reward priority")
        if is_purchase_page:
            task.log_info("Purchase card did not match reward priority, clicking Cancel")
            task.click_box(cancel_box)
            task.sleep(1)
            return True
        if (
            has_reward_priority
            and refresh_box
            and refresh_count
            and refresh_count[0] > 0
        ):
            task.log_info(f"Remaining rerolls: {refresh_count[0]}/{refresh_count[1]}, clicking reroll")
            task.click_box(refresh_box)
            return True
        if skip_box:
            task.log_info("No rerolls available, skipping non-priority card")
            task.click_box(skip_box)
            return True

    lv_texts = _find_member_level_tags(
        task,
        (0.426, 0.292, 0.473, 0.783),
        page="Card assignment page",
    )
    if not lv_texts:
        task.log_info("Member leveltag feature not found")
        if is_purchase_page:
            task.log_info("Purchase card page found no assignable member, clicking Cancel")
            task.click_box(cancel_box)
            task.sleep(1)
            return True
        return False

    target_member_index = _find_target_member_index(
        task, lv_texts, (0.484, 0.169, 0.652, 0.858)
    )

    available_members = []
    for index, level_box in enumerate(lv_texts):
        level_center_x = (level_box.x + level_box.width / 2) / task.width
        level_center_y = (level_box.y + level_box.height / 2) / task.height
        unavailable_box = find_box_at_point(
            task,
            level_center_x + 0.0615,
            level_center_y - 0.0795,
        )
        if unavailable_box and "无法获得" in unavailable_box.name:
            task.log_info(f"Member {index + 1} cannot receive this card, excluding")
            continue
        available_members.append((index, level_box))

    if not available_members:
        task.log_info("No members can receive this card")
        if is_purchase_page:
            task.log_info("Purchase card cannot be assigned to any member, clicking Cancel")
            task.click_box(cancel_box)
            task.sleep(1)
            return True
        if skip_box:
            task.log_info("Attempting to click skip")
            task.click_box(skip_box)
            return True
        task.log_info("Skip button not found")
        return False

    target_available = next(
        (member for member in available_members if member[0] == target_member_index),
        None,
    )
    chosen_idx, chosen_lv = target_available or available_members[0]
    if target_available:
        task.log_info(f"Prioritizing save-farming member ({chosen_idx + 1}) to receive card")
    else:
        task.log_info(f"Prioritizing member {chosen_idx + 1} to receive card")

    if (
        is_purchase_page
        and card_price is not None
        and current_credit <= card_price
    ):
        task.log_info(
            f"Purchase card costs {card_price} credits, current {current_credit}, insufficient credits, clicking Cancel"
        )
        task.click_box(cancel_box)
        task.sleep(1)
        return True

    tracks_target_member = "刷存档主战员" in getattr(task, "default_config", {})
    if (
        target_member_index is not None and chosen_idx == target_member_index
    ) or (
        not tracks_target_member and chosen_idx == 0
    ):
        deck = _member_deck_state(task)
        deck[matched_card_name or card_name] = card_desc
    _move_and_click(task, 0.756, (chosen_lv.y + chosen_lv.height / 2) / task.height)
    task.sleep(1)
    if is_purchase_page:
        task.log_info(
            f"Purchase card costs {card_price} credits, current {current_credit}, clicking Purchase"
        )
        task.click_box(purchase_box)
        _record_neutral_card(task)
        task.sleep(1)
        return True
    _record_neutral_card(task)
    return False

def handle_held_cards_page(task: TriggerTask):
    """Held cards page: close page when detected."""
    box = find_box_at_point(task, 0.500, 0.056)
    if box and box.name == _get_game_text(task, '持有卡牌'):
        task.log_info("Detected held cards page, clicking to close")
        _move_and_click(task, 0.966, 0.053)
        return True
    return False

def handle_weakness_info(task: TriggerTask):
    """Enemy info page: close page when weakness info detected."""
    box = find_box_at_point(task, 0.387, 0.107)
    if box and "弱点" in box.name:
        task.log_info("Detected enemy info page, clicking to close")
        _move_and_click(task, 0.502, 0.092)
        return True
    return False

def handle_minimizemap(task: TriggerTask):
    """Map page: click to close minimap when detected."""
    boxes = task.find_feature(feature_name="minimizemap")
    if boxes:
        task.log_info("Detected map page, clicking to close minimap")
        task.click_box(boxes[0])
        return True
    return False

def handle_non_battle_page(task: TriggerTask):
    """Non-Sortie/Chaos page: auto-stop current mode if Story/Rescue/Ark City detected (highest priority)."""
    box = find_box_at_point(task, 0.887, 0.160)
    if box and box.name == "故事":
        task.log_info("Detected Story page, stopping current mode")
        task.disable()
        return True
    box = find_box_at_point(task, 0.101, 0.046)
    if box and box.name == "营救":
        task.log_info("Detected Rescue page, stopping current mode")
        task.disable()
        return True
    box = find_box_at_point(task, 0.124, 0.049)
    if box and box.name == "方舟城市":
        task.log_info("Detected Ark City page, stopping current mode")
        task.disable()
        return True
    return False

def handle_unknown_page(task: TriggerTask):
    """Unknown page awaiting confirmation: click random center area if confirm button is unclickable."""
    box = find_box_at_point(task, 0.916, 0.931)
    if box and _clean_match(box.name, "确认") and not is_button_active(task, box):
        task.log_info("Detected unknown page awaiting confirmation with unclickable confirm button, clicking random screen area")
        import random
        rx = random.uniform(0.043, 0.972)
        ry = random.uniform(0.149, 0.843)
        _move_and_click(task, rx, ry)
        task.sleep(1)
        return True
    return False
