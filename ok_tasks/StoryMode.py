from ok import TriggerTask, og

import utils_story
from utils import _simplify_texts

class StoryMode(TriggerTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "Semi-Auto Story Mode"
        self.description = "1. For battle stages in the story, manually enable Sortie Mode to use Auto Battle.\n2. For Chaos stages, manually enable Chaos Mode.\n3. Story battle teams must be configured manually"
        self.instructions = """<a href="https://github.com/ok-oldking/ok-py">ok-py</a>"""
        self.trigger_interval = 1
        self.all_texts = []
        # Off by default; the user toggles it in the UI. The TriggerTask runs as its own main task.
        self.default_config['_enabled'] = False

    def enable(self):
        """Auto-disables Sortie Mode and Chaos Mode when Story Mode is enabled."""
        from SortieMode import SortieMode
        from ChaosMode import ChaosMode
        sortie = og.executor.get_task_by_class(SortieMode)
        if sortie and sortie.enabled:
            sortie.disable()
        chaos = og.executor.get_task_by_class(ChaosMode)
        if chaos and chaos.enabled:
            chaos.disable()
        super().enable()

    def run(self):
        # Run OCR once per frame and convert to Simplified, shared by all page handlers
        self.all_texts = _simplify_texts(self.ocr())
        # Try each page handler in order; a hit (True) ends this frame
        for handle_page in utils_story.PAGE_HANDLERS:
            if handle_page(self):
                return
