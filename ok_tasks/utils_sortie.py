from ok import TriggerTask

from utils import (
    _move_and_click, _simplify_texts, _edit_distance, _get_config_value, _get_card_list, _get_route_priority, _get_game_text,
    find_box_at_point, find_text, recognize_cards,
    _card_has_type_below, select_card, calculate_dominant_hue,
    log_credit, log_node_status, handle_battle_crash, handle_close_page, handle_refine_equipment_credit,
    handle_center_confirm, handle_settlement, handle_skip,
    handle_destiny_choice, handle_main_member_flash,
    handle_card_reward, handle_equipment,
    handle_select_card, handle_copy_member,
    handle_convert_card,
    handle_negotiation, handle_continue, handle_confirm, handle_enter,
    handle_event_task, handle_route_selection, handle_obtain_reward,
    handle_leave, handle_next_step, handle_select, handle_view_original,
    handle_close_button,
    handle_card_assign, handle_non_battle_page,
    handle_remove, handle_three_choice_card_remove, handle_flash, handle_reflash, handle_grant_flash, handle_copy, handle_convert, handle_equipment_recast, handle_weakness_info, handle_minimizemap,
    handle_held_cards_page,
    handle_stuck_log,  # Screen stuck detection and fallback handling, is_button_active, _clean_match,
    handle_shop, handle_expedition_result,
    handle_escape,
    _get_current_credit, _get_current_hp_percent, _get_region_text,
    _find_rest_feature, _wait_for_rest_confirm,
    # handle_stage_clear,
    _finish_only_first_layer,
    handle_auto_stop,
)
from utils_chaos import handle_archive_target_member

import re
import random
import cv2


# ------------------------- Sortie Mode exclusive tools -------------------------

def _get_member_priority(task: TriggerTask):
    """Read member priority config, return list; fallback to default on error."""
    value = _get_config_value(task, '主战员优先级', ["尼娅", "麦格纳", "米卡", "卡修斯"])
    return list(value) if isinstance(value, (list, tuple)) else ["尼娅", "麦格纳", "米卡", "卡修斯"]


def _get_blacklisted_members(task: TriggerTask):
    """Read blacklisted members list, return list; fallback to default on error."""
    value = _get_config_value(task, '拉黑主战员', ["黛安娜", "阿黛尔海特"])
    return list(value) if isinstance(value, (list, tuple)) else ["黛安娜", "阿黛尔海特"]


def _get_battle_member_priority(task: TriggerTask):
    """Read lead member priority config, return list; fallback to default on error."""
    value = _get_config_value(task, "出战主战员优先级", ["海德玛丽", "九", "力", "绯"])
    return list(value) if isinstance(value, (list, tuple)) else ["海德玛丽", "九", "力", "绯"]


def _card_key(text):
    table = str.maketrans("①②③④⑤⑥⑦⑧⑨⑩❶❷❸❹❺❻❼❽❾❿⓵⓶⓷⓸⓹⓺⓻⓼⓽⓾０１２３４５６７８９",
                         "1234567890123456789012345678900123456789")
    text = text.translate(table)
    m = re.search(r"\d", text)
    return m.group(0) if m else None


def _is_card_name(name):
    """Determine if text is card name: exclude card type tags."""
    exclude_keywords = {"攻击", "强化", "技能", "咒术", "基础", "基本", "状态异常", "诅咒"}
    # Texts containing card type keywords are not card names
    if any(kw in name for kw in exclude_keywords):
        return False
    # Texts containing attack keyword with length <= 3 are not card names (e.g. 'X attack', 'basic attack')
    if "攻" in name and len(name) <= 3:
        return False
    return True


def _hand_card_names(task: TriggerTask):
    """Read card names in hand card area, excluding keys and card type tags."""
    x1, y1, x2, y2 = 0.159, 0.683, 0.836, 0.831

    # Print all texts and coordinates to debug hand card area filtering
    task.log_info(f"_hand_card_names region: cx=[{x1}, {x2}], cy=[{y1}, {y2}]")
    for b in task.all_texts:
        cx = (b.x + b.width / 2) / task.width
        cy = (b.y + b.height / 2) / task.height
        in_region = x1 <= cx <= x2 and y1 <= cy <= y2
        has_key = _card_key(b.name)
        name_len = len(b.name.strip())
        task.log_info(f"  OCR: 「{b.name}」 cx={cx:.4f} cy={cy:.4f} in_region={in_region} has_key={has_key} len={name_len}")

    boxes = [b for b in task.all_texts
             if x1 <= (b.x + b.width / 2) / task.width <= x2
             and y1 <= (b.y + b.height / 2) / task.height <= y2]
    result = [b for b in boxes
              if not _card_key(b.name)
              and len(b.name.strip()) > 1
              and _is_card_name(b.name)]
    task.log_info(f"_hand_card_names region: total {len(boxes)} texts, {len(result)} remaining after filter: {[b.name for b in result]}")
    return result


