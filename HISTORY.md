# HISTORY

## 2026-08-07

- Built full MVP backend with FastAPI in `app.py`.
- Connected to existing Supabase tables `sessions` and `messages` using environment variables from `.env`.
- Added web search integration using scraped Bing results and a career-focused search trigger.
- Added frontend UI in `static/index.html`, `static/styles.css`, and `static/app.js`.
- Added `requirements.txt` and `README.md` for local setup and testing.
- Added Supabase RLS-aware error handling and service role key guidance for session creation and message inserts.
- Ensured the app stays a flexible chatbot while keeping responses career-focused and avoiding out-of-scope features.
