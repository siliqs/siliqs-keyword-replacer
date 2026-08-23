# -*- coding: utf-8 -*-
from src.config import MatchOptions
from src.replacer import normalize_keywords, replace_text


def test_case_sensitive_by_default():
    text, count = replace_text("Secret secret", ["Secret"], MatchOptions())
    assert text == "snoopy secret"
    assert count == 1


def test_ignore_case():
    text, count = replace_text("Secret secret", ["Secret"], MatchOptions(case_sensitive=False))
    assert text == "snoopy snoopy"
    assert count == 2


def test_substring_hits_by_default():
    text, count = replace_text("Secretive", ["Secret"], MatchOptions())
    assert text == "snoopyive"
    assert count == 1


def test_whole_word_blocks_substring():
    text, count = replace_text("Secretive Secret", ["Secret"], MatchOptions(whole_word=True))
    assert text == "Secretive snoopy"
    assert count == 1


def test_whole_word_does_not_break_chinese():
    # 中文不做斷詞，開啟全字比對仍應命中（\b 對 CJK 無意義）
    text, count = replace_text("這是機密文件", ["機密"], MatchOptions(whole_word=True))
    assert text == "這是snoopy文件"
    assert count == 1


def test_longer_keyword_wins():
    text, _ = replace_text("最高機密", ["機密", "最高機密"], MatchOptions())
    assert text == "snoopy"


def test_normalize_dedupes_and_sorts():
    assert normalize_keywords([" a ", "a", "", "abc"]) == ["abc", "a"]


def test_no_keyword_is_noop():
    text, count = replace_text("原文不動", [" "], MatchOptions())
    assert text == "原文不動"
    assert count == 0