def _hand_cards(task: TriggerTask):
    """Recognize hand cards, returning position-sorted card names and keys, inferring missing keys from spacing."""
    # Keys: containing digits
    keys = [(b.x / task.width, b.y / task.height, _card_key(b.name)) for b in task.all_texts if _card_key(b.name)]
    keys.sort(key=lambda x: x[0])

    # Card names
    card_names = _hand_card_names(task)
    card_names.sort(key=lambda b: b.x)

    # Read hand count
    hand_count = _read_hand_count(task)

    # Pairing: match each card to nearest unused key above-left
    used_keys = set()
    cards = []
    for name_box in card_names:
        cx = name_box.x / task.width
        left_x = (name_box.x) / task.width  # Use left edge coordinate to avoid text length affecting spacing calculation
        cy = name_box.y / task.height

        candidates = []
        for kx, ky, k in keys:
            if k in used_keys:
                continue
            # Vertical: key is 0.03-0.06 above card name
            if not (cy - 0.06 <= ky <= cy - 0.03):
                continue
            # Horizontal: key is left of card name, distance <= 0.025
            if not (cx - 0.025 <= kx <= cx + 0.01):
                continue
            candidates.append((kx, ky, k))

        if candidates:
            best = min(candidates, key=lambda x: cx - x[0])
            used_keys.add(best[2])
            cards.append({"name": name_box.name, "key": best[2], "x": cx, "left_x": left_x})
        else:
            cards.append({"name": name_box.name, "key": None, "x": cx, "left_x": left_x})

    # Infer missing keys: interpolate using minimum adjacent spacing as expected_spacing
    # Calculate based on nearest preceding card with key to avoid accumulated errors
    if len(cards) >= 2:
        sorted_cards = sorted(enumerate(cards), key=lambda x: x[1]["left_x"])
        # Calculate minimum left_x spacing between adjacent cards
        min_spacing = float('inf')
        for i in range(len(sorted_cards) - 1):
            spacing = sorted_cards[i + 1][1]["left_x"] - sorted_cards[i][1]["left_x"]
            if spacing < min_spacing:
                min_spacing = spacing
        expected_spacing = max(0.055, min_spacing)  # Take max of 0.055 and min spacing to prevent division by zero
        task.log_info(f"_hand_cards: minimum spacing={min_spacing:.4f}")
        # Ensure leftmost card has a key; assign 1 if none
        if sorted_cards[0][1]["key"] is None:
            sorted_cards[0][1]["key"] = "1"
            task.log_info(f"_hand_cards: Card '{sorted_cards[0][1]['name']}' left_x={sorted_cards[0][1]['left_x']:.4f} -> Assigning key 1 to leftmost card")
        for i in range(1, len(sorted_cards)):
            idx, c = sorted_cards[i]
            if c["key"] is None:
                # Search backwards for nearest card with an existing key
                for j in range(i - 1, -1, -1):
                    prev_idx, prev_c = sorted_cards[j]
                    if prev_c["key"] is not None:
                        offset = (c["left_x"] - prev_c["left_x"]) / expected_spacing
                        approx_key = int(prev_c["key"]) + round(offset)
                        if 1 <= approx_key <= 9:
                            c["key"] = str(approx_key)
                            task.log_info(f"_hand_cards: Card '{c['name']}' left_x={c['left_x']:.4f} based on '{prev_c['name']}'(key={prev_c['key']}) offset={offset:.2f} -> {c['key']}")
                        else:
                            task.log_info(f"_hand_cards: Card '{c['name']}' left_x={c['left_x']:.4f} based on '{prev_c['name']}'(key={prev_c['key']}) offset={offset:.2f} -> calculated={approx_key} out of range 1-9, not assigned")
                        break
    elif len(cards) == 1:
        if cards[0]["key"] is None:
            cards[0]["key"] = "1"
            task.log_info("_hand_cards: Single card, assigning key 1")

    task.log_info(f"_hand_cards: Recognized {len(cards)} hand cards: {[(c['name'], c['key']) for c in cards]}")
    return cards


def _try_all_card_keys(task: TriggerTask, count):
    """Try all card keys downwards from current hand count as fallback for missed key recognition.
    When hand count is 10, send key 0 first (card 10), then 9 down to 1."""
    task.log_info(f"_try_all_card_keys: hand count={count}")
    if count == 10:
        task.log_info("Hand count is 10, sending key 0 first")
        task.send_key("0")
        task.sleep(0.5)
        task.send_key("enter")
        task.sleep(1)
        start = 9
    else:
        start = min(count, 9)
    task.log_info(f"_try_all_card_keys: sending keys {start} down to 1")
    for index in range(start, 0, -1):
        task.send_key(str(index))
        task.sleep(0.5)
        task.send_key("enter")
        task.sleep(1)


def _read_hand_count(task: TriggerTask):
    """Read current hand card count; correct 3-digit OCR errors by taking last two digits."""
    box = find_box_at_point(task, 0.509, 0.972)
    match = re.search(r"(\d+)/10", box.name) if box else None
    if not match:
        return None
    hand_count_text = match.group(1)
    if len(hand_count_text) >= 3:
        corrected = hand_count_text[-2:]
        task.log_info(f"Hand count OCR recognized as {hand_count_text}, corrected to {corrected}")
        hand_count_text = corrected
    hand_count = int(hand_count_text)
    if hand_count > 10:
        corrected = hand_count % 100
        task.log_info(f"Hand count OCR exceeded 10: {hand_count}, corrected to {corrected}")
        hand_count = corrected
    return min(hand_count, 10)


