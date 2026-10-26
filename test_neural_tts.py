import asyncio
import base64
import io
import json
import queue
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import browser_workflow as workflow
import deck2audio as core
import neural_tts
import neural_tts_worker as worker


def recording(seconds=6, *, silent=False):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes((b"\0\0" if silent else b"\0\x10") * (seconds * 24000))
    return output.getvalue()


class VoiceReferenceTests(unittest.TestCase):
    def test_requires_consent_and_saves_immutable_content_addressed_wav(self):
        with tempfile.TemporaryDirectory() as temp:
            proj = Path(temp)
            with self.assertRaisesRegex(ValueError, "permission"):
                neural_tts.save_reference(proj, recording(), consent=False)
            self.assertFalse((proj / "voices").exists())
            first = neural_tts.save_reference(proj, recording(), consent=True)
            self.assertEqual(first.read_bytes(), recording())
            self.assertEqual(first, neural_tts.save_reference(proj, recording(), consent=True))
            second = neural_tts.save_reference(proj, recording(7), consent=True)
            self.assertNotEqual(first, second)
            settings = ("script", str(first), "+0%", "+0Hz", 1.2, 0.8)
            self.assertNotEqual(workflow.audio_signature(*settings, backend="chatterbox"),
                                workflow.audio_signature("script", str(second), "+0%", "+0Hz",
                                                         1.2, 0.8, backend="chatterbox"))

    def test_rejects_invalid_quiet_short_long_truncated_and_oversized_recordings(self):
        for data in (b"not wav", recording(4), recording(31), recording(silent=True),
                     recording()[:-30], b"x" * (neural_tts.MAX_RECORDING_BYTES + 1)):
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                neural_tts.validate_recording(data)

    def test_settings_reject_unsupported_rate_pitch_and_missing_reference(self):
        for engine, voice in ((neural_tts.vibevoice, "Emma"), (neural_tts.chatterbox, "")):
            with self.assertRaises(ValueError):
                engine.validate_settings(voice, "+10%", "+0Hz")
            with self.assertRaises(ValueError):
                engine.validate_settings(voice, "+0%", "+1Hz")
        with self.assertRaises(ValueError):
            neural_tts.vibevoice.validate_settings("missing", "+0%", "+0Hz")
        with self.assertRaises(ValueError):
            neural_tts.chatterbox.validate_settings("", "+0%", "+0Hz")
        with self.assertRaises(ValueError):
            asyncio.run(neural_tts.vibevoice.synth_pcm("", "Emma", "+0%", "+0Hz"))


class WorkerTests(unittest.TestCase):
    def test_missing_environment_has_explicit_setup_error(self):
        with tempfile.TemporaryDirectory() as temp, patch("neural_tts.ROOT", Path(temp)):
            with self.assertRaisesRegex(RuntimeError, "setup_offline_tts.py vibevoice"):
                neural_tts.Worker("vibevoice").synthesize("Hello", "Emma")

    def test_worker_protocol_reuses_process_and_preserves_unicode_text(self):
        local = neural_tts.Worker("vibevoice")
        process = MagicMock()
        process.poll.return_value = None
        local.process = process
        pcm = b"\x01\0" * 10
        for _ in range(2):
            local.responses.put(json.dumps({"pcm": base64.b64encode(pcm).decode()}))
            self.assertEqual(local.synthesize("Let's learn — together.", "Emma"), pcm)
        self.assertEqual(process.stdin.write.call_count, 2)
        request = json.loads(process.stdin.write.call_args.args[0])
        self.assertEqual(request["text"], "Let's learn — together.")

    def test_worker_errors_are_not_successful_audio(self):
        for line in ("", "garbage", "{}", '{"pcm":"!"}', '{"pcm":""}', '{"error":"Model missing"}'):
            local = neural_tts.Worker("vibevoice")
            local.process = MagicMock()
            local.process.poll.return_value = None
            local.responses.put(line)
            with patch.object(local, "close"), self.assertRaises(RuntimeError):
                local.synthesize("Hello", "Emma")

    def test_timeout_stops_the_worker(self):
        local = neural_tts.Worker("vibevoice")
        local.process = MagicMock()
        local.process.poll.return_value = None
        with patch.object(local.responses, "get", side_effect=queue.Empty), \
                patch.object(local, "close") as close:
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                local.synthesize("Hello", "Emma")
            close.assert_called_once()

    def test_network_guard_rejects_dns_and_connections(self):
        for event in ("socket.connect", "socket.getaddrinfo"):
            with self.assertRaisesRegex(RuntimeError, "Network access is disabled"):
                worker.block_network(event, ())
        worker.block_network("open", ())

    def test_chunks_preserve_all_words_and_respect_limits(self):
        text = " ".join(f"word{i}." if i % 10 == 0 else f"word{i}" for i in range(601))
        for limit in (35, 250):
            chunks = worker.split_text(text, limit)
            self.assertEqual(" ".join(chunks), text)
            self.assertTrue(all(0 < len(chunk.split()) <= limit for chunk in chunks))

    def test_subprocess_environment_forces_offline_and_disables_telemetry(self):
        local = neural_tts.Worker("vibevoice")
        process = MagicMock()
        process.stdout = iter([])
        with patch("neural_tts.environment_python", return_value=Path(__file__)), \
                patch("neural_tts.subprocess.Popen", return_value=process) as launch:
            local._start()
        environment = launch.call_args.kwargs["env"]
        self.assertEqual(environment["HF_HUB_OFFLINE"], "1")
        self.assertEqual(environment["TRANSFORMERS_OFFLINE"], "1")
        self.assertEqual(environment["HF_HUB_DISABLE_TELEMETRY"], "1")


