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


FAKE_GROUNDING_DOC = "PRINCIPLE ONE: quantify impact. PRINCIPLE TWO: lead bullets with strong verbs."
FAKE_RESUME_TEXT = "EXPERIENCE\nWorked on stuff at a company.\nEDUCATION\nState University, BS Computer Science"


class TestDocumentReviewEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app_module.app)
        self.fake_session = {"id": 7, "university": "Test U", "major": "CS", "year": "Junior", "goals": "internships"}

    def test_non_resume_document_type_rejected(self):
        with patch.object(app_module, "get_session", return_value=self.fake_session):
            response = self.client.post(
                "/document-reviews",
                json={
                    "session_id": 7,
                    "document_type": "cv",
                    "document_content": FAKE_RESUME_TEXT,
                    "intent": "general_feedback",
                },
            )
        self.assertEqual(response.status_code, 400)

    def test_follow_up_requires_message(self):
        with patch.object(app_module, "get_session", return_value=self.fake_session), \
             patch.object(app_module, "load_resume_grounding_document", return_value=FAKE_GROUNDING_DOC):
            response = self.client.post(
                "/document-reviews",
                json={
                    "session_id": 7,
                    "document_type": "resume",
                    "document_content": FAKE_RESUME_TEXT,
                    "intent": "resume_follow_up",
                },
            )
        self.assertEqual(response.status_code, 400)

    def test_missing_grounding_document_raises_clear_error(self):
        # resume-grounding-document.md genuinely doesn't exist in the repo
        # yet - this exercises the real (unpatched) loader against that.
        with patch.object(app_module, "get_session", return_value=self.fake_session):
            response = self.client.post(
                "/document-reviews",
                json={
                    "session_id": 7,
                    "document_type": "resume",
                    "document_content": FAKE_RESUME_TEXT,
                    "intent": "general_feedback",
                },
            )
        self.assertEqual(response.status_code, 500)
        self.assertIn("resume-grounding-document.md", response.json()["detail"])

    def test_general_feedback_prompt_embeds_grounding_document_and_resume_verbatim(self):
        prompt = app_module.compose_resume_review_prompt(
            FAKE_GROUNDING_DOC, FAKE_RESUME_TEXT, "general_feedback", None, None
        )
        self.assertIn(FAKE_GROUNDING_DOC, prompt)
        self.assertIn(FAKE_RESUME_TEXT, prompt)
        self.assertIn("never author a resume from scratch", prompt)
        self.assertIn("strengths", prompt)
        self.assertIn("overall_summary", prompt)

    def test_tailor_to_role_prompt_includes_role_alignment_instruction_and_search(self):
        role_context = {"title": "Data Analyst Intern", "company": "Acme", "industry": "Fintech", "job_posting": ""}
        prompt = app_module.compose_resume_review_prompt(
            FAKE_GROUNDING_DOC, FAKE_RESUME_TEXT, "tailor_to_role", role_context, "Search result summary here"
        )
        self.assertIn("How this aligns with Data Analyst Intern", prompt)
        self.assertIn("Search result summary here", prompt)

    def test_general_feedback_prompt_omits_role_alignment_instruction(self):
        prompt = app_module.compose_resume_review_prompt(
            FAKE_GROUNDING_DOC, FAKE_RESUME_TEXT, "general_feedback", None, None
        )
        self.assertNotIn("How this aligns with", prompt)

    def test_build_role_search_query_uses_role_context(self):
        query = app_module.build_role_search_query(
            {"title": "Data Analyst Intern", "company": "Acme", "industry": "Fintech"}
        )
        self.assertIn("Data Analyst Intern", query)
        self.assertIn("Acme", query)
        self.assertIn("Fintech", query)

    def test_tailor_to_role_endpoint_triggers_web_search_with_role_query(self):
        role_context = {"title": "Data Analyst Intern", "company": "Acme", "industry": "Fintech", "job_posting": ""}
        fake_feedback_json = (
            '{"strengths": ["Clear formatting"], "areas_to_improve": ["Quantify impact"], '
            '"line_suggestions": ["Rewrite bullet 1"], "overall_summary": "Solid start.", '
            '"role_alignment": "Aligns well with the analyst role."}'
        )
        with patch.object(app_module, "get_session", return_value=self.fake_session), \
             patch.object(app_module, "load_resume_grounding_document", return_value=FAKE_GROUNDING_DOC), \
             patch.object(app_module, "run_web_search", return_value=[{"title": "T", "url": "https://x.com", "snippet": "s"}]) as search_mock, \
             patch.object(app_module, "call_claude", return_value=fake_feedback_json), \
             patch.object(app_module, "execute_db", return_value=SimpleNamespace(data=[{"id": 1, "ai_feedback": {}}])):
            response = self.client.post(
                "/document-reviews",
                json={
                    "session_id": 7,
                    "document_type": "resume",
                    "document_content": FAKE_RESUME_TEXT,
                    "intent": "tailor_to_role",
                    "role_context": role_context,
                },
            )

        self.assertEqual(response.status_code, 200)
        search_mock.assert_called_once()
        called_query = search_mock.call_args[0][0]
        self.assertIn("Data Analyst Intern", called_query)
        self.assertIn("Acme", called_query)

    def test_general_feedback_does_not_trigger_web_search(self):
        fake_feedback_json = (
            '{"strengths": [], "areas_to_improve": [], "line_suggestions": [], "overall_summary": "ok"}'
        )
        with patch.object(app_module, "get_session", return_value=self.fake_session), \
             patch.object(app_module, "load_resume_grounding_document", return_value=FAKE_GROUNDING_DOC), \
             patch.object(app_module, "run_web_search") as search_mock, \
             patch.object(app_module, "call_claude", return_value=fake_feedback_json), \
             patch.object(app_module, "execute_db", return_value=SimpleNamespace(data=[{"id": 1, "ai_feedback": {}}])):
            response = self.client.post(
                "/document-reviews",
                json={
                    "session_id": 7,
                    "document_type": "resume",
                    "document_content": FAKE_RESUME_TEXT,
                    "intent": "general_feedback",
                },
            )

        self.assertEqual(response.status_code, 200)
        search_mock.assert_not_called()

    def test_normalize_resume_review_clamps_and_defaults(self):
        result = app_module.normalize_resume_review(None, "general_feedback")
        self.assertEqual(result["strengths"], [])
        self.assertEqual(result["overall_summary"], "")

        parsed = {
            "strengths": ["a", "", "b"],
            "areas_to_improve": ["c"],
            "line_suggestions": ["d"],
            "overall_summary": "  summary  ",
            "role_alignment": "should be dropped for non-tailor intent",
        }
        result = app_module.normalize_resume_review(parsed, "general_feedback")
        self.assertEqual(result["strengths"], ["a", "b"])
        self.assertEqual(result["overall_summary"], "summary")
        self.assertEqual(result["role_alignment"], "")

        result_tailored = app_module.normalize_resume_review(parsed, "tailor_to_role")
        self.assertEqual(result_tailored["role_alignment"], "should be dropped for non-tailor intent")


if __name__ == "__main__":
    unittest.main()