def _read_member_slots(task: TriggerTask):
    """Dynamically read rendezvous member candidate slots based on level and reroll text."""
    x1, y1, x2, y2 = 0.077, 0.572, 0.946, 0.871
    refresh_text = _get_game_text(task, "重新搜索")
    region_boxes = [
        box for box in task.all_texts
        if x1 <= (box.x + box.width / 2) / task.width <= x2
        and y1 <= (box.y + box.height / 2) / task.height <= y2
    ]
    level_boxes = sorted(
        (box for box in region_boxes if box.name.strip() == "等级"),
        key=lambda box: box.x,
    )
    refresh_boxes = [
        box for box in region_boxes
        if refresh_text in box.name
    ]

    slots = []
    unused_refresh_boxes = list(refresh_boxes)
    for level_box in level_boxes:
        level_center_x = (level_box.x + level_box.width / 2) / task.width
        level_center_y = (level_box.y + level_box.height / 2) / task.height
        name_x = level_center_x + 0.188
        name_y = level_center_y + 0.042
        name_box = find_box_at_point(task, name_x, name_y)
        name = name_box.name if name_box else ""

        refresh_box = None
        if unused_refresh_boxes:
            refresh_box = min(
                unused_refresh_boxes,
                key=lambda box: abs(
                    (box.x + box.width / 2) / task.width - level_center_x
                ),
            )
            unused_refresh_boxes.remove(refresh_box)
        refresh_y = (
            (refresh_box.y + refresh_box.height / 2) / task.height
            if refresh_box else None
        )

        if name_box:
            task.log_info(f"_read_member_slots: Level pos ({level_center_x:.3f},{level_center_y:.3f}) recognized name='{name}', reroll y={refresh_y}")
        else:
            task.log_info(f"_read_member_slots: Level pos ({level_center_x:.3f},{level_center_y:.3f}) member name not recognized, reroll y={refresh_y}")
        slots.append({
            "name": name,
            "x": name_x,
            "y": name_y,
            "refresh_y": refresh_y,
        })
    return slots


def _battle_member_boxes(task: TriggerTask):
    """Read clickable member names from lead member list."""
    _excluded = {"主战员列表", "甄别主战员", "确认", "返回", "等级", "Q", "6", "支援",
                 "治愈", "守护", "核心", "60", "令", "√", "攻", "弘命", "炫心",
                 "详细信息", "配置", "同步", "全部", "``"}
    matched = []
    for box in task.all_texts:
        cx = (box.x + box.width / 2) / task.width
        cy = (box.y + box.height / 2) / task.height
        in_x = 0.100 <= cx <= 0.984
        in_y = 0.100 <= cy <= 0.892
        excluded = box.name in _excluded
        task.log_debug(f"_battle_member_boxes: name=「{box.name}」 cx={cx:.4f} cy={cy:.4f} "
                       f"in_x={in_x} in_y={in_y} excluded={excluded}")
        if in_x and in_y and not excluded:
            matched.append(box)
    return matched


def _confirm_battle_member_selection(task: TriggerTask):
    """After selecting lead member, confirm or return based on confirm button hue."""
    dominant_hue = calculate_dominant_hue(task, (0.901, 0.931, 0.911, 0.941))
    if dominant_hue != -1 and 7 <= dominant_hue <= 17:
        task.log_info(f"Lead member confirm button hue={dominant_hue}, clicking confirm")
        _move_and_click(task, 0.906, 0.936)
        task.sleep(2)
    else:
        task.log_info(f"Lead member confirm button hue={dominant_hue}, inactive, returning")
        _move_and_click(task, 0.044, 0.050)
    return True


# Member name -> template feature name mapping dict (fallback for OCR misses)
_MEMBER_FEATURE_MAP = {
    "九": "nine",
}


def _select_battle_member(task: TriggerTask, max_scrolls=5):
    """Select character by lead member priority; randomly choose if configured character not found."""
    priority = _get_battle_member_priority(task)
    task.log_info(f"Lead member priority config: {priority}")
    for scroll_index in range(max_scrolls + 1):
        boxes = _battle_member_boxes(task)
        recognized_names = [box.name for box in boxes]
        task.log_info(f"Scan {scroll_index + 1}: OCR recognized {len(boxes)} members:")
        for b in boxes:
            cx = (b.x + b.width / 2) / task.width
            cy = (b.y + b.height / 2) / task.height
            task.log_info(f"  box: name=「{b.name}」 cx={cx:.4f} cy={cy:.4f} x={b.x} y={b.y} w={b.width} h={b.height}")
        for name in priority:
            member = next(
                (box for box in boxes if name.strip() == box.name.strip()),
                None,
            )
            if member:
                cx = (member.x + member.width / 2) / task.width
                cy = (member.y + member.height / 2) / task.height
                task.log_info(f"Lead member priority matched: config '{name}' -> OCR '{member.name}' cx={cx:.4f} cy={cy:.4f} x={member.x} y={member.y} w={member.width} h={member.height}")
                task.click_box(member)
                task.sleep(0.5)
                return _confirm_battle_member_selection(task)
            else:
                # OCR missed, try template matching as fallback
                feature_name = _MEMBER_FEATURE_MAP.get(name)
                if feature_name and task.feature_exists(feature_name):
                    task.log_info(f"Lead member OCR missed '{name}', trying template match feature='{feature_name}'")
                    search_box = task.box_of_screen(0.096, 0.097, 0.988, 0.896)
                    feature_box = task.find_one(feature_name=feature_name, box=search_box, threshold=0.5)
                    if feature_box:
                        cx = (feature_box.x + feature_box.width / 2) / task.width
                        cy = (feature_box.y + feature_box.height / 2) / task.height
                        task.log_info(f"Lead member template match succeeded: config '{name}' feature='{feature_name}' cx={cx:.4f} cy={cy:.4f}, confidence={feature_box.confidence:.4f}")
                        task.click_box(feature_box)
                        task.sleep(0.5)
                        return _confirm_battle_member_selection(task)
                    else:
                        task.log_info(f"Lead member template match failed: '{name}' (feature='{feature_name}') not found")
                else:
                    task.log_info(f"Lead member priority match failed: '{name}' not in listed {len(boxes)} members")
        if scroll_index < max_scrolls:
            task.log_info(f"Scan {scroll_index + 1}: no priority character matched, scrolling down to retry")
            if task.is_adb():
                task.log_info("ADB swiping from (0.500, 0.700) to (0.500, 0.300) to browse members")
                task.swipe_relative(
                    0.5, 0.7, 0.5, 0.3, duration=0.4, settle_time=0.3
                )
            else:
                task.move_relative(0.5, 0.5)
                task.scroll_relative(0.5, 0.7, -3)
            task.sleep(0.5)
            task.all_texts = _simplify_texts(task.ocr())
    boxes = _battle_member_boxes(task)
    if not boxes:
        task.log_info("Lead member list is empty, unable to select")
        return False
    member = random.choice(boxes)
    cx = (member.x + member.width / 2) / task.width
    cy = (member.y + member.height / 2) / task.height
    task.log_info(f"Configured lead member not found, randomly selecting '{member.name}' cx={cx:.4f} cy={cy:.4f} x={member.x} y={member.y} w={member.width} h={member.height}")
    task.click_box(member)
    task.sleep(0.5)
    return _confirm_battle_member_selection(task)


