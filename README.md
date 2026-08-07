# MoonReach Student Career Coach

A hackathon MVP for a student career coaching chatbot with one-time onboarding context, suggested reply chips, university-specific opportunity search, and a plan generator.

## Run locally

1. Activate the existing virtual environment:
   - Windows PowerShell:
     ```powershell
     .\.venv\Scripts\Activate.ps1
     ```
   - Windows CMD:
     ```cmd
     .\.venv\Scripts\activate.bat
     ```

2. Install dependencies if needed:
   ```powershell
   pip install -r requirements.txt
   ```

3. Ensure `.env` contains your Supabase keys and Anthropic API key.
   - If Supabase row-level security is enabled, set `SUPABASE_SERVICE_ROLE_KEY` instead of `SUPABASE_KEY`.
   - If you only have `SUPABASE_KEY`, the `sessions` and `messages` inserts may fail unless your Supabase RLS policies explicitly allow the anonymous key to insert and select from those tables.

4. Run the app:
   ```powershell
   uvicorn app:app --reload
   ```

5. Open the UI:
   - Visit `http://127.0.0.1:8000/`

## Features

- One-time session onboarding with university/major/year/goals
- Chat-based career coaching powered by Anthropic Claude
- Suggested reply chips that can be clicked to continue the conversation
- University-specific opportunity search using a generic web search scraper
- Plan generation endpoint that summarizes the conversation into actionable next steps

## Notes

- The app reads credentials from `.env`
- Do not add user authentication, resume generation, academic advising, or gamification features
