import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np

import deck2audio as core
import kokoro_tts
import pcm_audio


class KokoroVoiceTests(unittest.TestCase):
    def tearDown(self):
        kokoro_tts._engine.cache_clear()

    def test_rate_pitch_and_voice_validation(self):
        for rate, speed in (("+0%", 1.0), ("-50%", 0.5), ("+100%", 2.0)):
            self.assertEqual(kokoro_tts.validate_settings("af_heart", rate, "+0Hz"), speed)
        for voice, rate, pitch in (("missing", "+0%", "+0Hz"), ("af_heart", "-51%", "+0Hz"),
                                   ("af_heart", "+101%", "+0Hz"), ("af_heart", "fast", "+0Hz"),
                                   ("af_heart", "+0%", "+2Hz")):
            with self.subTest(voice=voice, rate=rate, pitch=pitch), self.assertRaises(ValueError):
                kokoro_tts.validate_settings(voice, rate, pitch)

    def test_empty_text_is_rejected_before_loading_model(self):
        with patch("kokoro_tts._engine", side_effect=AssertionError("Model loaded")):
            with self.assertRaisesRegex(ValueError, "empty"):
                asyncio.run(kokoro_tts.synth_pcm("  ", "af_heart", "+0%", "+0Hz"))

    def test_missing_dependency_has_setup_instructions(self):
        with patch.dict("sys.modules", {"kokoro_onnx": None}):
            with self.assertRaisesRegex(RuntimeError, "requirements-kokoro.txt"):
                kokoro_tts._engine()

    def test_missing_models_have_setup_instructions(self):
        with tempfile.TemporaryDirectory() as temp, \
                patch("kokoro_tts.MODEL_DIR", Path(temp)), \
                patch.dict("sys.modules", {"kokoro_onnx": SimpleNamespace(Kokoro=MagicMock())}):
            with self.assertRaisesRegex(RuntimeError, "model files are missing"):
                kokoro_tts._engine()

    def test_model_is_loaded_once_from_local_paths(self):
        constructor = MagicMock()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("kokoro-v1.0.onnx", "voices-v1.0.bin"):
                (root / name).touch()
            with patch("kokoro_tts.MODEL_DIR", root), \
                    patch.dict("sys.modules", {"kokoro_onnx": SimpleNamespace(Kokoro=constructor)}):
                self.assertIs(kokoro_tts._engine(), kokoro_tts._engine())
            constructor.assert_called_once_with(str(root / "kokoro-v1.0.onnx"), str(root / "voices-v1.0.bin"))

    def test_speech_converts_float_audio_to_mono_little_endian_pcm(self):
        engine = MagicMock()
        engine.create.return_value = (np.array([-2, -0.5, 0, 0.5, 2], dtype=np.float32), 24000)
        with patch("kokoro_tts._engine", return_value=engine):
            pcm = asyncio.run(kokoro_tts.synth_pcm("Test", "af_bella", "+20%", "+0Hz"))
        engine.create.assert_called_once_with("Test", voice="af_bella", speed=1.2, lang="en-us")
        self.assertEqual(np.frombuffer(pcm, dtype="<i2").tolist(), [-32767, -16383, 0, 16383, 32767])

    def test_invalid_model_output_is_an_error(self):
        for audio, sample_rate in ((np.array([]), 24000), (np.array([np.nan]), 24000),
                                   (np.array([np.inf]), 24000), (np.zeros((2, 2)), 24000),
                                   (np.ones(10), 44100)):
            with self.subTest(audio=audio, sample_rate=sample_rate):
                engine = MagicMock()
                engine.create.return_value = (audio, sample_rate)
                with patch("kokoro_tts._engine", return_value=engine), self.assertRaises(RuntimeError):
                    asyncio.run(kokoro_tts.synth_pcm("Test", "af_heart", "+0%", "+0Hz"))

    def test_synthesis_failure_is_not_hidden(self):
        engine = MagicMock()
        engine.create.side_effect = RuntimeError("Model failed")
        with patch("kokoro_tts._engine", return_value=engine):
            with self.assertRaisesRegex(RuntimeError, "Model failed"):
                asyncio.run(kokoro_tts.synth_pcm("Test", "af_heart", "+0%", "+0Hz"))


