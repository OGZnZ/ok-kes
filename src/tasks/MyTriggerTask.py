from ok import TriggerTask


class MyTriggerTask(TriggerTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "Trigger That Calls run Repeatedly"
        self.description = "Usually decides whether to run based on the frame"
        self.trigger_count = 0

    def run(self):
        self.trigger_count += 1
        self.log_debug(f'MyTriggerTask run {self.trigger_count}')



