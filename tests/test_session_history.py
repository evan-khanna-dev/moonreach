import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "dummy-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "dummy-service-role")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy-anthropic-key")

import app as app_module
from fastapi.testclient import TestClient


class TestSessionHistoryEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app_module.app)

    def test_list_sessions_returns_all_sessions(self):
        fake_response = SimpleNamespace(
            data=[
                {"id": 1, "university": "Test University", "major": "Computer Science", "year": "Junior", "goals": "internships"},
                {"id": 2, "university": "Another University", "major": "Data Science", "year": "Senior", "goals": "full-time roles"},
            ]
        )

        with patch.object(app_module, "execute_db", return_value=fake_response):
            response = self.client.get("/sessions")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["sessions"]), 2)
        self.assertEqual(body["sessions"][0]["id"], 1)
        self.assertEqual(body["sessions"][0]["university"], "Test University")

    def test_history_endpoint_returns_session_context_messages_and_plan(self):
        with patch.object(app_module, "get_session", return_value={"id": 7, "university": "Test University", "major": "Design", "year": "Sophomore", "goals": "portfolio"}), \
             patch.object(app_module, "get_message_history", return_value=[{"role": "user", "content": "Hello"}]), \
             patch.object(app_module, "get_latest_plan", return_value=["Reach out to alumni"]):
            response = self.client.get("/session/7/history")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["session"]["id"], 7)
        self.assertEqual(body["messages"][0]["content"], "Hello")
        self.assertEqual(body["plan"][0], "Reach out to alumni")

    def test_parse_json_response_unwraps_nested_assistant_payloads(self):
        raw = '{"assistant_response": "`json {\\"assistant_response\\": \\"Hello from Claude\\", \\"suggested_replies\\": [\\"Next step\\"], \\"career_radar_updates\\": []}"}'
        parsed = app_module.parse_json_response(raw)

        self.assertEqual(parsed["assistant_response"], "Hello from Claude")
        self.assertEqual(parsed["suggested_replies"], ["Next step"])
        self.assertEqual(parsed["career_radar_updates"], [])

    def test_chat_uses_session_context(self):
        def fake_get_session(session_id):
            return {"id": session_id, "university": "Test", "major": "CS", "year": "Junior", "goals": "internships"}

        with patch.object(app_module, "get_session", side_effect=fake_get_session), \
             patch.object(app_module, "get_message_history", return_value=[]), \
             patch.object(app_module, "call_claude", return_value='{"assistant_response": "Hello", "suggested_replies": ["Next"]}'), \
             patch.object(app_module, "parse_json_response", return_value={"assistant_response": "Hello", "suggested_replies": ["Next"]}), \
             patch.object(app_module, "execute_db", return_value=SimpleNamespace(data=[{"id": 1}])):
            response = self.client.post(
                "/chat",
                json={"session_id": 7, "message": "Hello"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["assistant_response"], "Hello")


if __name__ == "__main__":
    unittest.main()
