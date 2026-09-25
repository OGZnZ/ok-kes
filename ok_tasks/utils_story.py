from ok import TriggerTask

from utils import (
    _move_and_click,
    handle_confirm,
    handle_enter,
    handle_close_page,
    handle_next_step,
    find_box_at_point,
)
from utils_chaos import handle_battle_auto_check


# ------------------------- Page handlers -------------------------

def handle_auto_chat(task: TriggerTask):
    """Auto dialogue check: click to enable when autochatenable confidence is below 0.96."""
    search_box = task.box_of_screen(0.655, 0.007, 0.996, 0.097)
    auto_chat = task.find_one(feature_name="autochatenable", box=search_box)
    if auto_chat and auto_chat.confidence < 0.96:
        task.log_info(f"Auto dialogue is off, current match confidence: {auto_chat.confidence:.2%}, clicking to enable")
        task.click_box(auto_chat)
        return True
    return False


def handle_view_event(task: TriggerTask):
    """View event page: detect the check feature in the given region and click it."""
    search_box = task.box_of_screen(0.084, 0.125, 0.995, 0.875)
    check_box = task.find_one(feature_name="check", box=search_box)
    if check_box:
        task.log_info("Detected view event, clicking the check feature")
        task.click_box(check_box)
        task.sleep(0.5)
        return True
    return False


# def handle_team_config(task: TriggerTask):
#     """Team setup page: detect the '配置队伍' text at (0.122,0.047), pick an empty slot to add a member."""
#     title_box = find_box_at_point(task, 0.122, 0.047)
#     if not (title_box and "配置队伍" in title_box.name):
#         return False
#     task.log_info("Detected team setup page")
#     slots = [
#         (0.057, 0.611, 0.132, 0.456),
#         (0.270, 0.610, 0.344, 0.444),
#         (0.484, 0.608, 0.554, 0.436),
#     ]
#     for check_x, check_y, click_x, click_y in slots:
#         box = find_box_at_point(task, check_x, check_y)
#         if box is None or not box.name.strip():
#             task.log_info(f"Slot ({check_x},{check_y}) is empty, clicking ({click_x},{click_y}) to add a member")
#             _move_and_click(task, click_x, click_y)
#             task.sleep(2)
#             return True
#     task.log_info("All slots already have members, nothing to add")
#     return False


def handle_enter_stage(task: TriggerTask):
    """Enter-stage button: detect the enter button at (0.820,0.931) and click it."""
    box = find_box_at_point(task, 0.820, 0.931)
    if box and "入场" in box.name:
        task.log_info("Detected enter-stage button, clicking to enter")
        task.click_box(box)
        task.sleep(1)
        return True
    return False


def handle_enter_story_or_battle(task: TriggerTask):
    """Story/battle entrance page: click the leftmost enterstory or enterbattle feature."""
    search_box = task.box_of_screen(0.085, 0.124, 0.995, 0.874)
    story_boxes = task.find_feature(feature_name="enterstory", box=search_box)
    battle_boxes = task.find_feature(feature_name="enterbattle", box=search_box, threshold=0.85)
    candidates = [
        *((box, "story") for box in story_boxes),
        *((box, "battle") for box in battle_boxes),
    ]
    if candidates:
        chosen_box, entrance_type = min(candidates, key=lambda item: item[0].x)
        task.log_info(
            f"Detected {entrance_type} entrance, clicking the leftmost feature"
            f"(x={chosen_box.x}, confidence={chosen_box.confidence:.2f})"
        )
        task.click_box(chosen_box)
        task.sleep(2)
        return True
    return False


def handle_skip_story(task: TriggerTask):
    """Skippable story page: click to skip when the skipstory feature is detected."""
    boxes = task.find_feature(feature_name="skipstory")
    if boxes:
        task.log_info("Detected skippable story page, clicking to skip")
        task.click_box(boxes[0])
        task.sleep(1)
        return True
    return False


def handle_observe(task: TriggerTask):
    """Observe Chaos stage page: detect the '观测' text in the region and click it."""
    x1, y1, x2, y2 = 0.092, 0.214, 0.962, 0.792
    for b in task.all_texts:
        cx = (b.x + b.width / 2) / task.width
        cy = (b.y + b.height / 2) / task.height
        if x1 <= cx <= x2 and y1 <= cy <= y2 and b.name.strip() == "观测":
            task.log_info("Detected observe Chaos stage, clicking observe")
            task.click_box(b)
            task.sleep(4)
            return True
    return False


# Story mode page handler list (ordered by priority)
PAGE_HANDLERS = [
    # handle_team_config,  #team setup (highest priority)
    handle_skip_story,  #skip story (highest priority)
    handle_auto_chat,  #auto dialogue check
    handle_view_event,  #view event
    handle_confirm,  #confirm button
    handle_enter,  #enter button
    handle_enter_stage,  #enter-stage button
    handle_close_page,  #tap screen to close page
    handle_enter_story_or_battle,
    handle_observe,  #observe Chaos stage
    handle_next_step,
    handle_battle_auto_check,  #auto battle check
]
