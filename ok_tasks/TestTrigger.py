from ok import TriggerTask

from utils_sortie import handle_secret_enemy


class TestTrigger(TriggerTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "Test Trigger"
        self.description = "Test Trigger"
        self.trigger_interval = 2
        self.instructions = """<a href="https://github.com/ok-oldking/ok-py">ok-py</a>"""

    def run(self):
        self.all_texts = self.ocr()
        handle_secret_enemy(self)
