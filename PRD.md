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
- **Frontend:** Simple web UI (plain HTML/CSS/JS or a lightweight framework), functional over polished
- **Search:** a web search API/tool, triggered conditionally as described in Feature 4

### Database Schema (already created — connect to existing tables, do not recreate)

**`sessions` table:**
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
- Do not modify the existing Supabase schema — connect to the tables as defined above