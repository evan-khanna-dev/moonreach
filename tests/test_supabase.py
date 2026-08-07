import os
import unittest
import uuid

from dotenv import load_dotenv
from supabase import create_client


load_dotenv()


class TestSupabaseConnection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.supabase_url = os.getenv("SUPABASE_URL")
        cls.supabase_key = os.getenv("SUPABASE_KEY")
        cls.supabase_service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

        if not cls.supabase_url:
            raise unittest.SkipTest("SUPABASE_URL is not set in .env")

        if cls.supabase_service_role_key:
            cls.client = create_client(cls.supabase_url, cls.supabase_service_role_key)
        elif cls.supabase_key:
            cls.client = create_client(cls.supabase_url, cls.supabase_key)
        else:
            raise unittest.SkipTest("Neither SUPABASE_SERVICE_ROLE_KEY nor SUPABASE_KEY is set in .env")

    def test_env_keys_present(self):
        self.assertIsNotNone(self.supabase_url, "SUPABASE_URL must be set")
        self.assertTrue(
            self.supabase_service_role_key or self.supabase_key,
            "Either SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY must be set",
        )

    def test_can_select_sessions(self):
        response = self.client.table("sessions").select("id").limit(1).execute()
        self.assertTrue(hasattr(response, "data"), "Supabase response must include data")
        self.assertIsNotNone(response.data, "Session select returned no data")

    def test_can_insert_and_clean_session_when_service_role_enabled(self):
        if not self.supabase_service_role_key:
            self.skipTest("SUPABASE_SERVICE_ROLE_KEY not set; skipping insert test")

        unique_tag = f"test-session-{uuid.uuid4()}"
        insert_payload = {
            "university": "Test University",
            "major": "Test Major",
            "year": "Test Year",
            "goals": unique_tag,
        }
        insert_response = self.client.table("sessions").insert(insert_payload).select("id").execute()
        self.assertTrue(hasattr(insert_response, "data"), "Insert response must include data")
        self.assertTrue(insert_response.data, "Insert did not return created row data")

        session_id = insert_response.data[0].get("id")
        self.assertIsNotNone(session_id, "Inserted row did not return an id")

        delete_response = self.client.table("sessions").delete().eq("id", session_id).execute()
        self.assertTrue(hasattr(delete_response, "data"), "Delete response must include data")


if __name__ == "__main__":
    unittest.main()
