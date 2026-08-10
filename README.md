# NeuraLearn

NeuraLearn is a personal AI-powered learning assistant that transforms video content — YouTube links or local uploads — into structured, personalized study material. It adapts to how you learn, getting smarter the more you use it.

---

## What it does

You paste a YouTube link or upload a local video. NeuraLearn handles everything from there — it fetches or extracts the transcript, runs it through AI, and gives you five different ways to actually understand and retain the content:

- **Quick Digest** — 5 high-signal bullet points distilled from the video
- **Study Notes** — Full research-grade markdown notes with sections like Abstract, Core Concepts, Critical Analysis
- **Visual Insights** — AI analysis of what was shown on screen (slides, diagrams, code)
- **Active Recall Flashcards** — 6 flip-card questions to test your memory
- **Concept Map** — An interactive Mermaid diagram showing how ideas connect

Everything is personalized. You can set an "Identity Blueprint" — tell it you're a medical student, a software engineer, a researcher — and every output adapts its tone, depth, and focus accordingly. The more feedback you give (👍/👎), the more it learns your preferences.

---

## How it works under the hood

**YouTube videos** go through `youtube-transcript-api` + `yt-dlp` fallback to get the transcript, then Groq's `llama-3.3-70b` handles all text generation — summaries, notes, flashcards, concept maps.

**Local video uploads** use `ffmpeg` to extract audio, then Groq Whisper (`whisper-large-v3-turbo`) transcribes it. Same Groq LLM pipeline handles the synthesis from there. Gemini is used as a secondary fallback for uploads if Groq is unavailable.

**Caching** is handled by Upstash Redis. Any video processed once is cached for 24 hours — the second time someone requests the same video and prompt, the response is instant with zero API calls.

**Rate limiting** via Upstash prevents API abuse: 10 YouTube requests per user per minute, 5 uploads per minute.

**Auth** uses Supabase magic link login. The JWT is verified on every backend request — the server never trusts a user ID from the client.

**User profiles** (persona blueprint, learned behaviors, feedback history) are stored in Supabase Postgres.

---

## Tech Stack

| Layer | Tech |
|---|---|
| Frontend | React + Vite, Framer Motion, Lucide Icons, Vanilla CSS |
| Backend | FastAPI (Python) |
| Primary LLM | Groq — `llama-3.3-70b-versatile` + `whisper-large-v3-turbo` |
| Vision LLM | Groq — `llama-3.2-11b-vision-preview` |
| Multimodal Fallback | Google Gemini 2.0 Flash |
| Auth + Database | Supabase (Magic Link + Postgres) |
| Cache + Rate Limit | Upstash Redis |

---

## Setup

### Prerequisites
- Python 3.10+
- Node.js 18+
- [ffmpeg](https://ffmpeg.org/download.html) — required for local video uploads (add to PATH)

### Backend

```bash
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Create a `backend/.env` file:

```env
GOOGLE_API_KEY=your_gemini_key
GROQ_API_KEY=your_groq_key
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_anon_key
UPSTASH_REDIS_URL=https://your-db.upstash.io
UPSTASH_REDIS_TOKEN=your_upstash_token
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

---

## API Keys (all free tier)

| Service | Where to get it |
|---|---|
| Groq | [console.groq.com](https://console.groq.com) |
| Google Gemini | [aistudio.google.com](https://aistudio.google.com) |
| Supabase | [supabase.com](https://supabase.com) |
| Upstash Redis | [upstash.com](https://upstash.com) |
