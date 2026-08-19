# MoonReach Student Career Workspace

MoonReach now behaves like a persistent student career operating system. A student sets up their profile (university, major, year) once per browser; every chat afterward only asks what that specific chat/pursuit is about. Each chat has its own durable Career Radar and action plan, while North Star synthesizes across the profile and every chat that belongs to it.

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
   - Run [supabase_migration_profiles.sql](supabase_migration_profiles.sql) in the Supabase SQL editor before first use - it adds the `profiles` table, links `sessions` to it, and creates the `plans`/`north_star_snapshots` tables if they don't already exist.

4. Run the app:
   ```powershell
   uvicorn app:app --reload
   ```

5. Open the UI:
   - Visit `http://127.0.0.1:8000/`

## Features

- One-time profile onboarding (university, major, year), captured once per browser via an anonymous device id and editable later from the sidebar
- Chats are per-pursuit: starting a new chat only asks what that chat is about, since identity is already known
- Persistent Career Radar and action plan per chat, with durable opportunities, priorities, statuses, and source links
- Claude-powered chat that can discover opportunities and update the Career Radar through structured instructions
- North Star synthesizes across the whole profile and all of its chats, with a visible "last updated" timestamp and a "what's new" summary each time it's regenerated

## Database changes

The original opportunities schema lives in [supabase_migration.sql](supabase_migration.sql) (rollback: [rollback.sql](rollback.sql)). The profile/chat split - a `profiles` table, a `profile_id` column on `sessions`, the `plans` table (previously uncommitted), a `north_star_snapshots` table, and RLS policies for all of the above - lives in [supabase_migration_profiles.sql](supabase_migration_profiles.sql) (rollback: [rollback_profiles.sql](rollback_profiles.sql)). Run these directly in the Supabase SQL editor.

## Notes

- The app reads credentials from `.env`
- The backend now exposes opportunity endpoints for create, list, update, and archive flows
- The app still avoids user authentication, resume generation, academic advising, and gamification features
