# -*- coding: utf-8 -*-
"""
Runtime i18n patch for ok-script-kes framework classes.
Ensures bidirectional translation (Chinese game OCR values <-> English UI display)
for ModifyListItem, ModifyListDialog, LabelAndLineEdit, and App.tr/reverse_tr
even when ok-script-kes is installed from site-packages.
"""
from ok import App, og
from ok.gui.tasks.LabelAndLineEdit import LabelAndLineEdit
from ok.gui.tasks.ModifyListDialog import ModifyListDialog
from ok.gui.tasks.ModifyListItem import ModifyListItem, MAX_LIST_DISPLAY_LENGTH
from ok.gui.widget.UpdateConfigWidgetItem import value_to_string


def install_i18n_patch():
    if getattr(App, "_mbg_kes_i18n_patched", False):
        return

    # 1. Patch App.tr and App.reverse_tr
    _orig_tr = App.tr

    def patched_tr(self, key):
        res = _orig_tr(self, key)
        if res and res != key:
            return res
        if isinstance(key, str) and getattr(self, "po_translation", "Failed") not in (None, "Failed"):
            for sep in ("：", ":"):
                if sep in key:
                    parts = key.split(sep)
                    tr_parts = [patched_tr(self, p.strip()) for p in parts]
                    if tr_parts != [p.strip() for p in parts]:
                        return ": ".join(tr_parts)
            modifiers = [
                ("强化", " Buff"),
                ("攻击", " Attack"),
                ("技能", " Skill"),
                ("感应", " Induction"),
            ]
            for cn_mod, en_mod in modifiers:
                if key.endswith(cn_mod) and len(key) > len(cn_mod):
                    base_card = key[:-len(cn_mod)]
                    tr_base = patched_tr(self, base_card)
                    if tr_base != base_card:
                        return f"{tr_base}{en_mod}"
        return res

    def reverse_tr(self, text):
        if not text:
            return text
        po = getattr(self, "po_translation", None)
        if po and hasattr(po, "_catalog"):
            if not hasattr(self, "_reverse_catalog") or getattr(self, "_reverse_catalog_len", 0) != len(po._catalog):
                self._reverse_catalog = {v: k for k, v in po._catalog.items() if v and k}
                self._reverse_catalog_len = len(po._catalog)
            if text in self._reverse_catalog:
                return self._reverse_catalog[text]
            if isinstance(text, str):
                if ": " in text:
                    parts = text.split(": ")
                    rev_parts = [reverse_tr(self, p.strip()) for p in parts]
                    if rev_parts != [p.strip() for p in parts]:
                        return "：".join(rev_parts)
                modifiers = [
                    (" Buff", "强化"),
                    (" Attack", "攻击"),
                    (" Skill", "技能"),
                    (" Induction", "感应"),
                ]
                for en_mod, cn_mod in modifiers:
                    if text.endswith(en_mod) and len(text) > len(en_mod):
                        base_card = text[:-len(en_mod)]
                        rev_base = reverse_tr(self, base_card)
                        if rev_base != base_card:
                            return f"{rev_base}{cn_mod}"
        return text

    App.tr = patched_tr
    App.reverse_tr = reverse_tr

    # 2. Patch ModifyListItem.update_value
    def patched_list_update_value(self):
        items = self.config.get(self.key)
        if isinstance(items, list):
            items = [og.app.tr(str(item)) for item in items]
        elif isinstance(items, str):
            items = og.app.tr(items)
        full_text = value_to_string(items)
        display_text = full_text
        if len(display_text) > MAX_LIST_DISPLAY_LENGTH:
            display_text = f"{display_text[:MAX_LIST_DISPLAY_LENGTH - 3]}..."
        self.list_text.setText(display_text)
        self.list_text.setToolTip(full_text if display_text != full_text else "")

    ModifyListItem.update_value = patched_list_update_value

    # 3. Patch ModifyListDialog.__init__ and confirm
    _orig_dialog_init = ModifyListDialog.__init__

    def patched_dialog_init(self, items, parent, options_available=None, allow_duplication=False):
        _orig_dialog_init(self, items, parent, options_available=options_available, allow_duplication=allow_duplication)
        if self.options_available is None:
            self.item_tr_map = {}
            self.list_widget.clear()
            display_items = []
            for item in self.original_items:
                tr = og.app.tr(str(item))
                self.item_tr_map[tr] = str(item)
                display_items.append(tr)
            self.list_widget.addItems(display_items)

    def patched_dialog_confirm(self):
        items_text = [self.list_widget.item(i).text() for i in range(self.list_widget.count())]
        if self.options_available is not None:
            items_text = [self.source_by_display.get(text, text) for text in items_text]
        else:
            reverse = getattr(og.app, "reverse_tr", None)
            item_map = getattr(self, "item_tr_map", {})
            items_text = [item_map.get(text, reverse(text) if reverse else text) for text in items_text]
        self.list_modified.emit(items_text)
        self.close()

    ModifyListDialog.__init__ = patched_dialog_init
    ModifyListDialog.confirm = patched_dialog_confirm

    # 4. Patch LabelAndLineEdit
    def patched_line_update_value(self):
        value = self.config.get(self.key)
        display_val = og.app.tr(value) if isinstance(value, str) else (value or "")
        self.line_edit.setText(display_val)
        self._update_width(display_val)

    def patched_line_value_changed(self, value):
        reverse = getattr(og.app, "reverse_tr", None)
        canonical_val = reverse(value) if reverse else value
        self.update_config(canonical_val)
        self._update_width(value)

    LabelAndLineEdit.update_value = patched_line_update_value
    LabelAndLineEdit.value_changed = patched_line_value_changed

    App._mbg_kes_i18n_patched = True
