import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services import engine


class FakeCompletions:
    def __init__(self):
        self.calls = []

    def create(self, *, messages, model):
        prompt = messages[0]["content"]
        self.calls.append(prompt)

        if "SOURCE MATERIAL:" in prompt:
            source = prompt.split("SOURCE MATERIAL:\n", 1)[1]
            map_call_count = sum("SOURCE MATERIAL:" in call for call in self.calls)
            note_size = 4500 if map_call_count <= 3 else 900
            note = "Faithful source notes " + ("x" * note_size)
            if "VIDEO-END-MARKER" in source:
                note += "\nVIDEO-END-MARKER"
            content = note
        elif "SOURCE NOTES FROM THE COMPLETE VIDEO:" in prompt:
            content = "# Study notes\n\nOnly source-supported material."
        elif engine.SUMMARY_DETAIL_DELIMITER in prompt:
            content = (
                "Brief summary of the source-grounded topic.\n"
                f"{engine.SUMMARY_DETAIL_DELIMITER}\n"
                "A thorough explanation in source-grounded prose."
                "\n===CUSTOM_INSIGHTS===\n"
            )
        else:
            content = (
                "- First source-grounded point with enough detail.\n"
                "- Second source-grounded point with enough detail.\n"
                "- Third source-grounded point with enough detail.\n"
                "- Fourth source-grounded point with enough detail.\n"
                "- Fifth source-grounded point with enough detail.\n"
                "===CUSTOM_INSIGHTS===\n"
            )

        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


def make_fake_client():
    completions = FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return client, completions


class TranscriptSynthesisTests(unittest.IsolatedAsyncioTestCase):
    def test_split_preserves_entire_source_with_bounded_chunks(self):
        transcript = "\n".join(
            f"SECTION-{index:04d} " + ("lecture content. " * 500)
            for index in range(15)
        )

        chunks = engine._split_transcript(transcript)

        self.assertGreater(len(chunks), 1)
        self.assertEqual("".join(chunks), transcript)
        self.assertTrue(
            all(len(chunk) <= engine.SUMMARY_INPUT_CHAR_LIMIT for chunk in chunks)
        )

    async def test_summary_reduces_full_transcript_and_uses_selected_level(self):
        transcript = (
            "Lecture content. " * 1400
            + "\nVIDEO-END-MARKER"
        )
        fake_client, fake_completions = make_fake_client()

        with patch.object(engine, "groq_client", fake_client):
            result = await engine.generate_summary_with_prompt(
                transcript,
                "CORE PERSONA BLUEPRINT\nResearch learner",
                level="beginner",
            )

        final_prompt = fake_completions.calls[-1]
        self.assertEqual(len(result["summary"]), 5)
        self.assertIsNone(result["custom_insights"])
        self.assertIn("SELECTED LEVEL (beginner)", final_prompt)
        self.assertIn("VIDEO-END-MARKER", final_prompt)
        self.assertGreater(len(fake_completions.calls), 3)

    async def test_summary_respects_paragraph_format_and_detailed_concise_length(self):
        fake_client, fake_completions = make_fake_client()

        with patch.object(engine, "groq_client", fake_client):
            result = await engine.generate_summary_with_prompt(
                "The source explains a topic and gives one example.",
                "CORE PERSONA BLUEPRINT\nPrefer paragraph flow.",
                preferred_format="paragraphs",
                preferred_length="detailed and concise",
            )

        final_prompt = fake_completions.calls[-1]
        self.assertEqual(result["summary_format"], "paragraphs")
        self.assertEqual(len(result["summary"]), 2)
        self.assertIn("Brief summary", result["summary"][0])
        self.assertIn("thorough explanation", result["summary"][1])
        self.assertIn(engine.SUMMARY_DETAIL_DELIMITER, final_prompt)
        self.assertIn("Do not use bullets", final_prompt)
        self.assertIn("remove repetition and filler", final_prompt)

    async def test_summary_uses_visual_frame_analysis_as_source_evidence(self):
        fake_client, fake_completions = make_fake_client()
        master_prompt = (
            "CORE PERSONA BLUEPRINT\nResearch learner\n"
            "DYNAMIC USER INTENT\nExplain the diagram at 00:50.\n\n"
            "### AUTOMATIC VISUAL ANALYSIS ###\n"
            "Visual details at timestamp 00:50 (requested frame): "
            "A diagram shows three connected processing stages.\n\n"
            "## OPERATING PROTOCOLS:\nFollow the user's focus."
        )

        with patch.object(engine, "groq_client", fake_client):
            await engine.generate_summary_with_prompt(
                "The speaker introduces the process.",
                master_prompt=master_prompt,
            )

        final_prompt = fake_completions.calls[-1]
        self.assertIn("TRANSCRIPT AND VISUAL FRAME ANALYSIS:", final_prompt)
        self.assertIn(
            "A diagram shows three connected processing stages.",
            final_prompt,
        )
        self.assertNotIn("## OPERATING PROTOCOLS:", final_prompt.split("TRANSCRIPT AND VISUAL FRAME ANALYSIS:", 1)[1])

    async def test_study_notes_cover_long_transcript_and_apply_persona_and_level(self):
        transcript = (
            "Detailed lecture section. " * 1400
            + "\nVIDEO-END-MARKER"
        )
        fake_client, fake_completions = make_fake_client()

        with (
            patch.object(engine, "groq_client", fake_client),
            patch(
                "services.profile.get_master_prompt",
                return_value=(
                    "CORE PERSONA BLUEPRINT\nResearch learner\n"
                    "DYNAMIC USER INTENT\nFocus on mechanisms"
                ),
            ) as get_master_prompt,
        ):
            notes = await engine.generate_notes(
                transcript,
                level="expert",
                user_id="test-user",
                dynamic_extra="Focus on mechanisms",
            )

        final_prompt = fake_completions.calls[-1]
        self.assertIn("SOURCE NOTES FROM THE COMPLETE VIDEO:", final_prompt)
        self.assertIn("VIDEO-END-MARKER", final_prompt)
        self.assertIn("SELECTED LEARNING LEVEL (expert)", final_prompt)
        self.assertIn("CORE PERSONA BLUEPRINT", final_prompt)
        self.assertIn("Focus on mechanisms", final_prompt)
        self.assertEqual(notes, "# Study notes\n\nOnly source-supported material.")
        get_master_prompt.assert_called_once_with(
            "test-user",
            "Focus on mechanisms",
            jwt=None,
        )


if __name__ == "__main__":
    unittest.main()