# ------------------------- Sortie Mode exclusive page handlers -------------------------

def handle_boss_selection(task: TriggerTask):
    """Boss selection page: randomly select a boss and confirm."""
    box = find_box_at_point(task, 0.484, 0.928)
    if not (box and re.search(r"请选择.*遇见的首领", box.name)):
        return False
    bosses = []
    for x, y in [(0.358, 0.706), (0.641, 0.706)]:
        name_box = find_box_at_point(task, x, y)
        if name_box:
            bosses.append({"name": name_box.name, "x": x, "y": y})
    if not bosses:
        return False
    boss = random.choice(bosses)
    task.log_info(f"Boss selection: randomly selected '{boss['name']}'")
    _move_and_click(task, boss["x"], boss["y"])
    task.sleep(1)
    # _move_and_click(task, 0.919, 0.930)
    return True


def handle_secret_enemy(task: TriggerTask):
    """Battle screen: when special enemy discovered, drag a random hand card to enemy center."""
    hand_count_box = find_box_at_point(task, 0.513, 0.975)
    if not (hand_count_box and re.search(r"\d+/\d+", hand_count_box.name)):
        return False

    search_box = task.box_of_screen(0.496, 0.154, 0.967, 0.636)
    secret_enemy = task.find_one(
        feature_name="secret_enemy",
        box=search_box,
        threshold=0.7,
    )
    if not secret_enemy:
        return False

    enemy_x = (secret_enemy.x + secret_enemy.width / 2) / task.width
    enemy_y = (secret_enemy.y + secret_enemy.height / 2) / task.height
    card_x = random.uniform(0.202, 0.795)
    card_y = random.uniform(0.726, 0.911)
    task.log_info(f"Discovered special enemy, dragging hand card from ({card_x:.3f}, {card_y:.3f}) to enemy center ({enemy_x:.3f}, {enemy_y:.3f}), confidence={secret_enemy.confidence:.4f}")
    task.move_relative(card_x, card_y)
    task.swipe_relative(card_x, card_y, enemy_x, enemy_y, duration=0.5)
    return False


def handle_battle_page(task: TriggerTask):
    """Battle screen: play cards according to 'Card Play Priority' config; fallback to descending hand keys if not found."""

    hand_count = _read_hand_count(task)
    if hand_count is None:
        return False

    # If reached final boss node, mark boss battle status
    if hasattr(task, 'node_status') and task.node_status.get('reach_final_boss', False):
        task.node_status['final_boss_battle'] = True
        task.log_info("Detected final boss battle start, final_boss_battle=True")

    # Check if EP bar is full (RGB near (193, 255, 255) at 0.032, 0.947)
    ep_px = int(0.032 * task.width)
    ep_py = int(0.947 * task.height)
    if 0 <= ep_px < task.width and 0 <= ep_py < task.height:
        ep_region = task.frame[max(0, ep_py-2):ep_py+3, max(0, ep_px-2):ep_px+3, :3]
        if ep_region.size > 0:
            avg_bgr = cv2.mean(ep_region)[:3]
            # OpenCV uses BGR format; target RGB(193, 255, 255) -> BGR(255, 255, 193)
            avg_b, avg_g, avg_r = avg_bgr
            task.log_info(f"EP energy bar color: B={avg_b:.1f} G={avg_g:.1f} R={avg_r:.1f} (expected near B=255 G=255 R=193)")
            if abs(avg_b - 255) <= 15 and abs(avg_g - 255) <= 15 and abs(avg_r - 193) <= 15:
                task.log_info("EP energy reached maximum, randomly releasing Ego skill")
                task.send_key(random.choice(["F1", "F2", "F3"]))
                task.sleep(1)
                task.send_key("enter")
                task.sleep(4)
                return True

    finishturn_box = task.box_of_screen(0.844, 0.782, 0.998, 0.990)
    if not task.find_feature(feature_name="finishturn", box=finishturn_box):
        task.log_info("finishturn feature not detected, return True waiting for next frame")
        return True

    card_names = _hand_card_names(task)
    cards = _hand_cards(task)

    if (cards or card_names):
        # Card play stuck check: track if previously attempted card remains in hand across rounds
        if not hasattr(task, '_play_stuck_count'):
            task._play_stuck_count = 0
        if not hasattr(task, '_last_attempted_card'):
            task._last_attempted_card = None

        # Check 'Card Play Priority' config
        play_priority = _get_config_value(task, "出牌优先级", [])
        if play_priority and cards:
            for pri_name in play_priority:
                matched = next((c for c in cards if pri_name and (pri_name in c["name"] or c["name"] in pri_name) and c["key"] is not None), None)
                if matched:
                    # Check if matched card is same as previous attempt and still in hand
                    if task._last_attempted_card == matched["name"]:
                        task._play_stuck_count += 1
                        task.log_info(f"Card '{matched['name']}' failed to play for {task._play_stuck_count + 1} consecutive attempts")
                        if task._play_stuck_count >= 3:
                            task.log_info(f"Card '{matched['name']}' failed to play 3 times consecutively, executing fallback card play")
                            task._last_attempted_card = None
                            task._play_stuck_count = 0
                            _try_all_card_keys(task, hand_count)
                            return True
                    else:
                        task._last_attempted_card = matched["name"]
                        task._play_stuck_count = 0

                    task.log_info(f"Card play priority matched: Card '{matched['name']}' -> Key {matched['key']}")
                    task.send_key(matched['key'])
                    task.sleep(1)
                    task.send_key("enter")
                    task.sleep(2)
                    if "极光" in matched["name"]:
                        task.log_info(f"Card '{matched['name']}' contains Aurora, waiting additional 2s")
                        task.sleep(2)
                    elif "万众英雄" in matched["name"]:
                        task.log_info(f"Card '{matched['name']}' contains Universal Hero, waiting additional 2s")
                        task.sleep(2)
                    return True

        # No priority card matched, reset card-stuck state
        task._last_attempted_card = None
        task._play_stuck_count = 0
        # Fallback: play cards from high to low keys
        task.log_info(f"No priority card matched, executing fallback from hand count {hand_count} downwards")
        _try_all_card_keys(task, hand_count)
        return True
    else:
        finishturn_box = task.box_of_screen(0.844, 0.782, 0.998, 0.990)
        if task.find_feature(feature_name="finishturn", box=finishturn_box):
            task.log_info("Detected finishturn feature, pressing E to end turn")
            task.send_key("e")
            task.sleep(1)
        return True
    return True


