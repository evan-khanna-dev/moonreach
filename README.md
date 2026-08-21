# MoonReach Student Career Workspace

MoonReach is a persistent student career operating system, presented entirely as an interactive 3D scene rather than a traditional dashboard. A student sets up their profile (university, major, year) once per browser; every chat afterward only asks what that specific chat/pursuit is about. Each chat has its own durable Career Radar and action plan, while North Star synthesizes across the profile and every chat that belongs to it.

## The 3D scene is the UI

There's no nav bar, sidebar, or dashboard page — the moon, ridge, asteroid belt, and north star *are* the navigation. Clicking an object opens its feature as a 2D overlay panel on top of the scene, and the camera tweens to focus on whatever you clicked:

| Scene object | Opens |
|---|---|
| Ridge | Profile (university, major, year) |
| Asteroid belt | Chats list → chat interface |
| Moon | Career Radar (opportunities aggregated across every chat, drag to reorder by priority) |
| North Star (the flare) | North Star goal + AI-generated Action Plan, as two tabs in one panel |
| Highlighted background stars | One-click recommended chat prompts |

Drag to orbit, scroll to zoom, and the scene drifts gently on its own when idle. Closing a panel returns the camera to wherever it was before (or one level out, for the belt's chat-list-then-chat docking). `static/scene.js` owns all Three.js rendering and camera control; `static/app.js` owns all backend I/O and panel/state management, and the two only talk to each other through `window.MR.bus` (events) and `window.MR.scene` (camera/scene commands).

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

3. Ensure `.env` contains your Supabase keys and Anthropic API key:
   ```
   ANTHROPIC_API_KEY=...
   SUPABASE_URL=...
   SUPABASE_KEY=...        # or SUPABASE_SERVICE_ROLE_KEY if RLS is enabled
   ANTHROPIC_MODEL=...     # optional, defaults to claude-sonnet-5
   ```
   - If Supabase row-level security is enabled, set `SUPABASE_SERVICE_ROLE_KEY` instead of `SUPABASE_KEY`.
   - If you only have `SUPABASE_KEY`, writes may fail unless your Supabase RLS policies explicitly allow the anonymous key to insert/select on the relevant tables.
   - Run the migrations listed under [Database changes](#database-changes) below in the Supabase SQL editor before first use.

4. Run the app:
   ```powershell
   uvicorn app:app --reload
   ```

5. Open the UI:
   - Visit `http://127.0.0.1:8000/`

## Features

- **3D scene navigation** — no sidebar or dashboard; every feature is reached by clicking an object in the scene (see table above), opening as a focused overlay panel while the camera moves to match; hovering a clickable object gives a subtle glow/scale affordance
- One-time profile onboarding (university, major, year), captured once per browser via an anonymous device id and editable any time from the ridge panel
- Chats are per-pursuit: starting a new chat only asks what that chat is about, since identity is already known; the asteroid belt's chat list scales independently of how many chats exist (the belt itself always shows the same small set of rocks)
- Persistent Career Radar and action plan per chat, with durable opportunities, priorities, statuses, and source links; the radar panel aggregates opportunities across every chat you have and lets you drag-reorder (or use the up/down buttons) to reprioritize
- Claude-powered chat that can discover opportunities and update the Career Radar through structured instructions
- North Star synthesizes across the whole profile and all of its chats, with a visible "last updated" timestamp and a "what's new" summary each time it's regenerated; the same panel holds a short user-set North Star goal statement and a generated, per-chat Action Plan with per-step status
- A small, rotating subset of background stars surface as clickable, pre-filled recommended chat prompts, reshuffling with a fade transition whenever a chat finishes, the radar changes, or the action plan updates

## Database changes

Run these directly in the Supabase SQL editor, in order:
1. [supabase_migration.sql](supabase_migration.sql) (rollback: [rollback.sql](rollback.sql)) — the original `opportunities` schema
2. [supabase_migration_profiles.sql](supabase_migration_profiles.sql) (rollback: [rollback_profiles.sql](rollback_profiles.sql)) — the `profiles` table, `profile_id` on `sessions`, the `plans` table, `north_star_snapshots`, and RLS policies for all of the above
3. [supabase_migration_document_reviews.sql](supabase_migration_document_reviews.sql) (rollback: [rollback_document_reviews.sql](rollback_document_reviews.sql)) — the `document_reviews` table backing the `/document-reviews` and `/resume-upload` endpoints

[supabase_migration_scene_ui.sql](supabase_migration_scene_ui.sql) adds a few optional columns (`opportunities.notes`, and `name`/`interests`/`bio`/`north_star_goal` on `profiles`) from an earlier pass at this UI. The current frontend doesn't use them — the profile panel only edits university/major/year, and opportunity notes / the North Star goal / action-plan step status all live in browser `localStorage` instead. Running it is optional and only useful if you want to wire real server-side persistence for those fields later.

## Notes

- The app reads credentials from `.env`
- The backend still exposes `/resume-upload` and `/document-reviews` endpoints (resume feedback), but the current 3D-scene frontend has no panel for them — the appointments/resume-review UI was removed. They're only reachable by calling the API directly.
- The app still avoids user authentication, resume generation, academic advising, and gamification features
