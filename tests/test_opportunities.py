import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "dummy-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "dummy-service-role")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy-anthropic-key")

import app as app_module
from fastapi.testclient import TestClient


class TestOpportunityEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app_module.app)

    def test_create_and_list_opportunities(self):
        fake_response = SimpleNamespace(data=[{"id": 10, "session_id": 7, "title": "Career Fair", "category": "Event", "description": "Fall fair", "reason_relevant": "Great for networking", "priority_score": 8, "status": "suggested", "source_url": "https://example.com"}])

        with patch.object(app_module, "execute_db", return_value=fake_response):
            response = self.client.post(
                "/opportunities",
                json={"session_id": 7, "title": "Career Fair", "category": "Event", "description": "Fall fair", "reason_relevant": "Great for networking", "priority_score": 8, "status": "suggested", "source_url": "https://example.com"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["opportunity"]["title"], "Career Fair")

    def test_chat_applies_career_radar_updates(self):
        fake_session = {"id": 7, "university": "Test University", "major": "CS", "year": "Junior", "goals": "internships"}

        with patch.object(app_module, "get_session", return_value=fake_session), \
             patch.object(app_module, "get_message_history", return_value=[]), \
             patch.object(app_module, "call_claude", return_value='{"assistant_response": "I found a relevant event.", "career_radar_updates": [{"action": "add", "title": "Fall Career Fair", "category": "Event", "description": "A campus event", "reason_relevant": "Useful for networking", "priority_score": 8, "status": "suggested"}]}'), \
             patch.object(app_module, "parse_json_response", return_value={"assistant_response": "I found a relevant event.", "career_radar_updates": [{"action": "add", "title": "Fall Career Fair", "category": "Event", "description": "A campus event", "reason_relevant": "Useful for networking", "priority_score": 8, "status": "suggested"}]}) as parse_mock, \
             patch.object(app_module, "execute_db", side_effect=[SimpleNamespace(data=[{"id": 1}]), SimpleNamespace(data=[{"id": 2}]), SimpleNamespace(data=[{"id": 3}]), SimpleNamespace(data=[{"id": 4}])]):
            response = self.client.post(
                "/chat",
                json={"session_id": 7, "message": "Any events coming up?"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["assistant_response"], "I found a relevant event.")
        self.assertEqual(parse_mock.call_count, 1)


if __name__ == "__main__":
    unittest.main()