def handle_get_card(task: TriggerTask):
    """Card acquisition page: select card according to priority."""
    title = find_box_at_point(task, 0.502, 0.128)
    tip = find_box_at_point(task, 0.883, 0.131)
    if not (title and title.name == "获得卡牌" and tip and re.search(r"请选择.*获得的卡牌", tip.name)):
        return False
    cards = recognize_cards(task, page="Card acquisition page")
    if not cards:
        task.log_info("Card acquisition: card type features not recognized, unable to select")
        return False

    priority = _get_config_value(task, "获得卡牌优先级", [])
    task.log_info(f"Card acquisition: current priority config: {priority}")
    for name in priority:
        task.log_info(f"Card acquisition: checking if priority '{name}' is in card list")
        chosen = next((card for card in cards if name in card["name"]), None)
        if chosen:
            task.log_info(f"Card acquisition: prioritized '{chosen['name']}' (matched priority '{name}')")
            _move_and_click(task, chosen["x"], chosen["y"])
            task.sleep(0.5)
            _move_and_click(task, 0.912, 0.931)
            return True
    task.log_info("Card acquisition: no priority card matched, skipping non-priority cards")
    _move_and_click(task, 0.749, 0.931)
    task.sleep(1)
    return True


def handle_draw_card_event(task: TriggerTask):
    """Card draw event page: select card to hold according to card acquisition priority."""
    title = find_box_at_point(task, 0.509, 0.108)
    prompt_pattern = _get_game_text(task, r"请选择.*手持的卡牌")
    if not (title and re.search(prompt_pattern, title.name)):
        return False
    x1, y1, x2, y2 = 0.028, 0.211, 0.938, 0.857
    cards = [
        box for box in task.all_texts
        if x1 <= (box.x + box.width / 2) / task.width <= x2
        and y1 <= (box.y + box.height / 2) / task.height <= y2
        and box.name.strip()
    ]
    if not cards:
        return False
    chosen = None
    for name in _get_config_value(task, "获得卡牌优先级", []):
        chosen = next((card for card in cards if name in card.name), None)
        if chosen:
            task.log_info(f"Draw card event: prioritized '{chosen.name}'")
            break
    if chosen is None:
        chosen = random.choice(cards)
        task.log_info(f"Draw card event: no priority matched, randomly selected '{chosen.name}'")
    task.click_box(chosen)
    task.sleep(1)
    # _move_and_click(task, 0.952, 0.933)
    return True


def handle_discard_hand_card(task: TriggerTask):
    """Available cards remain in hand prompt: click to discard hand."""
    box = find_box_at_point(task, 0.5, 0.356)
    if box and "手牌中仍有可用卡牌" in box.name:
        task.log_info("Detected hand discard prompt, clicking discard")
        _move_and_click(task, 0.424, 0.500) # Do not show again today
        task.sleep(0.5)
        _move_and_click(task, 0.663, 0.607)
        return True
    return False


def handle_sortie_reward_settlement(task: TriggerTask):
    """Sortie Mode reward settlement page: claim rewards or close page based on config."""
    title = find_box_at_point(task, 0.550, 0.068)
    if not (title and title.name == "结算"):
        return False
    reward_box = find_box_at_point(task, 0.848, 0.389)
    if reward_box and reward_box.name == "获得" and _get_config_value(task, "领取奖励", False):
        task.log_info("Detected Sortie Mode reward settlement page, claiming reward")
        task.click_box(reward_box)
        task.sleep(1)
        return True
    task.log_info("Detected Sortie Mode reward settlement page, closing page")
    return _finish_only_first_layer(task) if not task.node_status.get('is_escaped', False) else False


def handle_sortie_reward_claim(task: TriggerTask):
    """Sortie Mode reward claim page: claim or forfeit Chaos loot based on config."""
    title = find_box_at_point(task, 0.503, 0.335)
    if not (title and re.search(r"卡.*思战利品", title.name)):
        return False
    if _get_config_value(task, "领取奖励", False):
        task.log_info("Detected Sortie Mode reward claim page, claiming Chaos loot")
        _move_and_click(task, 0.567, 0.708)
        task.sleep(1)
        return True
    task.log_info("Detected Sortie Mode reward claim page, forfeiting Chaos loot")
    _move_and_click(task, 0.355, 0.714)
    return True


