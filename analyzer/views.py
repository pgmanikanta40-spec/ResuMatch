from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .services import (
    AIAnalysisError,
    MissingAIConfiguration,
    ResumeTextError,
    analyze_resume_match,
)
from .storage import ResumeStorageConfigurationError, ResumeStorageError


def home(request):
    return render(request, "index.html")


def practice(request):
    return render(request, "practice.html")


@csrf_exempt
@require_POST
def analyze_resume(request):
    resume_file = request.FILES.get("resume")
    job_description = request.POST.get("job_description", "").strip()
    target_role = request.POST.get("target_role", "").strip() or "Target role"
    experience_level = request.POST.get("experience_level", "").strip() or "Fresher"

    if resume_file is None:
        return JsonResponse({"error": "Please upload a resume file."}, status=400)

    if len(job_description) < 80:
        return JsonResponse(
            {"error": "Paste a fuller job description for better questions."},
            status=400,
        )

    try:
        result = analyze_resume_match(
            resume_file=resume_file,
            job_description=job_description,
            target_role=target_role,
            experience_level=experience_level,
        )
    except MissingAIConfiguration as exc:
        return JsonResponse({"error": str(exc)}, status=503)
    except ResumeStorageConfigurationError as exc:
        return JsonResponse({"error": str(exc)}, status=503)
    except ResumeStorageError as exc:
        return JsonResponse({"error": str(exc)}, status=502)
    except ResumeTextError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except AIAnalysisError as exc:
        return JsonResponse({"error": str(exc)}, status=502)

    return JsonResponse(result)