class NeuralRoutingTests(unittest.TestCase):
    def test_previews_and_generation_route_locally_for_both_engines(self):
        for name, voice in (("vibevoice", "Emma"), ("chatterbox", "reference.wav")):
            engine = core.LOCAL_ENGINES[name]
            with self.subTest(backend=name), tempfile.TemporaryDirectory() as temp:
                output = Path(temp) / "audio.mp3"
                pcm = b"\x01\0" * 10
                with patch.object(type(engine), "validate_settings"), \
                        patch.object(type(engine), "synth_pcm", new=AsyncMock(return_value=pcm)) as synth, \
                        patch("pcm_audio.encode_mp3", side_effect=lambda data: b"mp3" + data), \
                        patch("edge_tts.Communicate", side_effect=AssertionError("Edge called")):
                    preview = asyncio.run(core.synth_chunk("Preview", voice, "+0%", "+0Hz", backend=name))
                    self.assertEqual(preview, b"mp3" + pcm)
                    asyncio.run(core.generate_audio(
                        Path(temp), {1: "First [pause] next", 2: "Second"}, voice,
                        "+0%", "+0Hz", 0.2, 0.1, output, backend=name))
                combined = pcm + bytes(4800) + pcm + bytes(9600) + pcm
                self.assertEqual(output.read_bytes(), b"mp3" + combined)
                self.assertEqual(synth.await_count, 4)

    def test_failed_worker_does_not_record_audio_success(self):
        with tempfile.TemporaryDirectory() as temp:
            proj = Path(temp)
            with patch.object(neural_tts.Worker, "synthesize", side_effect=RuntimeError("Model missing")):
                with self.assertRaisesRegex(RuntimeError, "Model missing"):
                    asyncio.run(core.generate_audio(proj, {1: "Test"}, "Emma", "+0%", "+0Hz",
                                                    0, 0, proj / "output.mp3", backend="vibevoice"))
            self.assertNotIn("audio", core.load_state(proj))

    def test_cli_routes_new_backends(self):
        for name, options, voice in (
            ("vibevoice", [], "Emma"),
            ("vibevoice", ["--vibevoice-voice", "Grace"], "Grace"),
            ("chatterbox", ["--voice-reference", "/tmp/own.wav"], "/tmp/own.wav"),
        ):
            with patch("sys.argv", ["deck2audio.py", "voice-test", "--backend", name, *options]), \
                    patch("deck2audio.preview_voice", new=AsyncMock()) as preview:
                core.main()
            preview.assert_awaited_once_with(voice, "+0%", "+0Hz", Path("voice_sample.mp3"), backend=name)
            args = SimpleNamespace(backend=name, vibevoice_voice=voice, voice_reference=voice,
                                   output="/tmp/output.mp3", rate="+0%", pitch="+0Hz", slide_gap=1.2, pause=0.8)
            with patch("deck2audio.tts_async", new=AsyncMock()) as synth:
                core.tts(Path("/tmp"), args)
            synth.assert_awaited_once_with(Path("/tmp"), voice, "+0%", "+0Hz", 1.2, 0.8,
                                          Path("/tmp/output.mp3"), backend=name)


if __name__ == "__main__":
    unittest.main()
