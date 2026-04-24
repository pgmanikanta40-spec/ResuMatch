import json
import re
import time
import zipfile
from html import unescape
from pathlib import Path
from xml.etree import ElementTree

from django.conf import settings

from .storage import store_uploaded_resume


MAX_TEXT_CHARS = 16000


class MissingAIConfiguration(Exception):
    pass


class ResumeTextError(Exception):
    pass


class AIAnalysisError(Exception):
    pass


ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer"},
        "summary": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "matchedSkills": {"type": "array", "items": {"type": "string"}},
        "missingSkills": {"type": "array", "items": {"type": "string"}},
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "text": {"type": "string"},
                    "tip": {"type": "string"},
                },
                "required": ["category", "text", "tip"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "score",
        "summary",
        "keywords",
        "matchedSkills",
        "missingSkills",
        "questions",
    ],
    "additionalProperties": False,
}

SYSTEM_INSTRUCTIONS = """
You are RESUMATCH, a practical resume-to-interview preparation assistant.
Analyze the resume against the job description and return only structured JSON.
Score fit from 0 to 100 based on evidence in the resume, required skills,
responsibilities, seniority, project relevance, and communication clarity.
Generate realistic interview questions that directly target the candidate's
resume and the job description. Keep questions specific, fair, and useful.
""".strip()

SKILL_MAP = [
    ("JavaScript", ["javascript", "js", "typescript", "frontend", "ecmascript"]),
    ("React", ["react", "redux", "next.js", "component", "hooks"]),
    ("HTML/CSS", ["html", "css", "responsive", "accessibility", "semantic"]),
    ("Python", ["python", "django", "flask", "fastapi"]),
    ("APIs", ["api", "rest", "graphql", "integration", "endpoint"]),
    ("Databases", ["sql", "database", "mongodb", "postgres", "mysql", "sqlite"]),
    ("Cloud", ["aws", "azure", "gcp", "cloud", "deployment", "docker"]),
    ("Testing", ["test", "testing", "jest", "pytest", "qa", "automation"]),
    ("Communication", ["communication", "stakeholder", "client", "collaborate"]),
    ("Problem solving", ["debug", "troubleshoot", "problem", "optimize"]),
    ("Leadership", ["lead", "mentor", "ownership", "manage"]),
]


def analyze_resume_match(resume_file, job_description, target_role, experience_level):
    resume_text = extract_resume_text(resume_file)

    if len(resume_text.split()) < 25:
        raise ResumeTextError(
            "I could not read enough text from this resume. Upload a text-based PDF, DOCX, or TXT file."
        )

    storage_result = store_uploaded_resume(
        resume_file=resume_file,
        job_description=job_description,
        target_role=target_role,
        experience_level=experience_level,
        resume_text=resume_text,
    )

    if not settings.GEMINI_API_KEY:
        raise MissingAIConfiguration(
            "Real AI analysis needs GEMINI_API_KEY. Set it in your terminal and restart Django."
        )

    ai_result = run_gemini_analysis(
        resume_text=resume_text,
        job_description=job_description,
        target_role=target_role,
        experience_level=experience_level,
    )

    ai_result.update({
        "resumeName": resume_file.name,
        "role": target_role,
        "level": experience_level,
        "source": "gemini",
        "storage": storage_result,
    })

    return ai_result


def run_gemini_analysis(resume_text, job_description, target_role, experience_level):
    try:
        from google import genai
    except ImportError as exc:
        raise MissingAIConfiguration(
            "The Google GenAI Python package is not installed. Run `pip install -r requirements.txt`."
        ) from exc

    prompt = build_ai_prompt(
        resume_text=resume_text,
        job_description=job_description,
        target_role=target_role,
        experience_level=experience_level,
    )

    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    model_names = get_gemini_model_candidates()
    temporary_errors = []

    for model_name in model_names:
        for attempt in range(max(1, settings.GEMINI_MODEL_RETRIES)):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config={
                        "system_instruction": SYSTEM_INSTRUCTIONS,
                        "response_mime_type": "application/json",
                        "response_json_schema": ANALYSIS_SCHEMA,
                    },
                )
                result = parse_gemini_response(response)
                result["model"] = model_name
                return result
            except Exception as exc:
                if not is_temporary_gemini_error(exc):
                    raise AIAnalysisError(clean_gemini_error(exc)) from exc

                temporary_errors.append(model_name)
                if attempt < settings.GEMINI_MODEL_RETRIES - 1:
                    time.sleep(0.8 * (attempt + 1))
                    continue

                break

    tried = ", ".join(dict.fromkeys(temporary_errors or model_names))
    raise AIAnalysisError(
        f"Gemini is temporarily busy. I tried these models: {tried}. "
        "Please click Generate questions again in a minute."
    )


