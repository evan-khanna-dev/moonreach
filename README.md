# MoonReach Student Career Workspace

MoonReach now behaves like a persistent student career operating system. Students onboard once, then use a durable Career Radar to track opportunities, priorities, and statuses over time while chat remains a tool for discovery and coaching.

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

- One-time onboarding with university, major, year, and career goals
- Persistent Career Radar with durable opportunities, priorities, statuses, and source links
- Claude-powered chat that can discover opportunities and update the Career Radar through structured instructions
- Career Plan generation that summarizes the conversation into actionable next steps
- Workspace UI that emphasizes the Career Radar over the chat experience

## Database changes

The new schema lives in [supabase_migration.sql](supabase_migration.sql) and adds an opportunities table with indexes and RLS guidance. The rollback script is in [rollback.sql](rollback.sql).

## Notes

- The app reads credentials from `.env`
- The backend now exposes opportunity endpoints for create, list, update, and archive flows
- The app still avoids user authentication, resume generation, academic advising, and gamification features
