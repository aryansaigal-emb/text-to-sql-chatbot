# Text-to-SQL Chatbot

A polished Text-to-SQL chatbot with a Next.js frontend, Python/FastAPI backend, OpenRouter tool calling, and Supabase Postgres.

## What It Does

- Inspects your Supabase `public` schema.
- Uses OpenRouter function/tool calling to generate SQL.
- Runs only read-only PostgreSQL `SELECT`/CTE queries.
- Stores chat sessions and messages in Supabase.
- Shows generated SQL and result tables in a clean analyst UI.

## Project Structure

- `frontend`: Next.js app router UI.
- `backend`: FastAPI API and OpenRouter orchestration.
- `supabase/schema.sql`: App tables plus optional demo data.

## Supabase Setup

1. Create a Supabase project.
2. Open the SQL editor and run `supabase/schema.sql`.
3. Copy your database connection string from Supabase:
   Settings → Database → Connection string → URI.
4. Put that URI in `backend/.env` as `SUPABASE_DB_URL`.

## Backend Setup

```powershell
cd backend
copy .env.example .env
D:\Python\python.exe -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run_backend.py
```

Required `backend/.env` values:

```env
OPENROUTER_API_KEY=your_openrouter_key
OPENROUTER_MODEL=openai/gpt-4o-mini
SUPABASE_DB_URL=postgresql://...
APP_URL=http://localhost:3000
```

Recommended local ports for this workspace:

```powershell
$env:BACKEND_PORT="8020"
D:\Python\python.exe backend\run_backend.py
```

## Frontend Setup

```powershell
cd frontend
copy .env.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000`.

For this workspace, run the frontend on `3020`:

```powershell
npm run dev -- --hostname 127.0.0.1 --port 3020
```

Open `http://127.0.0.1:3020`.

## Good First Questions

- `What is total revenue by region?`
- `Show the top 10 customers by order value.`
- `Which plan has the highest average order amount?`

## Safety Notes

The backend rejects SQL that is not a single `SELECT` or `WITH` query and blocks common write/DDL statements. Keep your Supabase database user scoped appropriately for production.