def get_gemini_model_candidates():
    candidates = [settings.GEMINI_MODEL, *settings.GEMINI_FALLBACK_MODELS]
    unique_candidates = []

    for candidate in candidates:
        if candidate and candidate not in unique_candidates:
            unique_candidates.append(candidate)

    return unique_candidates


def parse_gemini_response(response):
    try:
        data = json.loads(response.text)
    except (AttributeError, TypeError, json.JSONDecodeError) as exc:
        raise AIAnalysisError("The AI response was not valid JSON. Try again.") from exc

    return normalize_ai_result(data)


def is_temporary_gemini_error(exc):
    message = str(exc).lower()
    status = getattr(exc, "status", "")
    code = getattr(exc, "code", "")

    return (
        str(status).upper() == "UNAVAILABLE"
        or str(code) == "503"
        or "503" in message
        or "unavailable" in message
        or "high demand" in message
        or "temporarily" in message
    )


def clean_gemini_error(exc):
    message = str(exc)

    if "API key not valid" in message or "API_KEY_INVALID" in message:
        return "Gemini rejected the API key. Check GEMINI_API_KEY in your .env file and restart Django."

    if "429" in message or "RESOURCE_EXHAUSTED" in message:
        return "Gemini rate limit reached. Wait a minute, then try again."

    if "404" in message or "not found" in message.lower():
        return "The configured Gemini model is not available for this API key. Update GEMINI_MODEL in .env."

    return f"Gemini analysis failed: {message}"


def build_ai_prompt(resume_text, job_description, target_role, experience_level):
    return f"""
Target role: {target_role}
Experience level: {experience_level}

Resume text:
{resume_text}

Job description:
{job_description}

Return:
- score: integer 0 to 100
- summary: 1 concise paragraph explaining the fit
- keywords: 4 to 8 important focus areas for interview practice
- matchedSkills: skills/responsibilities supported by the resume
- missingSkills: important job requirements not clearly supported by the resume
- questions: 6 to 8 realistic interview questions, each with category, text, and answer tip
""".strip()


def normalize_ai_result(data):
    score = data.get("score", 0)

    try:
        score = int(score)
    except (TypeError, ValueError):
        score = 0

    questions = [
        {
            "category": clean_text(question.get("category", "General"))[:80],
            "text": clean_text(question.get("text", "")),
            "tip": clean_text(question.get("tip", "")),
        }
        for question in data.get("questions", [])
        if question.get("text") and question.get("tip")
    ]

    if len(questions) < 3:
        raise AIAnalysisError("The AI returned too few practice questions. Try again.")

    return {
        "score": max(0, min(100, score)),
        "summary": clean_text(data.get("summary", "")),
        "keywords": normalize_string_list(data.get("keywords", []), limit=8),
        "matchedSkills": normalize_string_list(data.get("matchedSkills", []), limit=12),
        "missingSkills": normalize_string_list(data.get("missingSkills", []), limit=12),
        "questions": questions[:8],
    }


def normalize_string_list(values, limit):
    cleaned = []

    for value in values:
        text = clean_text(value)[:80]
        if text and text not in cleaned:
            cleaned.append(text)

    return cleaned[:limit]


def extract_resume_text(resume_file):
    extension = Path(resume_file.name).suffix.lower()
    resume_file.seek(0)

    if extension == ".txt":
        return decode_bytes(resume_file.read())

    if extension == ".docx":
        return extract_docx_text(resume_file)

    if extension == ".pdf":
        return extract_pdf_text(resume_file)

    return ""


def extract_docx_text(resume_file):
    try:
        with zipfile.ZipFile(resume_file) as archive:
            document_xml = archive.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile):
        return ""

    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError:
        return ""

    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    parts = [node.text for node in root.findall(".//w:t", namespace) if node.text]
    return clean_text(" ".join(parts))


def extract_pdf_text(resume_file):
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise MissingAIConfiguration(
            "PDF parsing needs pypdf. Run `pip install -r requirements.txt`."
        ) from exc

    try:
        reader = PdfReader(resume_file)
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception:
        resume_file.seek(0)
        return extract_pdf_like_text(resume_file)

    text = clean_text(" ".join(pages))

    if text:
        return text

    resume_file.seek(0)
    return extract_pdf_like_text(resume_file)


