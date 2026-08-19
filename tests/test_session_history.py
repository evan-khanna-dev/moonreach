import json
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

    def test_list_sessions_scoped_to_device_profile(self):
        fake_profile = {"id": 42, "university": "Test University", "major": "Computer Science", "year": "Junior"}
        fake_response = SimpleNamespace(
            data=[
                {"id": 1, "goals": "internships", "created_at": "2026-01-01T00:00:00Z"},
                {"id": 2, "goals": "full-time roles", "created_at": "2026-01-02T00:00:00Z"},
            ]
        )

        with patch.object(app_module, "get_profile_by_device", return_value=fake_profile), \
             patch.object(app_module, "execute_db", return_value=fake_response):
            response = self.client.get("/sessions", headers={"X-Device-Id": "device-abc"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["sessions"]), 2)
        self.assertEqual(body["sessions"][0]["id"], 1)
        self.assertEqual(body["sessions"][0]["goals"], "internships")

    def test_list_sessions_without_profile_returns_empty(self):
        with patch.object(app_module, "get_profile_by_device", return_value=None):
            response = self.client.get("/sessions", headers={"X-Device-Id": "unknown-device"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sessions"], [])

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

    def test_parse_json_response_unwraps_doubly_nested_assistant_payloads(self):
        # Claude wrapped its own schema inside assistant_response twice - the
        # single-level unwrap used to leave the inner JSON blob as literal text.
        inner_inner = '{"assistant_response": "Hello from Claude", "suggested_replies": ["Next step"], "career_radar_updates": []}'
        inner = json.dumps({"assistant_response": inner_inner, "suggested_replies": [], "career_radar_updates": []})
        raw = json.dumps({"assistant_response": inner, "suggested_replies": [], "career_radar_updates": []})

        parsed = app_module.parse_json_response(raw)

        self.assertEqual(parsed["assistant_response"], "Hello from Claude")
        self.assertEqual(parsed["suggested_replies"], ["Next step"])

    def test_salvage_assistant_text_extracts_field_from_truncated_json(self):
        # Simulates output cut off mid-generation (e.g. by max_tokens) - the
        # assistant_response field is complete but the rest of the JSON isn't.
        raw = '{"assistant_response": "Here are three internships worth looking at", "suggested_repl'
        result = app_module.salvage_assistant_text(raw)
        self.assertEqual(result, "Here are three internships worth looking at")

    def test_salvage_assistant_text_passes_through_plain_prose(self):
        raw = "Sure! Here's some career advice without any JSON wrapper."
        self.assertEqual(app_module.salvage_assistant_text(raw), raw)

    def test_salvage_assistant_text_never_returns_raw_json_blob(self):
        raw = '{"totally": "unparseable", "and": "no assistant_response key at all"'
        result = app_module.salvage_assistant_text(raw)
        self.assertNotIn("{", result)

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