def handle_battle_member_config(task: TriggerTask):
    """Member config page: differentiate lead member entrance and confirm entrance."""
    title = find_box_at_point(task, 0.130, 0.043)
    if not (title and _get_game_text(task, '主战员配置') in title.name):
        return False
    battle_member_hint = find_box_at_point(task, 0.188, 0.799)
    if not (battle_member_hint and battle_member_hint.name.strip()):
        task.log_info("Detected member config page: currently in lead member, clicking lead member entrance")
        _move_and_click(task, 0.315, 0.475)
        task.sleep(2)
        return True
    task.log_info("Detected member config page: clicking enter")
    _move_and_click(task, 0.719, 0.914)
    return True


def handle_battle_member_selection(task: TriggerTask):
    """Lead member list page: select character by configured priority."""
    title = find_box_at_point(task, 0.139, 0.044)
    right_hint = find_box_at_point(task, 0.562, 0.044)
    if not ((title and  _get_game_text(task, '主战员列表') in title.name) and  (right_hint and _get_game_text(task, '甄别主战员') in right_hint.name)):
        return False
    return _select_battle_member(task)


def handle_member_selection(task: TriggerTask):
    """Member selection page: prioritize configured character (skip blacklisted); else reroll once, then select randomly."""
    prompt = find_box_at_point(task, 0.500, 0.931)
    if not (prompt and _get_game_text(task, '主战员') in prompt.name):
        return False
    priority = _get_member_priority(task)
    blacklisted = _get_blacklisted_members(task)
    task.log_info(f"Member selection: priority={priority}, blacklisted={blacklisted}")

    def not_blacklisted(slot):
        return not any(blk in slot["name"] for blk in blacklisted)

    slots = _read_member_slots(task)
    chosen = None
    for name in priority:
        chosen = next((slot for slot in slots if name in slot["name"] and not_blacklisted(slot)), None)
        if chosen:
            task.log_info(f"Member selection: prioritized '{chosen['name']}'")
            break
    if chosen is None:
        task.log_info("Member selection: priority character not found or blacklisted, rerolling once")
        for slot in slots:
            if slot["refresh_y"] is not None:
                _move_and_click(task, slot["x"], slot["refresh_y"])
                task.sleep(1)
        task.sleep(1)
        task.all_texts = _simplify_texts(task.ocr())
        slots = _read_member_slots(task)
        for name in priority:
            chosen = next((slot for slot in slots if name in slot["name"] and not_blacklisted(slot)), None)
            if chosen:
                task.log_info(f"Member selection: selected '{chosen['name']}' after reroll")
                break
    if chosen is None:
        valid_slots = [slot for slot in slots if slot["name"] and not_blacklisted(slot)]
        if not valid_slots:
            valid_slots = [slot for slot in slots if slot["name"]]
            if not valid_slots:
                return False
            task.log_info("Member selection: all candidates blacklisted, selecting randomly from all")
        chosen = random.choice(valid_slots)
        task.log_info(f"Member selection: priority character not found, randomly selecting '{chosen['name']}'")
    _move_and_click(task, chosen["x"], chosen["y"])
    task.sleep(1)
    # _move_and_click(task, 0.884, 0.931)
    # task.sleep(0.5)
    # _move_and_click(task, 0.635, 0.639)
    # task.sleep(0.5)
    return True


def handle_rational_supply(task: TriggerTask):
    """Rational supply page: when confirm button is inactive, disable claim rewards and forfeit refill."""
    # Search for text containing 'Rational Refill' in region (0.438, 0.101, 0.561, 0.250)
    x1, y1, x2, y2 = 0.438, 0.101, 0.561, 0.250
    title = next((b for b in task.all_texts
                  if x1 <= (b.x + b.width / 2) / task.width <= x2
                  and y1 <= (b.y + b.height / 2) / task.height <= y2
                  and "补充理性" in b.name), None)
    if not title:
        return False
    task.log_info("Detected rational supply page")
    confirm_box = find_box_at_point(task, 0.664, 0.774)
    if confirm_box and _clean_match(confirm_box.name, "确认") and not is_button_active(task, confirm_box):
        task.log_info("Confirm button inactive, setting 'Claim Rewards' to False, clicking forfeit refill")
        task.config['领取奖励'] = False
        from ok.gui.Communicate import communicate
        communicate.task_list_updated.emit()
        _move_and_click(task, 0.352, 0.774)
        task.sleep(1)
        return True
    return False


def handle_ether_supply(task: TriggerTask):
    """Aether supply page: prompt user to manually refill aether."""
    box = find_box_at_point(task, 0.502, 0.139)
    if box and box.name == _get_game_text(task, '以太补充'):
        task.log_info("Detected aether supply page, please refill aether manually before resuming")
        _move_and_click(task, 0.347, 0.803)
        task.sleep(0.5)
        return True
    return False


