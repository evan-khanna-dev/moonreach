# Product Requirements Document: Student Career Coach (Working Title)

## NOTE: never read, display, or transmit the contents of .env, only reference variable names in code

## Overview
An AI career coach built specifically for students, so context (university, major, year, goals) only needs to be provided once, and every conversation afterward is grounded in that context. The tool proactively surfaces university-specific opportunities via web search rather than giving generic advice. Built for the Stellic Pathfinders Challenge (submission deadline August 21, 2026), category: College to Career.

## Goals
- Demonstrate a genuinely useful, working AI coaching experience in under two weeks
- Prove the specific differentiator: a student doesn't have to explain their context repeatedly, and the tool surfaces real, local opportunities (not just generic advice)
- Produce a clean, demoable, open-source artifact suitable for both the competition submission and a public GitHub portfolio piece

## Non-Goals (explicitly out of scope for this MVP)
- Resume generation
- Role/job matching engine
- Progress tracking, gamification, streaks, or "weekly summary" style features
- User authentication/accounts (fully anonymous per-session for this demo)
- Academic advising (course selection, degree requirements, scheduling) — this tool is career-focused only

## Users
College students (the competition's actual entrant/judge audience), who want quick, contextual career guidance without repeatedly explaining who they are and what they need.

## Core Features

### 1. Onboarding (one-time context capture)
- A short form or guided first exchange capturing: university, major, year/semester standing, general goals (free text)
- This creates a new session, stored in the `sessions` table (see schema below)
- Returns a `session_id` used for all subsequent requests

### 2. Conversational Coaching Interface
- Plain-language chat, powered by the Claude API
- Every message sent to Claude includes: a system prompt establishing the coaching persona, the session's stored context (university/major/year/goals), and the full prior conversation history for that session
- Both the user's message and Claude's response are stored in the `messages` table
- No re-explaining context required across the conversation

### 3. Suggested Reply Chips
- After each assistant response, generate 2-4 short, plausible next-user-replies relevant to the conversation so far
- Displayed as clickable chips in the UI; clicking a chip sends that text as the user's next message through the same chat pipeline as manually typed messages
- User can always ignore the chips and type freely instead

### 4. University-Specific Opportunity Search
- Must support **any university**, not a fixed list — this is handled entirely through the web search itself (search query includes the session's stored university name + relevant topic), so no hardcoded per-university data or logic is needed
- When the conversation calls for it (the user asks about career-related opportunities, clubs, career center resources, employer connections, etc.), trigger a web search scoped to the session's stored university plus the relevant topic
- Feed search results back into the prompt sent to Claude so the response is grounded in real, current information rather than generic/invented suggestions
- Detection of "when to search" can be a simple keyword heuristic or left to Claude via tool-calling, implementer's choice, whichever is faster to build reliably

### 5. Plan Generator
- A separate endpoint/action that takes the full conversation history for a session and asks Claude to summarize it into a short, actionable list of next steps
- Returned as a simple list, not a complex tracker or persistent goal system

## Technical Requirements

### Stack
- **Backend:** Python, FastAPI
- **AI:** Claude API (Anthropic Python SDK)
- **Database:** Supabase (Postgres)
- **Frontend:** Plain HTML/CSS/JS, no framework. Implemented as a Three.js 3D scene (moon, ridge, asteroid belt, north star, starfield) that serves as the entire navigation surface — every feature opens as a 2D overlay panel triggered by clicking an object in the scene, rather than a traditional page/dashboard layout.
- **Search:** a web search API/tool, triggered conditionally as described in Feature 4

### Database Schema

The schema below is what shipped for the MVP demo (`sessions`, `messages`) — see [Current Implementation Status](#current-implementation-status) for how it grew from there. Original tables, connected to as-is, not recreated:

**`sessions` table (original shape):**
| Column | Type | Notes |
|---|---|---|
| `id` | `int8` | primary key, identity/auto-increment |
| `university` | `text` | |
| `major` | `text` | |
| `year` | `text` | |
| `goals` | `text` | |
| `created_at` | `timestamptz` | default `now()` |

**`messages` table:**
| Column | Type | Notes |
|---|---|---|
| `id` | `int8` | primary key, identity/auto-increment |
| `session_id` | `int8` | foreign key → `sessions.id`; on update: no action; on delete: cascade |
| `role` | `text` | `"user"` or `"assistant"` |
| `content` | `text` | |
| `created_at` | `timestamptz` | default `now()` |

- Row Level Security (RLS) is enabled on both tables (automatic on all new tables in this project). Policies must allow the app's normal read/write operations using the Supabase key stored in the backend's environment (see Environment Variables below) — write policies permitting insert/select for this key if not already configured.
- Realtime is enabled on the `messages` table only (not `sessions`).

### Environment Variables (already set — read from `.env`, do not hardcode)
```
ANTHROPIC_API_KEY=...
SUPABASE_URL=...
SUPABASE_KEY=...
```
As the app grew, two optional variables were added: `SUPABASE_SERVICE_ROLE_KEY` (used instead of `SUPABASE_KEY` when RLS requires it) and `ANTHROPIC_MODEL` (defaults to `claude-sonnet-5` if unset). See `README.md` for the current full list.

### API Endpoints (suggested shape — implementer may adjust naming/structure as needed)
1. `POST /session` — accepts university, major, year, goals; inserts into `sessions`; returns `session_id`
2. `POST /chat` — accepts `session_id` + user message; retrieves session context + message history from Supabase; calls Claude; inserts both user and assistant messages into `messages`; returns assistant response + suggested reply chips
3. `POST /plan` — accepts `session_id`; retrieves full message history; asks Claude to summarize into an actionable next-steps list; returns that list

## Success Criteria
- A user can complete onboarding, have a multi-turn conversation where the AI clearly remembers their context without being re-told, click at least one suggested chip successfully, receive at least one genuinely university-specific (not generic) answer via the search feature, and generate a final plan
- The app runs end-to-end locally (or deployed) well enough to record a clean 2-minute demo video
- Code is clean enough to serve as a public, open-source portfolio piece (MIT license), not just a working script

## Submission Requirements (for context, not to be built into the app itself)
- Public GitHub repo (satisfies "working prototype link")
- 2-minute demo video (YouTube/Vimeo/Loom)
- 500-word written overview
- Full AI-tool disclosure (Claude API, Supabase, any search API/library used, and note that Claude Code was used in development)
- Category: **College to Career** (final, not to be changed)

## Out of Scope Reminders for the Builder
- Do not add authentication
- Do not add resume generation, role-matching, or gamification features
- Do not add academic advising features (course/degree planning) — career-focused only
- Do not hardcode support for specific universities — the search feature must work generically for any university name provided
- Do not silently alter the original `sessions`/`messages` tables — new tables/columns for later features (see below) must go through an explicit, reviewed migration + rollback pair, same as the ones already in this repo

## Current Implementation Status

The MVP above shipped, then grew past it. This section tracks the delta so the PRD stays a useful reference instead of a historical artifact.

- **Frontend rebuilt as a 3D scene.** No page/dashboard layout — the moon, ridge, asteroid belt, and north star are the entire navigation surface; clicking one opens its feature as a 2D overlay panel. See `README.md` for the object → feature mapping.
- **Identity split out of `sessions` into a `profiles` table**, captured once per browser via an anonymous device id (`X-Device-Id` header) instead of once per chat. `sessions` now holds `profile_id` + `goals` per chat; university/major/year live on `profiles`. Migration: `supabase_migration_profiles.sql`.
- **Career Radar added** — a persistent `opportunities` table per chat (title, category, description, priority, status, source), which Claude can add/update/reprioritize/archive through structured `career_radar_updates` in its response. Migration: `supabase_migration.sql`.
- **Action Plan persisted** — a `plans` table per chat, generated on demand from that chat's history (still matches the original Plan Generator feature, just now saved rather than ephemeral).
- **North Star added** — cross-chat synthesis (current direction, priorities, risks, upcoming opportunities) over the whole profile and every chat under it, snapshotted to `north_star_snapshots` so the UI can show "what's new" since the last run. Not in the original MVP scope; added afterward as the profile-level complement to per-chat plans.
- **Resume feedback added, then its frontend removed.** A `document_reviews` table and `/resume-upload` + `/document-reviews` endpoints (PDF/DOCX/TXT extraction via Docling, structured feedback, follow-up thread) were built and are still live on the backend, but the overlay panel for them was removed from the 3D-scene frontend — they're only reachable by calling the API directly today. This is resume *feedback on existing content*, not resume *generation*, so it doesn't conflict with the Non-Goals above. Migration: `supabase_migration_document_reviews.sql`.
- **`supabase_migration_scene_ui.sql` exists but is optional/unused.** It adds `opportunities.notes` and extra `profiles` columns (`name`, `interests`, `bio`, `north_star_goal`) from an earlier pass at the 3D UI. The current frontend keeps those fields in browser `localStorage` instead, so this migration isn't required for the app to run.