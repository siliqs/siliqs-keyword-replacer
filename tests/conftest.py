# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")


def call(handler, src, dst, keywords, options):
    """呼叫 handler 並統一回傳 (取代次數, 警告訊息)。"""
    outcome = handler.process(src, dst, list(keywords), options)
    return outcome if isinstance(outcome, tuple) else (outcome, "")