def handle_battle_hand_select(task: TriggerTask):
    """In-battle card selection page: detect select-card text and hand count, randomly select required count."""
    # Detect prompt text at (0.5, 0.111)
    prompt = find_box_at_point(task, 0.5, 0.111)
    if not prompt:
        return False
    m = re.search(r'请选择(?=.*卡牌).*?(\d+)张', prompt.name)
    if not m:
        return False

    # Detect hand count x/10 at (0.505, 0.971)
    hand_box = find_box_at_point(task, 0.505, 0.971)
    if not (hand_box and re.search(r'\d+/10', hand_box.name)):
        return False

    need = int(m.group(1))
    task.log_info(f"Detected in-battle hand selection page, need to select {need} cards, selecting randomly")

    _card_exclude_keywords = {"攻击", "强化", "技能", "咒术", "基础", "基本", "状态异常", "诅咒"}
    selected = 0
    for _ in range(need):
        task.all_texts = _simplify_texts(task.ocr())
        cards = [
            b for b in task.all_texts
            if 0.116 <= (b.x + b.width / 2) / task.width <= 0.859
            and 0.697 <= (b.y + b.height / 2) / task.height <= 0.878
            and len(b.name.strip()) > 1
            and b.name not in ["确认", "返回", "跳过"]
            and not any(kw in b.name for kw in _card_exclude_keywords)
            and not ("攻" in b.name and len(b.name) <= 3)
        ]
        if not cards:
            task.log_info("No cards found in hand area, clicking random position in hand area")
            rx = random.uniform(0.216, 0.759)
            ry = random.uniform(0.697, 0.878)
            _move_and_click(task, rx, ry)
            selected += 1
            task.sleep(1)
            continue
        chosen = random.choice(cards)
        task.log_info(f"Selected hand card: {chosen.name}")
        task.click_box(chosen)
        selected += 1
        task.sleep(1)

    if selected > 0:
        task.log_info("Selection complete, clicking confirm")
        _move_and_click(task, 0.934, 0.883)
        task.sleep(1)
    return True


def handle_curiosity_activate(task: TriggerTask):
    """Nia's Curiosity trigger page: select card to hold by priority (battle-related, prioritized over battle page)."""
    box = find_box_at_point(task, 0.499, 0.129)
    if box and _get_game_text(task, '请选择1张要手持的卡牌') in box.name:
        task.log_info("Detected Nia's Curiosity activation page")
        priority = ["剑雨", "展开极光", "一缕光芒", "万众英雄"]
        cards = recognize_cards(task, page="Nia's Curiosity page")
        chosen_card = None
        for pri_name in priority:
            for card in cards:
                if card["name"] and card["name"] in pri_name:
                    chosen_card = card
                    task.log_info(f"Selected card by priority: {card['name']}")
                    break
            if chosen_card:
                break
        if not chosen_card and cards:
            chosen_card = random.choice(cards)
            task.log_info(f"Priority missed, randomly selected card: {chosen_card['name']}")
        if chosen_card:
            _move_and_click(task, chosen_card["x"], chosen_card["y"])
            task.sleep(2)
            return True
    return False


def handle_extra_card_use(task: TriggerTask):
    """Extra card play page: randomly select a card to play (battle-related, prioritized over battle page)."""
    box = find_box_at_point(task, 0.498, 0.131)
    if box and "请选择张要额外使用的卡牌" in box.name:
        task.log_info("Detected extra card play page, selecting randomly")
        _move_and_click(task, *random.choice([(0.251, 0.546), (0.508, 0.518), (0.764, 0.525)]))
        task.sleep(2)
        return True
    return False


def handle_card_function_select(task: TriggerTask):
    """Card function selection page: Quantum Seed forecast selects Create, Clown task selects random task."""
    title = find_box_at_point(task, 0.499, 0.131)
    if not (title and "请选择功能" in title.name):
        return False
    task_positions = [(0.115, 0.286), (0.349, 0.289), (0.588, 0.290), (0.827, 0.287)]
    task_boxes = [find_box_at_point(task, x, y) for x, y in task_positions]
    if all(b and "任务" in b.name for b in task_boxes):
        chosen = random.choice(task_boxes)
        task.log_info("Detected Clown task card activation, selecting random task")
        task.click_box(chosen)
        task.sleep(4)
        return True
    p1 = find_box_at_point(task, 0.214, 0.289)
    p2 = find_box_at_point(task, 0.470, 0.292)
    p3 = find_box_at_point(task, 0.722, 0.286)
    if p1 and p2 and p3 and "创造" in p1.name and "创造" in p2.name and "创造" in p3.name:
        task.log_info("Detected Quantum Seed Forecast card page, clicking Create")
        _move_and_click(task, 0.722, 0.286)
        task.sleep(4)
        return True
    cards = recognize_cards(task, page="Card function selection page")
    if cards:
        chosen = random.choice(cards)
        task.log_info(f"Card function selection fallback: randomly clicking card '{chosen['name']}', type '{chosen['type'] or chosen['feature_type']}'")
        _move_and_click(task, chosen["x"], chosen["y"])
        task.sleep(4)
        return True
    return False


def handle_return_to_draw_pile(task: TriggerTask):
    """Return hand card to draw pile page: select first card from left to right."""
    box = find_box_at_point(task, 0.484, 0.111)
    if not (box and re.search(r"请选择.*要移动至抽牌堆.*", box.name)):
        return False
    task.log_info("Detected return card to draw pile page, selecting first card from left")
    cards = sorted(
        [b for b in task.all_texts
         if 0.116 <= (b.x + b.width / 2) / task.width <= 0.859
         and 0.697 <= (b.y + b.height / 2) / task.height <= 0.908
         and len(b.name.strip()) > 1
         and b.name not in ["确认", "返回", "跳过"]],
        key=lambda b: b.x
    )
    if not cards:
        task.log_info("No hand cards found")
        return False
    chosen = cards[0]
    task.log_info(f"Return to draw pile page triggered card selection, clicking '{chosen.name}'")
    task.click_box(chosen)
    task.sleep(1)
    # _move_and_click(task, 0.934, 0.883)
    # task.sleep(1)
    return True





