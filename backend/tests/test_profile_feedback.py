import unittest
from unittest.mock import patch

from services.profile import get_master_prompt, update_preference


class ProfileFeedbackTests(unittest.TestCase):
    def test_custom_feedback_sets_detailed_concise_length_and_bullet_format(self):
        profile = {
            "preferred_length": "shorter",
            "preferred_format": "paragraphs",
            "support_level": 2,
            "profile_version": 22,
            "feedback_count": 21,
        }

        with (
            patch("services.profile.get_profile", return_value=profile),
            patch("services.profile.save_profile") as save_profile,
        ):
            update_preference(
                "test-user",
                "intermediate",
                "other",
                custom_feedback=(
                    "Keep advanced detail, but be brief and use bullet points "
                    "so it is easy to scan."
                ),
            )

        self.assertEqual(profile["preferred_length"], "detailed and concise")
        self.assertEqual(profile["preferred_format"], "bullets")
        self.assertEqual(profile["profile_version"], 23)
        self.assertEqual(profile["feedback_count"], 22)
        save_profile.assert_called_once()

    def test_feedback_without_length_or_format_instruction_preserves_values(self):
        profile = {
            "preferred_length": "shorter",
            "preferred_format": "table",
            "support_level": 2,
            "profile_version": 22,
            "feedback_count": 21,
        }

        with (
            patch("services.profile.get_profile", return_value=profile),
            patch("services.profile.save_profile"),
        ):
            update_preference(
                "test-user",
                "expert",
                "other",
                custom_feedback="Only cover what the video says.",
            )

        self.assertEqual(profile["preferred_length"], "shorter")
        self.assertEqual(profile["preferred_format"], "table")

    def test_explicit_request_to_avoid_bullets_selects_paragraphs(self):
        profile = {
            "preferred_length": "default",
            "preferred_format": "bullets",
            "support_level": 0,
            "profile_version": 1,
            "feedback_count": 0,
        }

        with (
            patch("services.profile.get_profile", return_value=profile),
            patch("services.profile.save_profile"),
        ):
            update_preference(
                "test-user",
                "intermediate",
                "other",
                custom_feedback="Avoid bullet points and use paragraphs.",
            )

        self.assertEqual(profile["preferred_format"], "paragraphs")

    def test_persona_preferring_paragraph_flow_over_heavy_bullets_selects_paragraphs(self):
        profile = {
            "preferred_length": "default",
            "preferred_format": "bullets",
            "support_level": 0,
            "profile_version": 1,
            "feedback_count": 0,
        }

        with (
            patch("services.profile.get_profile", return_value=profile),
            patch("services.profile.save_profile"),
        ):
            update_preference(
                "test-user",
                "intermediate",
                "other",
                custom_feedback=(
                    "Always give a concise brief summary first, then a thorough "
                    "detailed explanation. Present answers in short paragraphs, "
                    "favoring paragraph flow over heavy bullet lists."
                ),
            )

        self.assertEqual(profile["preferred_format"], "paragraphs")
        self.assertEqual(profile["preferred_length"], "detailed and concise")

    def test_master_prompt_preserves_detailed_concise_preference(self):
        profile = {
            "persona_blueprint": "Advanced learner",
            "instructions": [],
            "support_level": 2,
            "preferred_length": "detailed and concise",
            "preferred_format": "bullets",
        }
        with patch("services.profile.get_profile", return_value=profile):
            prompt = get_master_prompt("test-user")

        self.assertIn("- Preferred Length: detailed and concise", prompt)
        self.assertIn("- Preferred Format: bullets", prompt)
        self.assertIn("preserve all important reasoning", prompt)


if __name__ == "__main__":
    unittest.main()
