import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import deck2audio


class SkipAllTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.proj = Path(self.temp.name)
        self.slides = [
            {"number": 1, "title": "Title", "body": ["Unused body"], "notes": "Use these notes."},
            {"number": 2, "title": "Fallback", "body": ["First point", "Second point"], "notes": ""},
        ]
        (self.proj / "slides.json").write_text(json.dumps(self.slides))
        deck2audio.save_state(self.proj, {"extracted": True, "research": {"academic": "approved"}})

    def test_notes_and_slide_text_fallback(self):
        sections = deck2audio.deck_script_sections(self.slides)
        self.assertEqual(sections, {1: "Use these notes.", 2: "Fallback\n\nFirst point\n\nSecond point"})

    def test_empty_slide_reports_error(self):
        with self.assertRaisesRegex(SystemExit, "Slide 3 has no usable text"):
            deck2audio.deck_script_sections([{"number": 3, "title": "", "body": [], "notes": ""}])

    def test_skip_all_approves_without_llm_or_research(self):
        with patch("deck2audio.ask", return_value="a"), \
                patch("deck2audio.human_in_the_loop", side_effect=AssertionError("LLM called")), \
                patch("deck2audio.approved_research", side_effect=AssertionError("Research read")):
            deck2audio.script(self.proj, 15, "", None, skip_all=True)
        self.assertEqual(deck2audio.parse_script((self.proj / "script.md").read_text()),
                         deck2audio.deck_script_sections(self.slides))
        self.assertEqual(deck2audio.load_state(self.proj)["script"], "approved")
        self.assertEqual(deck2audio.load_state(self.proj)["research"], {"academic": "approved"})
        self.assertEqual(list(self.proj.glob("script_prompt_*.txt")), [])

    def test_interactive_skip_all_keeps_final_review(self):
        with patch("deck2audio.ask", side_effect=["s", "a"]) as ask:
            deck2audio.script(self.proj, 15, "", None)
        self.assertEqual(ask.call_count, 2)
        self.assertTrue((self.proj / "script.md").exists())

    def test_cancel_saves_only_draft(self):
        with patch("deck2audio.ask", return_value="c"):
            deck2audio.script(self.proj, 15, "", None, skip_all=True)
        self.assertTrue((self.proj / "script.draft.md").exists())
        self.assertFalse((self.proj / "script.md").exists())
        self.assertNotEqual(deck2audio.load_state(self.proj).get("script"), "approved")

    def test_edit_before_approval(self):
        edited = "## Slide 1\n\nEdited notes.\n\n## Slide 2\n\nEdited fallback."
        with patch("deck2audio.ask", side_effect=["e", "a"]), \
                patch("deck2audio.edit_in_editor", return_value=edited):
            deck2audio.script(self.proj, 15, "", None, skip_all=True)
        self.assertEqual((self.proj / "script.md").read_text(), edited)

    def test_existing_approved_script_is_preserved(self):
        (self.proj / "script.md").write_text("Existing script")
        state = deck2audio.load_state(self.proj)
        state["script"] = "approved"
        deck2audio.save_state(self.proj, state)
        with patch("deck2audio.ask", return_value="n") as ask:
            deck2audio.script(self.proj, 15, "", None, skip_all=True)
        self.assertEqual(ask.call_count, 1)
        self.assertEqual((self.proj / "script.md").read_text(), "Existing script")

    def test_cancel_replacement_stops_run_before_tts(self):
        (self.proj / "script.md").write_text("Existing script")
        state = deck2audio.load_state(self.proj)
        state["script"] = "approved"
        deck2audio.save_state(self.proj, state)
        with patch("sys.argv", ["deck2audio.py", "run", str(self.proj), "--skip-all"]), \
                patch("deck2audio.ask", side_effect=["y", "c"]), \
                patch("deck2audio.tts", side_effect=AssertionError("TTS called")):
            deck2audio.main()
        self.assertEqual(deck2audio.load_state(self.proj)["script"], "draft")
        self.assertEqual((self.proj / "script.md").read_text(), "Existing script")

    def test_script_flag_keeps_only_final_review(self):
        with patch("sys.argv", ["deck2audio.py", "script", str(self.proj), "--skip-all"]), \
                patch("deck2audio.ask", side_effect=["a"]) as ask:
            deck2audio.main()
        self.assertEqual(ask.call_count, 1)
        self.assertEqual(deck2audio.load_state(self.proj)["script"], "approved")

    def test_run_proceeds_to_tts_after_approval(self):
        with patch("sys.argv", ["deck2audio.py", "run", str(self.proj), "--skip-all"]), \
                patch("deck2audio.ask", side_effect=["a"]), \
                patch("deck2audio.research", side_effect=AssertionError("Research called")), \
                patch("deck2audio.tts") as tts:
            deck2audio.main()
        tts.assert_called_once()
        self.assertEqual(deck2audio.load_state(self.proj)["script"], "approved")

    def test_empty_deck_reports_error(self):
        (self.proj / "slides.json").write_text("[]")
        with self.assertRaisesRegex(SystemExit, "No slides found"):
            deck2audio.script(self.proj, 15, "", None, skip_all=True)

    def test_llm_path_still_works(self):
        result = "## Slide 1\n\nLLM notes.\n\n## Slide 2\n\nLLM fallback."
        with patch("deck2audio.human_in_the_loop", return_value=result) as llm, \
                patch("deck2audio.ask", return_value="a"):
            deck2audio.script(self.proj, 15, "", None, skip_all=False)
        llm.assert_called_once()
        self.assertTrue((self.proj / "script_prompt_1.txt").exists())
        self.assertEqual(deck2audio.load_state(self.proj)["script"], "approved")

    def test_run_bypasses_research_and_stops_on_cancel(self):
        for flag in ([], ["--skip-all"]):
            with self.subTest(flag=flag), \
                    patch("sys.argv", ["deck2audio.py", "run", str(self.proj), *flag]), \
                    patch("deck2audio.ask", side_effect=["c"] if flag else ["s", "c"]), \
                    patch("deck2audio.research", side_effect=AssertionError("Research called")), \
                    patch("deck2audio.human_in_the_loop", side_effect=AssertionError("LLM called")), \
                    patch("deck2audio.tts", side_effect=AssertionError("TTS called")):
                deck2audio.main()
            self.assertTrue((self.proj / "script.draft.md").exists())


if __name__ == "__main__":
    unittest.main()
