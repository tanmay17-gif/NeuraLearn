import base64
import subprocess
import unittest
from unittest.mock import AsyncMock, Mock, patch
import tempfile
from pathlib import Path

from fastapi import HTTPException
from api import router
from services import frame_extraction


class VisualFocusTests(unittest.IsolatedAsyncioTestCase):
    def test_extracts_explicit_timestamps_without_treating_other_numbers_as_times(self):
        self.assertEqual(
            router._extract_focus_timestamps(
                "Explain the diagram at 02:15 and compare it with the chart at 1:04:30."
            ),
            ["02:15", "1:04:30"],
        )
        self.assertEqual(
            router._extract_focus_timestamps(
                "Explain the three stages and the diagram on slide 2."
            ),
            [],
        )
        self.assertEqual(
            router._extract_focus_timestamps(
                "Can you explain the diagram on 0.50min in the video?"
            ),
            ["00:50"],
        )

    async def test_visual_focus_without_timestamp_analyzes_representative_frames(self):
        with patch.object(
            router.engine,
            "generate_visual_analysis",
            new_callable=AsyncMock,
            return_value="The frame shows a labeled process diagram.",
        ) as analyze_frames:
            enriched_prompt = await router.inject_frame_explanations(
                "local-video.mp4",
                "Please tell me about this.",
                is_youtube=False,
                user_id="test-user",
            )

        analyze_frames.assert_awaited_once_with(
            transcript="",
            video_url="local-video.mp4",
            user_id="test-user",
            dynamic_extra="Please tell me about this.",
            is_youtube=False,
            max_frames=8,
        )
        self.assertIn("AUTOMATIC VISUAL ANALYSIS", enriched_prompt)
        self.assertIn("labeled process diagram", enriched_prompt)
        self.assertIn("not a specific timeline position", enriched_prompt)

    async def test_visual_focus_with_timestamp_analyzes_the_exact_frame(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            frame_path = str(Path(temp_dir) / "frame.jpg")
            with (
                patch(
                    "services.frame_extraction.extract_frame_at_timestamp",
                    new_callable=AsyncMock,
                    return_value=frame_path,
                ) as extract_frame,
                patch(
                    "services.vision_client.explain_frame_with_vision",
                    new_callable=AsyncMock,
                    return_value={
                        "explanation": "A diagram labels the three processing stages.",
                        "provider": "gemini",
                    },
                ) as explain_frame,
            ):
                enriched_prompt = await router.inject_frame_explanations(
                    "local-video.mp4",
                    "Summarize the diagram at 02:15.",
                    is_youtube=False,
                    user_id="test-user",
                    jwt="test-user-jwt",
                )

        extract_frame.assert_awaited_once_with(
            "local-video.mp4",
            "02:15",
            is_remote=False,
            http_headers=None,
        )
        explain_frame.assert_awaited_once_with(
            frame_path,
            "test-user",
            "Explain the visible content, especially any diagram, chart, or text.",
            jwt="test-user-jwt",
        )
        self.assertIn("timestamp 02:15 (requested frame)", enriched_prompt)
        self.assertIn("three processing stages", enriched_prompt)
        self.assertNotIn("representative frames", enriched_prompt)

    async def test_youtube_timestamp_resolution_does_not_require_redis(self):
        with patch("yt_dlp.YoutubeDL") as youtube_dl:
            youtube_dl.return_value.__enter__.return_value.extract_info.return_value = {
                "formats": [
                    {
                        "format_id": "audio",
                        "url": "https://cdn.example/audio",
                        "vcodec": "none",
                        "height": None,
                        "tbr": 128,
                    },
                    {
                        "format_id": "360p",
                        "url": "https://cdn.example/video-360",
                        "vcodec": "avc1",
                        "height": 360,
                        "tbr": 500,
                    },
                    {
                        "format_id": "720p-low",
                        "url": "https://cdn.example/video-720-low",
                        "vcodec": "avc1",
                        "height": 720,
                        "tbr": 1000,
                        "http_headers": {
                            "User-Agent": "test-agent",
                            "Referer": "https://www.youtube.com/",
                        },
                    },
                    {
                        "format_id": "720p-high",
                        "url": "https://cdn.example/video-720-high",
                        "vcodec": "avc1",
                        "height": 720,
                        "tbr": 2500,
                        "protocol": "m3u8_native",
                    },
                    {
                        "format_id": "1080p",
                        "url": "https://cdn.example/video-1080",
                        "vcodec": "avc1",
                        "height": 1080,
                        "tbr": 4000,
                    },
                    {
                        "format_id": "storyboard",
                        "url": "https://cdn.example/storyboard",
                        "vcodec": "none",
                        "height": None,
                        "tbr": 0,
                        "protocol": "mhtml",
                    },
                ],
                "duration": 2400,
            }
            from services.frame_extraction import resolve_youtube_stream_url

            stream = await resolve_youtube_stream_url("video123")

        self.assertEqual(stream.url, "https://cdn.example/video-720-low")
        self.assertEqual(
            stream.http_headers,
            {
                "User-Agent": "test-agent",
                "Referer": "https://www.youtube.com/",
            },
        )
        self.assertEqual(stream.duration, 2400)
        youtube_dl.assert_called_once()
        options = youtube_dl.call_args.args[0]
        self.assertNotIn("format", options)
        youtube_dl.return_value.__enter__.return_value.extract_info.assert_called_once_with(
            "https://www.youtube.com/watch?v=video123",
            download=False,
            process=True,
        )

    async def test_timestamp_extraction_uses_bundled_ffmpeg_and_stream_headers(self):
        def run_process(command, **kwargs):
            self.assertEqual(kwargs["stdout"], subprocess.PIPE)
            self.assertEqual(kwargs["stderr"], subprocess.PIPE)
            self.assertEqual(kwargs["timeout"], 15.0)
            self.assertFalse(kwargs["check"])
            Path(command[-1]).write_bytes(b"jpeg-frame")
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=b"",
                stderr=b"",
            )

        frame_path = None
        with (
            patch.object(
                frame_extraction,
                "get_ffmpeg_executable",
                return_value="C:\\tools\\ffmpeg.exe",
            ),
            patch(
                "services.frame_extraction.subprocess.run",
                side_effect=run_process,
            ) as create_ffmpeg,
        ):
            frame_path = await frame_extraction.extract_frame_at_timestamp(
                "https://cdn.example/video",
                "6:39",
                is_remote=True,
                http_headers={"User-Agent": "test-agent"},
            )

        try:
            command = create_ffmpeg.call_args.args[0]
            self.assertEqual(command[0], "C:\\tools\\ffmpeg.exe")
            self.assertEqual(command[command.index("-ss") + 1], "397.0")
            self.assertIn(
                "User-Agent: test-agent\r\n",
                command[command.index("-headers") + 1],
            )
            self.assertEqual(command[command.index("-i") + 1], "https://cdn.example/video")
            self.assertEqual(command[command.index("-ss", command.index("-i")) + 1], "2.0")
        finally:
            if frame_path:
                import shutil

                shutil.rmtree(Path(frame_path).parent, ignore_errors=True)

    async def test_youtube_focus_resolves_stream_then_analyzes_exact_timestamp(self):
        with (
            patch.object(
                frame_extraction,
                "resolve_youtube_stream_url",
                new_callable=AsyncMock,
                return_value=frame_extraction.ResolvedVideoStream(
                    url="https://cdn.example/video.mp4",
                    http_headers={"User-Agent": "test-agent"},
                    duration=2400,
                ),
            ) as resolve_stream,
            patch(
                "services.frame_extraction.extract_frame_at_timestamp",
                new_callable=AsyncMock,
                return_value="C:\\temp\\frame_ext_test\\frame.jpg",
            ) as extract_frame,
            patch(
                "services.vision_client.explain_frame_with_vision",
                new_callable=AsyncMock,
                return_value={
                    "explanation": "A chart shows a rising trend.",
                    "provider": "gemini",
                },
            ),
        ):
            enriched_prompt = await router.inject_frame_explanations(
                "https://www.youtube.com/watch?v=video123",
                "Explain the chart at 6:30.",
                is_youtube=True,
                user_id="test-user",
            )

        resolve_stream.assert_awaited_once_with(
            "https://www.youtube.com/watch?v=video123"
        )
        extract_frame.assert_awaited_once_with(
            "https://cdn.example/video.mp4",
            "6:30",
            is_remote=True,
            http_headers={"User-Agent": "test-agent"},
        )
        self.assertIn("A chart shows a rising trend.", enriched_prompt)

    async def test_visual_failure_is_reported_instead_of_returning_prompt_only(self):
        with patch.object(
            frame_extraction,
            "resolve_youtube_stream_url",
            new_callable=AsyncMock,
            side_effect=RuntimeError("video unavailable"),
        ):
            with self.assertRaises(HTTPException) as raised:
                await router.inject_frame_explanations(
                    "https://www.youtube.com/watch?v=video123",
                    "Explain the diagram at 6:30.",
                    is_youtube=True,
                    user_id="test-user",
                )

        self.assertEqual(raised.exception.status_code, 502)
        self.assertIn("No visual summary was generated", raised.exception.detail)

    async def test_empty_representative_analysis_is_not_reported_as_success(self):
        with patch.object(
            router.engine,
            "generate_visual_analysis",
            new_callable=AsyncMock,
            return_value="Visual analysis unavailable: no frames could be extracted.",
        ):
            with self.assertRaises(HTTPException) as raised:
                await router.inject_frame_explanations(
                    "local-video.mp4",
                    "Explain the diagram.",
                    is_youtube=False,
                    user_id="test-user",
                )

        self.assertEqual(raised.exception.status_code, 502)
        self.assertIn("No visual summary was generated", raised.exception.detail)

    async def test_nonvisual_focus_does_not_trigger_vision_analysis(self):
        with patch.object(
            router.engine,
            "generate_visual_analysis",
            new_callable=AsyncMock,
        ) as analyze_frames:
            prompt = await router.inject_frame_explanations(
                "local-video.mp4",
                "Focus on the historical context and key dates.",
                is_youtube=False,
                user_id="test-user",
            )

        analyze_frames.assert_not_awaited()
        self.assertEqual(
            prompt,
            "Focus on the historical context and key dates.",
        )

    async def test_local_video_frame_extraction_samples_the_uploaded_file(self):
        capture = Mock()
        capture.get.return_value = 12
        capture.read.return_value = (True, "frame")

        with (
            patch.object(router.engine.cv2, "VideoCapture", return_value=capture),
            patch.object(router.engine.cv2, "resize", return_value="resized"),
            patch.object(
                router.engine.cv2,
                "imencode",
                return_value=(True, b"jpeg-data"),
            ),
            patch(
                "services.frame_extraction.resolve_youtube_stream_url",
                new_callable=AsyncMock,
            ) as resolve_stream,
        ):
            frames = await router.engine.extract_frames(
                "local-video.mp4",
                max_frames=2,
                is_youtube=False,
            )

        self.assertEqual(frames, [base64.b64encode(b"jpeg-data").decode("utf-8")] * 2)
        self.assertEqual(capture.set.call_count, 2)
        capture.release.assert_called_once()
        resolve_stream.assert_not_awaited()

    async def test_youtube_representative_frames_use_resolved_headers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            async def extract_frame(url, timestamp, is_remote, http_headers):
                self.assertEqual(url, "https://cdn.example/video")
                self.assertTrue(is_remote)
                self.assertEqual(http_headers, {"User-Agent": "test-agent"})
                frame_dir = temp_path / timestamp.replace(".", "_")
                frame_dir.mkdir()
                frame_path = frame_dir / "frame.jpg"
                frame_path.write_bytes(f"frame-{timestamp}".encode())
                return str(frame_path)

            with (
                patch(
                    "services.frame_extraction.resolve_youtube_stream_url",
                    new_callable=AsyncMock,
                    return_value=frame_extraction.ResolvedVideoStream(
                        url="https://cdn.example/video",
                        http_headers={"User-Agent": "test-agent"},
                        duration=400,
                    ),
                ) as resolve_stream,
                patch(
                    "services.frame_extraction.extract_frame_at_timestamp",
                    new_callable=AsyncMock,
                    side_effect=extract_frame,
                ) as extract_at_timestamp,
            ):
                frames = await router.engine.extract_frames(
                    "https://www.youtube.com/watch?v=video123",
                    max_frames=2,
                    is_youtube=True,
                )

        self.assertEqual(len(frames), 2)
        resolve_stream.assert_awaited_once_with(
            "https://www.youtube.com/watch?v=video123"
        )
        self.assertEqual(extract_at_timestamp.await_count, 2)
        self.assertEqual(
            [call.args[1] for call in extract_at_timestamp.await_args_list],
            ["133.333", "266.667"],
        )
        self.assertTrue(
            all(
                call.kwargs["http_headers"] == {"User-Agent": "test-agent"}
                for call in extract_at_timestamp.await_args_list
            )
        )

    async def test_multiframe_visual_analysis_prefers_gemini(self):
        image = base64.b64encode(b"jpeg-data").decode("utf-8")
        generate_content = Mock(
            return_value=Mock(text="The diagram shows connected processing stages.")
        )
        gemini_client = Mock()
        gemini_client.models.generate_content = generate_content
        groq_create = Mock()
        groq_client = Mock()
        groq_client.chat.completions.create = groq_create

        with (
            patch.object(
                router.engine,
                "extract_frames",
                new_callable=AsyncMock,
                return_value=[image],
            ) as extract_frames,
            patch.object(router.engine, "groq_client", groq_client),
            patch.object(router.engine, "gemini_client", gemini_client),
            patch(
                "services.profile.get_master_prompt",
                return_value="Research learner",
            ),
        ):
            analysis = await router.engine.generate_visual_analysis(
                transcript="",
                video_url="local-video.mp4",
                user_id="test-user",
                dynamic_extra="Explain the diagram.",
                is_youtube=False,
                max_frames=8,
            )

        self.assertIn("connected processing stages", analysis)
        extract_frames.assert_awaited_once_with(
            "local-video.mp4",
            max_frames=8,
            is_youtube=False,
        )
        vision_prompt = generate_content.call_args.kwargs["contents"][0]
        self.assertEqual(
            generate_content.call_args.kwargs["model"],
            "gemini-3.5-flash-lite",
        )
        self.assertIn("Explain the diagram.", vision_prompt)
        self.assertIn("representative frames", vision_prompt)
        groq_create.assert_not_called()

    async def test_exact_frame_explanation_prefers_gemini(self):
        from services import vision_client

        gemini_client = Mock()
        gemini_client.models.generate_content.return_value = Mock(
            text="A diagram connects three labeled stages."
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "frame.jpg"
            image_path.write_bytes(b"jpeg-data")
            with (
                patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key"}),
                patch.object(
                    vision_client.genai,
                    "Client",
                    return_value=gemini_client,
                ) as create_client,
                patch.object(
                    vision_client,
                    "get_master_prompt",
                    return_value="Research learner",
                ),
                patch.object(vision_client, "AsyncGroq") as groq_client,
            ):
                result = await vision_client.explain_frame_with_vision(
                    str(image_path),
                    "test-user",
                    "Summarize the diagram.",
                )

        self.assertEqual(result["provider"], "gemini")
        self.assertIn("three labeled stages", result["explanation"])
        create_client.assert_called_once_with(api_key="test-key")
        gemini_client.models.generate_content.assert_called_once()
        self.assertEqual(
            gemini_client.models.generate_content.call_args.kwargs["model"],
            "gemini-3.5-flash-lite",
        )
        groq_client.assert_not_called()

    async def test_gemini_transient_failure_is_retried_before_fallback(self):
        from services import vision_client

        gemini_client = Mock()
        gemini_client.models.generate_content.side_effect = [
            RuntimeError("503 UNAVAILABLE"),
            Mock(text="The frame contains an A-star search graph."),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "frame.jpg"
            image_path.write_bytes(b"jpeg-data")
            with (
                patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key"}),
                patch.object(
                    vision_client.genai,
                    "Client",
                    return_value=gemini_client,
                ),
                patch.object(
                    vision_client,
                    "get_master_prompt",
                    return_value="Research learner",
                ),
                patch(
                    "services.vision_client.asyncio.sleep",
                    new_callable=AsyncMock,
                ) as retry_delay,
                patch.object(vision_client, "AsyncGroq") as groq_client,
            ):
                result = await vision_client.explain_frame_with_vision(
                    str(image_path),
                    "test-user",
                    "Explain the diagram.",
                )

        self.assertEqual(result["provider"], "gemini")
        self.assertIn("A-star search graph", result["explanation"])
        self.assertEqual(
            gemini_client.models.generate_content.call_count,
            2,
        )
        retry_delay.assert_awaited_once_with(1)
        groq_client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
