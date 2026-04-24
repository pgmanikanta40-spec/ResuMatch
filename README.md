# ResuMatch

Minimal Django + HTML/CSS/JS app for resume-based interview practice.

## Run locally

Create and activate the project virtual environment:

```powershell
& 'C:\Users\pgman\AppData\Local\Python\bin\python.exe' -m venv resumatch_env
.\resumatch_env\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Set your Gemini AI Studio API key before starting Django:

```powershell
Copy-Item .env.example .env
notepad .env
python manage.py runserver
```

Put your real key in `.env`:

```txt
DJANGO_SECRET_KEY=replace-this-with-a-long-random-secret
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0,testserver
DJANGO_CSRF_TRUSTED_ORIGINS=
GEMINI_API_KEY=your-real-gemini-ai-studio-key
GEMINI_MODEL=gemini-2.5-flash
GEMINI_FALLBACK_MODELS=gemini-2.5-flash-lite,gemini-2.0-flash,gemini-2.0-flash-lite
CLOUDANT_URL=https://your-cloudant-instance.cloudantnosqldb.appdomain.cloud
CLOUDANT_APIKEY=your-ibm-cloudant-iam-apikey
CLOUDANT_DATABASE=uploaded_resumes
```

Restart Django after changing `.env`.

Open:

```txt
http://127.0.0.1:8000/
```

## Backend API

```txt
POST /api/analyze/
```

Form fields:

```txt
resume
job_description
target_role
experience_level
```

The backend parses TXT, DOCX, and text-based PDF resumes, sends the resume and job description to the Gemini API, and returns a structured match score, skill gaps, summary, and practice questions.

When `CLOUDANT_URL` and `CLOUDANT_APIKEY` are configured, each uploaded resume is also stored in IBM Cloudant as a document with the file attached to it.

## Deploy on Render

Use these values in your Render web service:

```txt
Build command: pip install -r requirements.txt
Start command: gunicorn resumatch_backend.wsgi
```

Set these environment variables in Render:

```txt
DJANGO_SECRET_KEY=<long-random-secret>
DJANGO_DEBUG=False
GEMINI_API_KEY=<your-gemini-key>
GEMINI_MODEL=gemini-2.5-flash
GEMINI_FALLBACK_MODELS=gemini-2.5-flash-lite,gemini-2.0-flash,gemini-2.0-flash-lite
CLOUDANT_URL=<your-cloudant-url>
CLOUDANT_APIKEY=<your-cloudant-apikey>
CLOUDANT_DATABASE=uploaded_resumes
```

`RENDER_EXTERNAL_HOSTNAME` is provided by Render automatically, and `settings.py` adds it to `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`.