def extract_pdf_like_text(resume_file):
    raw_text = decode_bytes(resume_file.read())
    chunks = re.findall(r"\(([^()]+?)\)", raw_text)

    if chunks:
        return clean_text(" ".join(chunks))

    return clean_text(raw_text)


def decode_bytes(value):
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return clean_text(value.decode(encoding, errors="ignore"))
        except (AttributeError, UnicodeDecodeError):
            continue

    return ""


def clean_text(value):
    text = unescape(value or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()[:MAX_TEXT_CHARS]


def detect_skills(text):
    lowered = (text or "").lower()
    skills = [
        label
        for label, terms in SKILL_MAP
        if any(re.search(rf"\b{re.escape(term)}\b", lowered) for term in terms)
    ]

    return skills


def build_focus_areas(required_skills, matched_skills, missing_skills):
    focus_areas = []

    for skill in matched_skills:
        focus_areas.append(skill)

    for skill in missing_skills:
        if skill not in focus_areas:
            focus_areas.append(skill)

    for skill in required_skills:
        if skill not in focus_areas:
            focus_areas.append(skill)

    return (focus_areas or ["Role basics", "Projects", "Communication"])[:6]


def calculate_score(job_description, resume_text, required_skills, matched_skills):
    if not required_skills:
        base_score = 62
    else:
        base_score = 48 + round((len(matched_skills) / len(required_skills)) * 34)

    resume_depth = min(12, len(resume_text.split()) // 45)
    description_depth = min(8, len(job_description.split()) // 55)

    return max(35, min(96, base_score + resume_depth + description_depth))


def build_summary(role, score, matched_skills, missing_skills):
    matched = ", ".join(matched_skills[:3]) if matched_skills else "your project experience"
    missing = ", ".join(missing_skills[:3]) if missing_skills else "role-specific examples"

    if score >= 78:
        return f"Strong fit for {role}. Lead with {matched} and prepare crisp examples for {missing}."

    if score >= 60:
        return f"Good starting fit for {role}. Strengthen your answers around {missing}."

    return f"Developing fit for {role}. Use the practice questions to connect your resume to {missing}."


def generate_questions(role, level, focus_areas, missing_skills, matched_skills):
    normalized_role = "this role" if role == "Target role" else role
    questions = [
        {
            "category": "Opening",
            "text": (
                f"Introduce yourself as a {level.lower()} candidate for "
                f"{normalized_role}. What should the interviewer remember about you?"
            ),
            "tip": (
                "Keep it under 90 seconds. Connect your skills, one resume project, "
                "and your motivation for this exact job."
            ),
        },
        {
            "category": "Resume match",
            "text": (
                f"Which resume project proves you can succeed in {normalized_role}, "
                "and what was your personal contribution?"
            ),
            "tip": (
                "Pick one project. Explain the problem, your work, the tools used, "
                "and the result without making the answer too broad."
            ),
        },
    ]

    for skill in focus_areas[:4]:
        modifier = "strongest" if skill in matched_skills else "clearest learning plan for"
        questions.append(
            {
                "category": skill,
                "text": (
                    f"How would you explain your {modifier} {skill} experience "
                    "using a real example from your resume?"
                ),
                "tip": (
                    f"Mention what you built, why {skill} mattered, what you owned, "
                    "and how you would improve it next time."
                ),
            }
        )

    if missing_skills:
        questions.append(
            {
                "category": "Skill gap",
                "text": (
                    f"The role mentions {missing_skills[0]}. How would you handle "
                    "an interview question on a skill you are still building?"
                ),
                "tip": (
                    "Be honest, then show initiative: explain related experience, "
                    "your learning plan, and how you would deliver with support."
                ),
            }
        )

    questions.extend(
        [
            {
                "category": "Scenario",
                "text": (
                    "If the interviewer gives you a requirement you have never "
                    "worked on before, how would you approach it?"
                ),
                "tip": (
                    "Clarify the goal, break the work down, research quickly, build "
                    "a small version, then ask for feedback."
                ),
            },
            {
                "category": "Closing",
                "text": (
                    "What questions would you ask the interviewer to understand "
                    "expectations for the first 90 days?"
                ),
                "tip": (
                    "Ask about success metrics, team workflow, current pain points, "
                    "and the first projects needing attention."
                ),
            },
        ]
    )

    return questions[:8]
