import unittest
from unittest.mock import Mock, patch

from services import memory


class MemoryPersistenceTests(unittest.TestCase):
    def test_save_uses_the_authenticated_user_jwt_for_row_level_security(self):
        supabase = Mock()

        with patch.object(memory, "supabase", supabase):
            memory.save_to_memory(
                video_id="video-123",
                title="Video title",
                content="Summary content",
                user_id="user-123",
                profile_version_used=4,
                jwt="user-access-token",
            )

        supabase.table.assert_called_once_with(
            "knowledge",
            jwt="user-access-token",
        )
        supabase.table.return_value.upsert.assert_called_once_with(
            {
                "video_id": "video-123",
                "title": "Video title",
                "content": "Summary content",
                "user_id": "user-123",
                "profile_version_used": 4,
            },
            on_conflict="video_id",
        )
        supabase.table.return_value.upsert.return_value.execute.assert_called_once()


if __name__ == "__main__":
    unittest.main()