def handle_rest_sortie(task: TriggerTask):
    """Sortie Mode rest page: handles both rest and flash functions according to conditions."""
    # Check flash area (0.788,0.463)-(0.870,0.594) for 'Flash' and cost <= 30
    flash_x1, flash_y1, flash_x2, flash_y2 = 0.788, 0.463, 0.870, 0.594
    has_flash_text = False
    flash_cost = None
    flash_box = None
    for b in task.all_texts:
        cx = (b.x + b.width / 2) / task.width
        cy = (b.y + b.height / 2) / task.height
        if flash_x1 <= cx <= flash_x2 and flash_y1 <= cy <= flash_y2:
            if "闪光" in b.name:
                has_flash_text = True
                flash_box = b
            costs = [int(number) for number in re.findall(r"\d+", b.name) if int(number) <= 30]
            if costs and flash_cost is None:
                flash_cost = costs[0]

    flash_feature = task.find_one(
        feature_name="flash_in_sortie_safezoom",
        box=task.box_of_screen(0.702, 0.347, 0.963, 0.713),
    )
    if flash_feature:
        task.log_info(f"Detected flash_in_sortie_safezoom feature, confidence: {flash_feature.confidence:.2%}")

    if flash_feature and has_flash_text and flash_cost is not None and flash_box and hasattr(task, 'node_status') and task.node_status.get('flash_or_rest', False):
        task.log_info("Rest area has available flash option")

        # Get current credit points
        credit = _get_current_credit(task)
        task.log_info(f"Current credits: {credit}")

        # Get current HP percentage, fallback to 100% on failure
        hp_percent = _get_current_hp_percent(task)
        if hp_percent is False:
            hp_percent = 100

        flash_threshold_str = _get_config_value(task, '生命值大于多少优先闪光(百分比)', "60")
        try:
            flash_threshold = int(flash_threshold_str)
        except (ValueError, TypeError):
            flash_threshold = 60
        task.log_info(f"HP={hp_percent}%, threshold={flash_threshold}%, credits={credit}")
        if credit > flash_cost and hp_percent >= flash_threshold:
            task.log_info("Flash conditions met, clicking flash")
            task.click_box(flash_box)
            if not _wait_for_rest_confirm(task):
                return True
            task.node_status['flash_or_rest'] = False
            return True
        else:
            task.log_info("Flash conditions not met, continuing to check rest")

    rest_feature = _find_rest_feature(task)
    free_text = _get_region_text(task, (0.154, 0.602, 0.359, 0.847))
    if (rest_feature and "免费" in free_text and hasattr(task, 'node_status')
            and task.node_status.get('flash_or_rest', False)):
        task.log_info("Detected rest screen, clicking rest")
        task.click_box(rest_feature)
        if not _wait_for_rest_confirm(task):
            return True
        task.node_status['flash_or_rest'] = False
        return True

    if rest_feature and "免费" not in free_text:
        task.log_info("Detected rest feature, but 'Free' not found in rest region, skipping click")

    # Check whether Delang Shop should be entered
    shop_box = find_box_at_point(task, 0.360, 0.138)
    if shop_box and "德朗商店" in shop_box.name and hasattr(task, 'node_status') and task.node_status.get('shop', False):
        task.log_info("Detected Delang Shop with node_status['shop']=True, entering shop")
        task.click_box(shop_box)
        task.sleep(2)
        return True
    return False


# Sortie Mode PAGE_HANDLERS
PAGE_HANDLERS = [
    handle_auto_stop,
    handle_route_selection,
    # handle_stage_clear,
    log_credit,
    log_node_status,
    handle_stuck_log,  # Screen stuck detection and fallback handling,
    handle_close_page,  # Tap screen to close page, prioritized over normal page handling

    handle_ether_supply,
    handle_refine_equipment_credit,  # Refine equipment credit page, prioritized over confirm button
    handle_center_confirm,
    handle_archive_target_member,  # Info stats page, prevent Sortie Mode freezing
    handle_equipment,  # Equipment selection
    handle_card_assign,
    handle_confirm,  # Confirm button
    handle_convert,  # Convert button
    handle_shop,  # Delang shop
    handle_rest_sortie,  # Rest / shop entrance
    handle_close_button,  # Close button
    handle_remove,  # Remove button
    handle_three_choice_card_remove,  # 3-choice card removal page (low-priority fallback)
    handle_flash,  # Flash button
    handle_reflash,  # Re-flash button
    handle_grant_flash,  # Grant flash button
    handle_copy,  # Duplicate button
    handle_leave,  # Leave button
    handle_expedition_result,  # Expedition result page, prioritized over next step
    handle_next_step,  # Next-step button
    handle_select,  # Select button

    handle_equipment_recast,  # Equipment recast button

    handle_non_battle_page,
    handle_battle_crash,
    handle_discard_hand_card,
    handle_battle_hand_select,
    handle_curiosity_activate,
    handle_extra_card_use,
    handle_card_function_select,
    handle_return_to_draw_pile,
    handle_weakness_info,
    handle_battle_page,
    handle_settlement,
    handle_destiny_choice,
    handle_main_member_flash,
    handle_boss_selection,
    handle_get_card,
    handle_card_reward,
    handle_draw_card_event,
    # handle_equipment,
    # handle_mask_card,
    handle_select_card,
    handle_copy_member,
    handle_convert_card,
    handle_negotiation,
    handle_sortie_reward_settlement,
    handle_sortie_reward_claim,
    handle_continue,
    handle_battle_member_selection,
    handle_member_selection,
    handle_battle_member_config,
    handle_enter,
    handle_obtain_reward,
    handle_view_original,
    handle_skip,
    handle_event_task,
    handle_rational_supply,
    handle_weakness_info,
    handle_minimizemap,
    handle_held_cards_page,
    handle_escape,
]
