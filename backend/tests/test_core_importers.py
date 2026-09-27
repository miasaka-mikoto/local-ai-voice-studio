from __future__ import annotations

import unittest

from app.importers import parse_import


class ImporterTests(unittest.TestCase):
    def test_srt_and_ass_preserve_timing(self) -> None:
        srt = """1
00:00:01,250 --> 00:00:03,500
<i>こんにちは</i>

2
00:00:04,000 --> 00:00:05,200
またね
"""
        result = parse_import("srt", srt)
        self.assertEqual(2, len(result.lines))
        self.assertEqual(1250, result.lines[0]["start_ms"])
        self.assertEqual(2250, result.lines[0]["duration_budget_ms"])
        self.assertEqual("こんにちは", result.lines[0]["text"])

        ass = """[Script Info]
Title: smoke
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:02.50,Default,Alice,0,0,0,,{\\i1}行こう\\N今すぐ
"""
        parsed_ass = parse_import("ass", ass)
        self.assertEqual("Alice", parsed_ass.lines[0]["speaker"])
        self.assertEqual("行こう\n今すぐ", parsed_ass.lines[0]["text"])
        self.assertEqual(1500, parsed_ass.lines[0]["duration_limit_ms"])

    def test_game_formats_normalize_fields(self) -> None:
        csv_text = (
            "line_id,scene_id,character_id,text,emotion,locale,duration_limit,asset_name\n"
            "L001,S01,C01,開始します,happy,ja-JP,1800,voice_001\n"
        )
        csv_result = parse_import("csv", csv_text)
        self.assertEqual("L001", csv_result.lines[0]["external_line_id"])
        self.assertEqual("C01", csv_result.lines[0]["character_external_id"])
        self.assertEqual(1800, csv_result.lines[0]["duration_limit_ms"])

        json_result = parse_import("json", '{"lines":[{"line_id":"L2","text":"了解"}]}')
        jsonl_result = parse_import("jsonl", '{"line_id":"L3","text":"はい"}\n')
        self.assertEqual("L2", json_result.lines[0]["external_line_id"])
        self.assertEqual("L3", jsonl_result.lines[0]["external_line_id"])


if __name__ == "__main__":
    unittest.main()