class KokoroAudioTests(unittest.TestCase):
    def test_preview_never_calls_online_or_macos_speech(self):
        with patch("kokoro_tts.synth_pcm", new=AsyncMock(return_value=b"\x01\x00")) as synth, \
                patch("pcm_audio.encode_mp3", return_value=b"mp3"), \
                patch("macos_tts.synth_pcm", side_effect=AssertionError("macOS called")), \
                patch("edge_tts.Communicate", side_effect=AssertionError("Edge called")):
            audio = asyncio.run(core.synth_chunk("Test", "af_heart", "+0%", "+0Hz", backend="kokoro"))
        self.assertEqual(audio, b"mp3")
        synth.assert_awaited_once_with("Test", "af_heart", "+0%", "+0Hz")

    def test_generation_preserves_exact_pauses_gaps_and_slide_clips(self):
        with tempfile.TemporaryDirectory() as temp:
            proj = Path(temp)
            output = proj / "narrated.mp3"
            pcm = b"\x01\x00" * 12
            encoded = []
            updates = []

            def encode(data):
                encoded.append(data)
                return b"mp3:" + data

            with patch("kokoro_tts.synth_pcm", new=AsyncMock(return_value=pcm)) as synth, \
                    patch("pcm_audio.encode_mp3", side_effect=encode), \
                    patch("macos_tts.synth_pcm", side_effect=AssertionError("macOS called")), \
                    patch("edge_tts.Communicate", side_effect=AssertionError("Edge called")):
                asyncio.run(core.generate_audio(
                    proj, {2: "Second", 1: "First [pause] next"}, "am_michael", "-10%", "+0Hz",
                    0.2, 0.1, output, backend="kokoro",
                    progress=lambda done, total: updates.append((done, total))))
            slide = pcm + pcm_audio.silence(0.1) + pcm
            self.assertEqual(encoded, [slide, pcm, slide + pcm_audio.silence(0.2) + pcm])
            self.assertEqual((proj / "audio/slide_001.mp3").read_bytes(), b"mp3:" + slide)
            self.assertEqual(output.read_bytes(), b"mp3:" + encoded[-1])
            self.assertEqual(core.load_state(proj)["audio"], str(output))
            self.assertEqual(updates, [(1, 2), (2, 2)])
            self.assertEqual(synth.await_count, 3)

    def test_failed_generation_does_not_record_success(self):
        with tempfile.TemporaryDirectory() as temp:
            proj = Path(temp)
            output = proj / "narrated.mp3"
            with patch("kokoro_tts.synth_pcm", new=AsyncMock(side_effect=RuntimeError("Model failed"))):
                with self.assertRaisesRegex(RuntimeError, "Model failed"):
                    asyncio.run(core.generate_audio(proj, {1: "Test"}, "af_heart", "+0%", "+0Hz",
                                                    0, 0, output, backend="kokoro"))
            self.assertFalse(output.exists())
            self.assertNotIn("audio", core.load_state(proj))

    def test_cli_routes_preview_and_default_voice(self):
        for options, voice in (([], "af_heart"), (["--kokoro-voice", "am_michael"], "am_michael")):
            with patch("sys.argv", ["deck2audio.py", "voice-test", "--backend", "kokoro", *options]), \
                    patch("deck2audio.preview_voice", new=AsyncMock()) as preview:
                core.main()
            preview.assert_awaited_once_with(voice, "+0%", "+0Hz", Path("voice_sample.mp3"), backend="kokoro")

    def test_cli_routes_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            proj = Path(temp)
            args = SimpleNamespace(backend="kokoro", kokoro_voice="af_bella", voice="edge-voice",
                                   rate="-10%", pitch="+0Hz", slide_gap=1.2, pause=0.8,
                                   output=str(proj / "output.mp3"))
            with patch("deck2audio.tts_async", new=AsyncMock()) as tts:
                core.tts(proj, args)
            tts.assert_awaited_once_with(proj, "af_bella", "-10%", "+0Hz", 1.2, 0.8,
                                        proj / "output.mp3", backend="kokoro")


if __name__ == "__main__":
    unittest.main()
