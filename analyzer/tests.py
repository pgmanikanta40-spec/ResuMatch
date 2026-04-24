from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings

from .services import analyze_resume_match
from .storage import ResumeStorageConfigurationError, store_uploaded_resume


class ResumeStorageTests(SimpleTestCase):
    @override_settings(
        CLOUDANT_URL="",
        CLOUDANT_APIKEY="",
        CLOUDANT_DATABASE="uploaded_resumes",
        GEMINI_API_KEY="test-key",
    )
    @patch("analyzer.services.run_gemini_analysis")
    def test_analyze_resume_match_returns_disabled_storage_without_cloudant_credentials(
        self,
        mock_run_gemini_analysis,
    ):
        mock_run_gemini_analysis.return_value = {
            "score": 84,
            "summary": "Strong fit.",
            "keywords": ["Python", "APIs"],
            "matchedSkills": ["Python", "Django"],
            "missingSkills": ["Cloudant"],
            "questions": [
                {
                    "category": "Opening",
                    "text": "Tell me about your background.",
                    "tip": "Keep it concise.",
                },
                {
                    "category": "Projects",
                    "text": "Which project is most relevant here?",
                    "tip": "Focus on impact.",
                },
                {
                    "category": "Learning",
                    "text": "How do you learn new tools quickly?",
                    "tip": "Use a recent example.",
                },
            ],
        }
        resume = SimpleUploadedFile(
            "resume.txt",
            (
                "Software engineer with Python Django REST API testing debugging "
                "communication teamwork delivery ownership problem solving experience. "
                "Built and maintained web apps for internal and external users."
            ).encode("utf-8"),
            content_type="text/plain",
        )

        result = analyze_resume_match(
            resume_file=resume,
            job_description=(
                "We need a software engineer who can design, develop, test, and "
                "maintain web applications using Python, APIs, debugging, teamwork, "
                "and strong communication across stakeholders."
            ),
            target_role="Software Engineer",
            experience_level="Mid-level",
        )

        self.assertEqual(result["storage"], {"provider": "cloudant", "status": "disabled"})

    @override_settings(
        CLOUDANT_URL="https://example.cloudantnosqldb.appdomain.cloud",
        CLOUDANT_APIKEY="",
        CLOUDANT_DATABASE="uploaded_resumes",
    )
    def test_store_uploaded_resume_rejects_partial_cloudant_configuration(self):
        resume = SimpleUploadedFile(
            "resume.txt",
            b"Software engineer with enough words to pass validation and store safely.",
            content_type="text/plain",
        )

        with self.assertRaises(ResumeStorageConfigurationError):
            store_uploaded_resume(
                resume_file=resume,
                job_description="A long enough description for this storage check.",
                target_role="Software Engineer",
                experience_level="Junior",
                resume_text=(
                    "Software engineer with enough words to pass validation and store safely."
                ),
            )


class AnalyzeResumeViewTests(TestCase):
    def test_analyze_resume_returns_503_for_storage_configuration_errors(self):
        resume = SimpleUploadedFile(
            "resume.txt",
            (
                "Software engineer with Python Django JavaScript REST APIs testing "
                "communication collaboration debugging deployment and delivery experience."
            ).encode("utf-8"),
            content_type="text/plain",
        )

        with patch(
            "analyzer.views.analyze_resume_match",
            side_effect=ResumeStorageConfigurationError("Cloudant config is incomplete."),
        ):
            response = self.client.post(
                "/api/analyze/",
                {
                    "resume": resume,
                    "job_description": (
                        "We need a software engineer who can design, develop, test, and "
                        "maintain web applications using Python, JavaScript, REST APIs, "
                        "debugging, collaboration, and stakeholder communication."
                    ),
                    "target_role": "Software Engineer",
                    "experience_level": "Mid-level",
                },
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"], "Cloudant config is incomplete.")
