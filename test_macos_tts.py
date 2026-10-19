import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import deck2audio as core
import macos_tts
import pcm_audio


class MacOSVoiceTests(unittest.TestCase):
    def test_availability_requires_macos_and_say(self):
        with patch("macos_tts.sys.platform", "win32"), patch("macos_tts.shutil.which", return_value="/bin/say"):
            self.assertFalse(macos_tts.available())
        with patch("macos_tts.sys.platform", "darwin"), patch("macos_tts.shutil.which", return_value=None):
            self.assertFalse(macos_tts.available())

    def test_voice_list_preserves_spaces_and_locale(self):
        result = subprocess.CompletedProcess([], 0, "Bad News    en_US # Hello\nSamantha    en_US # Hello\n", "")
        with patch("macos_tts.available", return_value=True), patch("macos_tts.subprocess.run", return_value=result):
            self.assertEqual(macos_tts.list_voices(), {"Bad News": "en_US", "Samantha": "en_US"})

    def test_failed_and_empty_voice_lists_are_errors(self):
        for result in (subprocess.CompletedProcess([], 1, "", "speech unavailable"),
                       subprocess.CompletedProcess([], 0, "", "")):
            with self.subTest(result=result), patch("macos_tts.available", return_value=True), \
                    patch("macos_tts.subprocess.run", return_value=result):
                with self.assertRaises(RuntimeError):
                    macos_tts.list_voices()

    def test_rate_pitch_and_voice_validation(self):
        with patch("macos_tts.available", return_value=True), \
                patch("macos_tts.list_voices", return_value={"Samantha": "en_US"}):
            self.assertEqual(macos_tts.validate_settings("Samantha", "+0%", "+0Hz"), 175)
            self.assertEqual(macos_tts.validate_settings("", "+20%", "+0Hz"), 210)
            for voice, rate, pitch in (("missing", "+0%", "+0Hz"), ("", "-100%", "+0Hz"),
                                       ("", "fast", "+0Hz"), ("", "+0%", "+2Hz")):
                with self.subTest(voice=voice, rate=rate, pitch=pitch), self.assertRaises(ValueError):
                    macos_tts.validate_settings(voice, rate, pitch)

    def test_speech_failure_reports_stderr(self):
        process = MagicMock(returncode=1)
        process.communicate = AsyncMock(return_value=(b"", b"Voice unavailable"))
        with patch("macos_tts.validate_settings", return_value=175), \
                patch("macos_tts.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)):
            with self.assertRaisesRegex(RuntimeError, "Voice unavailable"):
                asyncio.run(macos_tts.synth_pcm("Test", "", "+0%", "+0Hz"))

    def test_speech_uses_a_text_file_not_shell_arguments(self):
        process = MagicMock(returncode=0)
        process.communicate = AsyncMock(return_value=(b"", b""))
        pcm = b"\x01\x00" * 240
        captured = []

        async def launch(*args, **kwargs):
            import wave

            captured.extend(args)
            source = Path(args[args.index("-f") + 1])
            self.assertEqual(source.read_text(), "-not-a-command; $(test)")
            with wave.open(args[args.index("-o") + 1], "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(macos_tts.SAMPLE_RATE)
                audio.writeframes(pcm)
            return process

        with patch("macos_tts.validate_settings", return_value=175), \
                patch("macos_tts.asyncio.create_subprocess_exec", side_effect=launch):
            result = asyncio.run(macos_tts.synth_pcm("-not-a-command; $(test)", "Bad News", "+0%", "+0Hz"))
        self.assertEqual(result, pcm)
        self.assertEqual(captured[-2:], ["-v", "Bad News"])
        self.assertFalse(Path(captured[captured.index("-f") + 1]).exists())

    def test_missing_encoder_has_actionable_error(self):
        with patch.dict("sys.modules", {"lameenc": None}):
            with self.assertRaisesRegex(RuntimeError, "encoder is missing"):
                pcm_audio.encode_mp3(b"\0\0")


class LocalAudioTests(unittest.TestCase):
    def test_local_preview_never_calls_edge(self):
        with patch("macos_tts.synth_pcm", new=AsyncMock(return_value=b"\x01\x00")) as synth, \
                patch("pcm_audio.encode_mp3", return_value=b"mp3"), \
                patch("edge_tts.Communicate", side_effect=AssertionError("Online speech called")):
            audio = asyncio.run(core.synth_chunk("Test", "", "+0%", "+0Hz", backend="macos"))
        self.assertEqual(audio, b"mp3")
        synth.assert_awaited_once_with("Test", "", "+0%", "+0Hz")

    def test_local_generation_assembles_exact_pcm_pauses_and_gaps(self):
        with tempfile.TemporaryDirectory() as temp:
            proj = Path(temp)
            output = proj / "narrated.mp3"
            pcm = b"\x01\x00" * 12
            encoded = []
            updates = []

            def encode(data):
                encoded.append(data)
                return b"mp3:" + data

            with patch("macos_tts.validate_settings"), \
                    patch("macos_tts.synth_pcm", new=AsyncMock(return_value=pcm)), \
                    patch("pcm_audio.encode_mp3", side_effect=encode), \
                    patch("deck2audio.synth_chunk", side_effect=AssertionError("Online speech called")):
                asyncio.run(core.generate_audio(
                    proj, {1: "First [pause] next", 2: "Second"}, "", "+0%", "+0Hz",
                    0.2, 0.1, output, backend="macos",
                    progress=lambda done, total: updates.append((done, total))))
            slide = pcm + bytes(4800) + pcm
            self.assertEqual(encoded, [slide, pcm, slide + bytes(9600) + pcm])
            self.assertEqual((proj / "audio/slide_001.mp3").read_bytes(), b"mp3:" + slide)
            self.assertEqual(output.read_bytes(), b"mp3:" + encoded[-1])
            self.assertEqual(core.load_state(proj)["audio"], str(output))
            self.assertEqual(updates, [(1, 2), (2, 2)])

    def test_local_failure_does_not_record_success(self):
        with tempfile.TemporaryDirectory() as temp:
            proj = Path(temp)
            output = proj / "narrated.mp3"
            with patch("macos_tts.validate_settings"), \
                    patch("macos_tts.synth_pcm", new=AsyncMock(side_effect=RuntimeError("Speech failed"))):
                with self.assertRaisesRegex(RuntimeError, "Speech failed"):
                    asyncio.run(core.generate_audio(proj, {1: "Test"}, "", "+0%", "+0Hz",
                                                    0, 0, output, backend="macos"))
            self.assertFalse(output.exists())
            self.assertNotIn("audio", core.load_state(proj))

    def test_cli_routes_local_preview(self):
        with patch("sys.argv", ["deck2audio.py", "voice-test", "--backend", "macos",
                                "--macos-voice", "Bad News"]), \
                patch("deck2audio.preview_voice", new=AsyncMock()) as preview:
            core.main()
        preview.assert_awaited_once_with("Bad News", "+0%", "+0Hz", Path("voice_sample.mp3"), backend="macos")

    def test_cli_routes_local_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            proj = Path(temp)
            args = MagicMock(backend="macos", macos_voice="Samantha", voice="edge-voice",
                             rate="+10%", pitch="+0Hz", slide_gap=1.2, pause=0.8,
                             output=str(proj / "output.mp3"))
            with patch("deck2audio.tts_async", new=AsyncMock()) as tts:
                core.tts(proj, args)
            tts.assert_awaited_once_with(proj, "Samantha", "+10%", "+0Hz", 1.2, 0.8,
                                        proj / "output.mp3", backend="macos")


if __name__ == "__main__":
    unittest.main()
