import io
import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "dummy-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "dummy-service-role")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy-anthropic-key")

import app as app_module
from fastapi.testclient import TestClient


class TestExtractResumeText(unittest.TestCase):
    """Unit tests against extract_resume_text() directly - the abstraction
    the rest of the app (and the /resume-upload endpoint) is built on."""

    def test_txt_extracted_natively_without_docling(self):
        with patch.object(app_module, "_get_docling_classes") as docling_mock:
            text = app_module.extract_resume_text("resume.txt", "text/plain", b"Jane Doe\nSoftware Engineer")
        self.assertEqual(text, "Jane Doe\nSoftware Engineer")
        docling_mock.assert_not_called()

    def test_txt_latin1_fallback(self):
        raw = "café résumé".encode("latin-1")
        text = app_module.extract_resume_text("resume.txt", None, raw)
        self.assertIn("caf", text)

    def test_unsupported_extension_rejected(self):
        with self.assertRaises(app_module.ResumeExtractionError):
            app_module.extract_resume_text("resume.exe", "application/octet-stream", b"whatever")

    def test_mismatched_mime_type_rejected(self):
        # .txt extension but a clearly different, non-generic content-type.
        with self.assertRaises(app_module.ResumeExtractionError):
            app_module.extract_resume_text("resume.txt", "application/pdf", b"hello")

    def test_generic_mime_type_is_tolerated(self):
        # Browsers commonly send application/octet-stream or omit it - must not block.
        text = app_module.extract_resume_text("resume.txt", "application/octet-stream", b"hello")
        self.assertEqual(text, "hello")

    def test_empty_file_rejected(self):
        with self.assertRaises(app_module.ResumeExtractionError):
            app_module.extract_resume_text("resume.txt", "text/plain", b"")

    def test_oversized_file_rejected(self):
        oversized = b"a" * (app_module.MAX_RESUME_UPLOAD_BYTES + 1)
        with self.assertRaises(app_module.ResumeExtractionError):
            app_module.extract_resume_text("resume.txt", "text/plain", oversized)

    def test_pdf_routes_through_docling(self):
        fake_converter = MagicMock()
        fake_result = MagicMock()
        fake_result.document.export_to_markdown.return_value = "# Jane Doe\n\n## Experience\n- Did things"
        fake_converter.convert.return_value = fake_result
        with patch.object(app_module, "_get_docling_classes", return_value=(fake_converter, MagicMock())):
            text = app_module.extract_resume_text("resume.pdf", "application/pdf", b"%PDF-1.4 fake bytes")
        self.assertIn("Jane Doe", text)
        fake_converter.convert.assert_called_once()

    def test_docx_routes_through_docling(self):
        fake_converter = MagicMock()
        fake_result = MagicMock()
        fake_result.document.export_to_markdown.return_value = "# Resume"
        fake_converter.convert.return_value = fake_result
        with patch.object(app_module, "_get_docling_classes", return_value=(fake_converter, MagicMock())):
            text = app_module.extract_resume_text(
                "resume.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                b"fake docx bytes",
            )
        self.assertEqual(text, "# Resume")

    def test_docling_parse_failure_becomes_clean_error(self):
        fake_converter = MagicMock()
        fake_converter.convert.side_effect = RuntimeError("corrupt structure, internal traceback details")
        with patch.object(app_module, "_get_docling_classes", return_value=(fake_converter, MagicMock())):
            with self.assertRaises(app_module.ResumeExtractionError) as ctx:
                app_module.extract_resume_text("resume.pdf", "application/pdf", b"garbage")
        # The internal exception text must not leak to the user-facing message.
        self.assertNotIn("internal traceback details", str(ctx.exception))

    def test_docling_extracts_to_empty_text_is_rejected(self):
        fake_converter = MagicMock()
        fake_result = MagicMock()
        fake_result.document.export_to_markdown.return_value = "   "
        fake_converter.convert.return_value = fake_result
        with patch.object(app_module, "_get_docling_classes", return_value=(fake_converter, MagicMock())):
            with self.assertRaises(app_module.ResumeExtractionError):
                app_module.extract_resume_text("resume.pdf", "application/pdf", b"whatever")

    def test_docling_not_installed_produces_clean_error(self):
        app_module._docling_converter = None
        app_module._docling_stream_class = None
        with patch.dict("sys.modules", {"docling.document_converter": None}):
            with self.assertRaises(app_module.ResumeExtractionError) as ctx:
                app_module._get_docling_classes()
        self.assertIn("PDF/DOCX parsing isn't available", str(ctx.exception))
        app_module._docling_converter = None
        app_module._docling_stream_class = None


class TestResumeUploadEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app_module.app)
        self.fake_profile = {"id": 1, "university": "Test U", "major": "CS", "year": "Junior"}

    def test_txt_upload_end_to_end_without_docling(self):
        with patch.object(app_module, "require_profile", return_value=self.fake_profile):
            response = self.client.post(
                "/resume-upload",
                headers={"X-Device-Id": "device-1"},
                files={"file": ("resume.txt", io.BytesIO(b"Jane Doe, Software Engineer"), "text/plain")},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["document_content"], "Jane Doe, Software Engineer")

    def test_pdf_upload_uses_mocked_docling_and_returns_markdown(self):
        fake_converter = MagicMock()
        fake_result = MagicMock()
        fake_result.document.export_to_markdown.return_value = "# Jane Doe\n- Bullet one"
        fake_converter.convert.return_value = fake_result
        with patch.object(app_module, "require_profile", return_value=self.fake_profile), \
             patch.object(app_module, "_get_docling_classes", return_value=(fake_converter, MagicMock())):
            response = self.client.post(
                "/resume-upload",
                headers={"X-Device-Id": "device-1"},
                files={"file": ("resume.pdf", io.BytesIO(b"%PDF-1.4 ..."), "application/pdf")},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["document_content"], "# Jane Doe\n- Bullet one")

    def test_unsupported_file_type_returns_400_with_clean_message(self):
        with patch.object(app_module, "require_profile", return_value=self.fake_profile):
            response = self.client.post(
                "/resume-upload",
                headers={"X-Device-Id": "device-1"},
                files={"file": ("resume.exe", io.BytesIO(b"MZ..."), "application/octet-stream")},
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Unsupported file type", response.json()["detail"])

    def test_upload_requires_profile(self):
        with patch.object(app_module, "get_profile_by_device", return_value=None):
            response = self.client.post(
                "/resume-upload",
                headers={"X-Device-Id": "unknown-device"},
                files={"file": ("resume.txt", io.BytesIO(b"hello"), "text/plain")},
            )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
