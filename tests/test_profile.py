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


class TestProfileEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app_module.app)

    def test_create_profile_requires_device_header(self):
        response = self.client.post(
            "/profile", json={"university": "Test U", "major": "CS", "year": "Junior"}
        )
        self.assertEqual(response.status_code, 400)

    def test_create_profile_is_idempotent_per_device(self):
        existing = {"id": 1, "university": "Test U", "major": "CS", "year": "Junior"}
        with patch.object(app_module, "get_profile_by_device", return_value=existing):
            response = self.client.post(
                "/profile",
                json={"university": "Different U", "major": "CS", "year": "Junior"},
                headers={"X-Device-Id": "device-1"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["profile"], existing)

    def test_create_profile_inserts_when_new(self):
        fake_response = SimpleNamespace(
            data=[{"id": 2, "university": "Test U", "major": "CS", "year": "Junior"}]
        )
        with patch.object(app_module, "get_profile_by_device", return_value=None), \
             patch.object(app_module, "execute_db", return_value=fake_response):
            response = self.client.post(
                "/profile",
                json={"university": "Test U", "major": "CS", "year": "Junior"},
                headers={"X-Device-Id": "device-2"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["profile"]["id"], 2)

    def test_read_profile_missing_returns_404(self):
        with patch.object(app_module, "get_profile_by_device", return_value=None):
            response = self.client.get("/profile", headers={"X-Device-Id": "unknown"})

        self.assertEqual(response.status_code, 404)

    def test_update_profile(self):
        existing = {"id": 3, "university": "Old U", "major": "CS", "year": "Junior"}
        fake_response = SimpleNamespace(
            data=[{"id": 3, "university": "New U", "major": "CS", "year": "Junior"}]
        )
        with patch.object(app_module, "get_profile_by_device", return_value=existing), \
             patch.object(app_module, "execute_db", return_value=fake_response):
            response = self.client.patch(
                "/profile", json={"university": "New U"}, headers={"X-Device-Id": "device-3"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["profile"]["university"], "New U")

    def test_create_session_requires_profile(self):
        with patch.object(app_module, "get_profile_by_device", return_value=None):
            response = self.client.post(
                "/session", json={"goals": "internships"}, headers={"X-Device-Id": "unknown"}
            )

        self.assertEqual(response.status_code, 404)

    def test_north_star_aggregates_across_profile_chats(self):
        profile = {"id": 9, "university": "Test U", "major": "CS", "year": "Junior"}
        chats = [{"id": 101, "goals": "internships", "created_at": "2026-01-01T00:00:00Z"}]

        with patch.object(app_module, "get_profile_by_device", return_value=profile), \
             patch.object(app_module, "get_profile_chats", return_value=chats), \
             patch.object(app_module, "get_profile_opportunities", return_value=[]), \
             patch.object(app_module, "get_profile_history", return_value=[]), \
             patch.object(app_module, "get_profile_plans", return_value=[]), \
             patch.object(app_module, "get_latest_north_star_snapshot", return_value=None), \
             patch.object(app_module, "save_north_star_snapshot", return_value=None) as save_mock, \
             patch.object(
                 app_module,
                 "call_claude",
                 return_value='{"current_direction": {"direction": "Technology"}, "priorities": [], "risks": [], "upcoming_opportunities": []}',
             ):
            response = self.client.post("/north-star", headers={"X-Device-Id": "device-9"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["current_direction"]["direction"], "Technology")
        self.assertEqual(body["whats_new"], ["Initial North Star generated."])
        self.assertIsNotNone(body["generated_at"])
        save_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
