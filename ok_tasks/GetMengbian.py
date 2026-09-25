from ok import BaseTask
import re

class GetMengbian(BaseTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "Farm Dream Border"
        self.description = "Dream Border"
        self.instructions = """<a href="https://github.com/ok-oldking/ok-py">ok-py</a>"""

    def run(self):
        for i in range(300):
            self.log_info("Starting loop {}".format(i+1))
            self.log_info("Dream Border entrance page triggered enter event, waiting and clicking the first \"Enter\"")
            self.wait_click_ocr(match="进入", time_out=60, after_sleep=1)
            self.log_info("Dream Border entrance page triggered confirm-enter event, waiting and clicking the second \"Enter\"")
            self.wait_click_ocr(match="进入", time_out=60)
            self.sleep(11)
            if self.ocr(match=re.compile(r".*传说卡牌.*")):
                self.log_info("Neutral legendary card appeared")
                self.log_info("Dream Border page triggered select-card event, clicking the neutral legendary card")
                self.click(0.758, 0.853)
                self.sleep(1)
                self.log_info("Dream Border page triggered confirm-selection event, clicking the confirm position")
                self.click(0.757, 0.953)
                self.sleep(4)
                if self.ocr(match=re.compile(r"梦之边境")):
                    self.log_info("Dream Border completed, exiting loop")
                    break
            self.log_info("No neutral legendary card appeared, continuing loop")
            self.log_info("Dream Border page triggered exit event, clicking the exit position")
            self.click(0.959, 0.049)
            self.log_info("Dream Border exit page triggered evacuate event, waiting and clicking \"Evacuate\"")
            self.wait_click_ocr(match="逃脱", time_out=60)
            self.log_info("Dream Border exit page triggered confirm event, waiting and clicking \"Confirm\"")
            self.wait_click_ocr(match="确认",time_out=60,after_sleep=2)

