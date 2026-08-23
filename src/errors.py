# -*- coding: utf-8 -*-
"""共用例外。

`SkipReason` 代表「檔案本身沒問題，是我們目前處理不了」——上層記為 SKIP 而非 FAIL，
使用者才分得出「程式壞了」與「這個檔需要人工或尚未支援」。
"""
from __future__ import annotations


class SkipReason(Exception):
    """已知且可解釋的無法處理原因，記為 SKIP。"""
