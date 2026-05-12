from __future__ import annotations

import json
import os
import re
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlparse

import asyncpg
import httpx
import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

load_dotenv(Path(__file__).resolve().parent / ".env")


class Settings(BaseSettings):
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    openrouter_model: str = Field(default="openai/gpt-4o-mini", alias="OPENROUTER_MODEL")
    openrouter_site_url: str = Field(default="http://localhost:3000", alias="OPENROUTER_SITE_URL")
    openrouter_app_name: str = Field(default="Text-to-SQL Chatbot", alias="OPENROUTER_APP_NAME")
    supabase_db_url: str = Field(default="", alias="SUPABASE_DB_URL")
    app_url: str = Field(default="http://localhost:3000", alias="APP_URL")


settings = Settings()
pool: asyncpg.Pool | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global pool
    if settings.supabase_db_url:
        pool = await asyncpg.create_pool(**database_connect_kwargs(), min_size=1, max_size=5)
        await ensure_app_tables()
    yield
    if pool:
        await pool.close()


app = FastAPI(title="Text-to-SQL Chatbot API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.app_url,
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None


class QueryResult(BaseModel):
    sql: str | None = None
    columns: list[str] = []
    rows: list[dict[str, Any]] = []
    row_count: int = 0


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    query: QueryResult | None = None
    tool_calls: list[str] = []


class SessionSummary(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class StoredMessage(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    content: str
    query: QueryResult | None = None
    created_at: str


class UploadResponse(BaseModel):
    table_name: str
    original_filename: str
    rows_inserted: int
    columns: list[str]


def require_database() -> asyncpg.Pool:
    if not pool:
        raise HTTPException(
            status_code=503,
            detail="SUPABASE_DB_URL is not configured. Add it to backend/.env and restart the API.",
        )
    return pool


def database_connect_kwargs() -> dict[str, Any]:
    parsed = urlparse(settings.supabase_db_url)
    if not parsed.hostname:
        raise RuntimeError("SUPABASE_DB_URL must be a valid PostgreSQL URI.")
    return {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "user": unquote(parsed.username or "postgres"),
        "password": unquote(parsed.password or ""),
        "database": parsed.path.lstrip("/") or "postgres",
        "ssl": "require",
    }


def read_uploaded_dataframe(filename: str, contents: bytes) -> pd.DataFrame:
    suffix = Path(filename).suffix.lower()
    try:
        if suffix in {".xlsx", ".xls"}:
            return pd.read_excel(BytesIO(contents))
        if suffix == ".csv":
            return pd.read_csv(BytesIO(contents))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read uploaded file: {exc}") from exc
    raise HTTPException(status_code=400, detail="Upload a .xlsx, .xls, or .csv file.")


def clean_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    dataframe = dataframe.dropna(how="all").dropna(axis=1, how="all")
    dataframe = dataframe.where(pd.notnull(dataframe), None)
    return dataframe


def safe_identifier(value: str, fallback: str = "column") -> str:
    value = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower())
    value = re.sub(r"_+", "_", value).strip("_")
    if not value:
        value = fallback
    if value[0].isdigit():
        value = f"{fallback}_{value}"
    return value[:50]


def make_unique_identifiers(values: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    identifiers: list[str] = []
    for index, value in enumerate(values, start=1):
        base = safe_identifier(value, f"column_{index}")
        count = seen.get(base, 0)
        seen[base] = count + 1
        identifiers.append(base if count == 0 else f"{base}_{count + 1}")
    return identifiers


async def unique_uploaded_table_name(db: asyncpg.Pool, filename: str) -> str:
    base = f"uploaded_{safe_identifier(Path(filename).stem, 'file')}"[:50]
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    table_name = f"{base}_{suffix}"[:63]
    async with db.acquire() as conn:
        exists = await conn.fetchval(
            """
            select exists (
              select 1 from information_schema.tables
              where table_schema = 'public' and table_name = $1
            )
            """,
            table_name,
        )
    if exists:
        table_name = f"{table_name[:56]}_{uuid.uuid4().hex[:6]}"
    return table_name


def infer_sql_types(dataframe: pd.DataFrame) -> dict[str, str]:
    types: dict[str, str] = {}
    for column in dataframe.columns:
        series = dataframe[column].dropna()
        if series.empty:
            types[column] = "text"
        elif pd.api.types.is_bool_dtype(series):
            types[column] = "boolean"
        elif pd.api.types.is_integer_dtype(series):
            types[column] = "bigint"
        elif pd.api.types.is_float_dtype(series):
            types[column] = "numeric"
        elif pd.api.types.is_datetime64_any_dtype(series):
            types[column] = "timestamptz"
        else:
            types[column] = "text"
    return types


def quote_ident(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


async def ensure_app_tables() -> None:
    db = require_database()
    async with db.acquire() as conn:
        await conn.execute(
            """
            create table if not exists app_chat_sessions (
              id uuid primary key,
              title text not null default 'New analysis',
              created_at timestamptz not null default now(),
              updated_at timestamptz not null default now()
            );

            create table if not exists app_chat_messages (
              id bigserial primary key,
              session_id uuid not null references app_chat_sessions(id) on delete cascade,
              role text not null check (role in ('user', 'assistant')),
              content text not null,
              sql text,
              rows_json jsonb,
              created_at timestamptz not null default now()
            );
            """
        )


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "database": bool(pool),
        "model": settings.openrouter_model,
    }


@app.get("/api/schema")
async def schema() -> dict[str, Any]:
    return {"schema": await get_database_schema()}


@app.post("/api/upload-table", response_model=UploadResponse)
async def upload_table(file: UploadFile = File(...)) -> UploadResponse:
    db = require_database()
    filename = file.filename or "uploaded_file"
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    dataframe = clean_dataframe(read_uploaded_dataframe(filename, contents))
    if dataframe.empty:
        raise HTTPException(status_code=400, detail="No usable rows found in the uploaded file.")
    if len(dataframe.columns) > 80:
        raise HTTPException(status_code=400, detail="Upload has too many columns. Limit is 80.")

    table_name = await unique_uploaded_table_name(db, filename)
    columns = make_unique_identifiers([str(column) for column in dataframe.columns])
    dataframe.columns = columns
    column_types = infer_sql_types(dataframe)

    async with db.acquire() as conn:
        column_sql = ", ".join(f"{quote_ident(column)} {column_types[column]}" for column in columns)
        await conn.execute(f"create table {quote_ident(table_name)} ({column_sql});")

        placeholders = ", ".join(f"${index}" for index in range(1, len(columns) + 1))
        insert_sql = (
            f"insert into {quote_ident(table_name)} "
            f"({', '.join(quote_ident(column) for column in columns)}) values ({placeholders})"
        )
        rows = [tuple(json_safe(value) for value in row) for row in dataframe.itertuples(index=False, name=None)]
        await conn.executemany(insert_sql, rows)

    return UploadResponse(
        table_name=table_name,
        original_filename=filename,
        rows_inserted=len(dataframe),
        columns=columns,
    )


@app.get("/api/sessions", response_model=list[SessionSummary])
async def sessions() -> list[dict[str, Any]]:
    db = require_database()
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            select id::text, title, created_at::text, updated_at::text
            from app_chat_sessions
            order by updated_at desc
            limit 30
            """
        )
    return [dict(row) for row in rows]


@app.get("/api/sessions/{session_id}/messages", response_model=list[StoredMessage])
async def session_messages(session_id: str) -> list[StoredMessage]:
    db = require_database()
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            select id, role, content, sql, rows_json, created_at::text
            from app_chat_messages
            where session_id = $1::uuid
            order by created_at asc, id asc
            """,
            session_id,
        )

    messages: list[StoredMessage] = []
    for row in rows:
        rows_json = normalize_stored_rows(row["rows_json"])
        query = None
        if row["sql"]:
            first_row = rows_json[0] if rows_json else {}
            columns = list(first_row.keys()) if isinstance(first_row, dict) else []
            query = QueryResult(
                sql=row["sql"],
                columns=columns,
                rows=rows_json,
                row_count=len(rows_json),
            )
        messages.append(
            StoredMessage(
                id=row["id"],
                role=row["role"],
                content=row["content"],
                query=query,
                created_at=row["created_at"],
            )
        )
    return messages


def normalize_stored_rows(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return [{"value": value}]
    if isinstance(value, dict):
        return [json_safe(value)]
    if isinstance(value, list):
        normalized: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, str):
                try:
                    item = json.loads(item)
                except json.JSONDecodeError:
                    item = {"value": item}
            if isinstance(item, dict):
                normalized.append(json_safe(item))
            else:
                normalized.append({"value": json_safe(item)})
        return normalized
    return [{"value": json_safe(value)}]


@app.post("/api/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest) -> ChatResponse:
    if not settings.openrouter_api_key:
        raise HTTPException(status_code=503, detail="OPENROUTER_API_KEY is missing in backend/.env.")

    session_id = payload.session_id or str(uuid.uuid4())
    await ensure_session(session_id, payload.message)
    history = await get_recent_messages(session_id)
    await save_message(session_id, "user", payload.message)

    direct_answer = await try_direct_uploaded_approval_answer(payload.message)
    if direct_answer:
        await save_message(session_id, "assistant", direct_answer["answer"], direct_answer["sql"], direct_answer["rows"])
        return ChatResponse(
            session_id=session_id,
            answer=direct_answer["answer"],
            query=QueryResult(sql=direct_answer["sql"], rows=direct_answer["rows"], columns=direct_answer["columns"], row_count=1),
            tool_calls=["search_uploaded_tables"],
        )

    schema_text = await get_database_schema()
    messages = build_model_messages(schema_text, history, payload.message)
    tool_names: list[str] = []
    latest_query: QueryResult | None = None

    for _ in range(4):
        model_message = await call_openrouter(messages)
        tool_calls = model_message.get("tool_calls") or []
        if not tool_calls:
            answer = model_message.get("content") or "I could not produce a response."
            await save_message(
                session_id,
                "assistant",
                answer,
                latest_query.sql if latest_query else None,
                latest_query.rows if latest_query else None,
            )
            return ChatResponse(
                session_id=session_id,
                answer=answer,
                query=latest_query,
                tool_calls=tool_names,
            )

        messages.append(model_message)
        for tool_call in tool_calls:
            function = tool_call.get("function") or {}
            name = function.get("name")
            arguments = parse_tool_arguments(function.get("arguments"))
            tool_names.append(name or "unknown")

            if name == "get_database_schema":
                result = {"schema": schema_text}
            elif name == "execute_readonly_sql":
                result = await execute_readonly_sql(arguments.get("sql", ""))
                latest_query = QueryResult(**result)
                if result.get("row_count") == 0:
                    fallback_result = await search_uploaded_tables(payload.message)
                    if fallback_result["row_count"] > 0:
                        tool_names.append("search_uploaded_tables")
                        result["fallback_search"] = fallback_result
                        result["instruction"] = (
                            "The SQL query returned zero rows, but fallback_search found likely uploaded-table "
                            "matches. Answer from fallback_search. Mention the matched activity code/name and "
                            "external_approval_c when relevant."
                        )
            elif name == "search_uploaded_tables":
                result = await search_uploaded_tables(arguments.get("query", payload.message))
            else:
                result = {"error": f"Unknown tool: {name}"}

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.get("id"),
                    "name": name,
                    "content": json.dumps(result, default=str),
                }
            )

    fallback = "I ran out of tool steps while analyzing the question. Try asking for a narrower query."
    await save_message(session_id, "assistant", fallback)
    return ChatResponse(session_id=session_id, answer=fallback, query=latest_query, tool_calls=tool_names)


async def ensure_session(session_id: str, first_message: str) -> None:
    db = require_database()
    title = make_title(first_message)
    async with db.acquire() as conn:
        await conn.execute(
            """
            insert into app_chat_sessions (id, title)
            values ($1::uuid, $2)
            on conflict (id) do update set updated_at = now()
            """,
            session_id,
            title,
        )


async def save_message(
    session_id: str,
    role: Literal["user", "assistant"],
    content: str,
    sql: str | None = None,
    rows: list[dict[str, Any]] | None = None,
) -> None:
    db = require_database()
    async with db.acquire() as conn:
        await conn.execute(
            """
            insert into app_chat_messages (session_id, role, content, sql, rows_json)
            values ($1::uuid, $2, $3, $4, $5::jsonb)
            """,
            session_id,
            role,
            content,
            sql,
            json.dumps(rows) if rows is not None else None,
        )
        await conn.execute("update app_chat_sessions set updated_at = now() where id = $1::uuid", session_id)


async def get_recent_messages(session_id: str) -> list[dict[str, str]]:
    db = require_database()
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            select role, content
            from app_chat_messages
            where session_id = $1::uuid
            order by created_at desc
            limit 8
            """,
            session_id,
        )
    return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]


async def get_database_schema() -> str:
    db = require_database()
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            select
              table_schema,
              table_name,
              column_name,
              data_type,
              is_nullable
            from information_schema.columns
            where table_schema = 'public'
              and table_name not like 'app_chat_%'
            order by table_schema, table_name, ordinal_position
            """
        )
        uploaded_tables = await conn.fetch(
            """
            select table_name
            from information_schema.tables
            where table_schema = 'public'
              and table_name like 'uploaded_%'
            order by table_name desc
            limit 5
            """
        )
        previews: list[str] = []
        for index, table in enumerate(uploaded_tables):
            table_name = table["table_name"]
            columns = await conn.fetch(
                """
                select column_name, data_type
                from information_schema.columns
                where table_schema = 'public'
                  and table_name = $1
                order by ordinal_position
                """,
                table_name,
            )
            text_columns = [column["column_name"] for column in columns if column["data_type"] in {"text", "character varying"}]
            preview_columns = [column["column_name"] for column in columns[:5]]
            if not preview_columns:
                continue
            sample_rows = await conn.fetch(
                f"""
                select {', '.join(quote_ident(column) for column in preview_columns)}
                from {quote_ident(table_name)}
                limit 3
                """
            )
            sample = [json_safe(dict(row)) for row in sample_rows]
            latest_marker = " latest_uploaded_table=true;" if index == 0 else ""
            previews.append(
                f"{table_name}{latest_marker} searchable_text_columns={text_columns}; sample_rows={json.dumps(sample, ensure_ascii=False)}"
            )

    grouped: dict[str, list[str]] = {}
    for row in rows:
        key = f"{row['table_schema']}.{row['table_name']}"
        nullable = "nullable" if row["is_nullable"] == "YES" else "required"
        grouped.setdefault(key, []).append(f"{row['column_name']} {row['data_type']} {nullable}")

    if not grouped:
        return "No user tables found in the public schema yet."

    schema_lines = [f"{table}({', '.join(columns)})" for table, columns in grouped.items()]
    if previews:
        schema_lines.append("Uploaded table previews:")
        schema_lines.extend(previews)
    return "\n".join(schema_lines)


async def execute_readonly_sql(sql: str) -> dict[str, Any]:
    cleaned = normalize_sql(sql)
    validate_readonly_sql(cleaned)
    db = require_database()
    async with db.acquire() as conn:
        records = await conn.fetch(cleaned)

    rows = [json_safe(dict(record)) for record in records]
    columns = list(rows[0].keys()) if rows else []
    return {
        "sql": cleaned,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
    }


async def search_uploaded_tables(query: str, limit: int = 12) -> dict[str, Any]:
    terms = search_terms(query)
    if not terms:
        return {"query": query, "row_count": 0, "matches": []}

    db = require_database()
    matches: list[dict[str, Any]] = []
    async with db.acquire() as conn:
        tables = await conn.fetch(
            """
            select table_name
            from information_schema.tables
            where table_schema = 'public'
              and table_name like 'uploaded_%'
            order by table_name desc
            limit 8
            """
        )
        for table in tables:
            if len(matches) >= limit:
                break
            table_name = table["table_name"]
            columns = await conn.fetch(
                """
                select column_name, data_type
                from information_schema.columns
                where table_schema = 'public'
                  and table_name = $1
                order by ordinal_position
                """,
                table_name,
            )
            text_columns = [
                column["column_name"]
                for column in columns
                if column["data_type"] in {"text", "character varying", "character"}
            ]
            if not text_columns:
                continue

            selected_columns = [column["column_name"] for column in columns[:12]]
            conditions: list[str] = []
            values: list[str] = []
            for term in terms:
                values.append(f"%{term}%")
                parameter = f"${len(values)}"
                conditions.append(
                    "(" + " or ".join(f"{quote_ident(column)} ilike {parameter}" for column in text_columns) + ")"
                )

            order_sql = ""
            if "name" in text_columns:
                order_sql = f"order by case when {quote_ident('name')} ilike $1 then 0 else 1 end"

            sql = f"""
                select {', '.join(quote_ident(column) for column in selected_columns)}
                from {quote_ident(table_name)}
                where {' or '.join(conditions)}
                {order_sql}
                limit {max(1, limit - len(matches))}
            """
            rows = await conn.fetch(sql, *values)
            for row in rows:
                item = json_safe(dict(row))
                item["_table"] = table_name
                matches.append(item)
                if len(matches) >= limit:
                    break

    return {"query": query, "terms": terms, "row_count": len(matches), "matches": matches}


async def try_direct_uploaded_approval_answer(query: str) -> dict[str, Any] | None:
    lowered = query.lower()
    if "approval" not in lowered:
        return None
    if not any(word in lowered for word in ["excel", "uploaded", "activity", "customer", "centre", "center", "care"]):
        return None

    result = await search_uploaded_tables(query, limit=5)
    if result["row_count"] == 0:
        return None

    row = result["matches"][0]
    if "external_approval_c" not in row:
        return None

    approval = row.get("external_approval_c")
    approval_text = "Yes" if approval is True else "No" if approval is False else "Not specified"
    name = row.get("name") or "Matched activity"
    code = row.get("code_c") or "N/A"
    group = row.get("activity_group_r_name") or "N/A"
    risk = row.get("risk_rating_c") or "N/A"
    table_name = row.get("_table")
    answer = (
        f"{approval_text}, external approval is {'required' if approval is True else 'not required' if approval is False else 'not specified'} "
        f"for **{name}**.\n\n"
        f"- Code: `{code}`\n"
        f"- Activity group: {group}\n"
        f"- Risk rating: {risk}\n"
        f"- Source table: `{table_name}`"
    )
    return {
        "answer": answer,
        "sql": f"fallback uploaded-table search for: {query}",
        "rows": [row],
        "columns": list(row.keys()),
    }


def search_terms(query: str) -> list[str]:
    normalized = re.sub(r"[^a-zA-Z0-9 ]+", " ", query.lower())
    stop_words = {
        "a",
        "an",
        "and",
        "are",
        "do",
        "does",
        "for",
        "from",
        "i",
        "in",
        "is",
        "it",
        "my",
        "need",
        "of",
        "on",
        "or",
        "the",
        "to",
        "we",
        "what",
        "whether",
    }
    words = [word for word in normalized.split() if len(word) > 2 and word not in stop_words]
    phrases = []
    if "customer" in words and ("care" in words or "centre" in words or "center" in words):
        phrases.extend(["customer care center", "customer care centre", "customer care"])
    if "centre" in words:
        words.append("center")
    if "center" in words:
        words.append("centre")
    if "approval" in words:
        words.append("external")
    terms = [*phrases, *words]
    unique_terms: list[str] = []
    for term in terms:
        if term not in unique_terms:
            unique_terms.append(term)
    return unique_terms[:12]


def normalize_sql(sql: str) -> str:
    sql = re.sub(r"```(?:sql)?|```", "", sql, flags=re.IGNORECASE).strip()
    if not sql.endswith(";"):
        sql = f"{sql};"
    return sql


def validate_readonly_sql(sql: str) -> None:
    lowered = re.sub(r"\s+", " ", sql.strip().lower())
    forbidden = [
        "insert ",
        "update ",
        "delete ",
        "drop ",
        "alter ",
        "create ",
        "truncate ",
        "grant ",
        "revoke ",
        "copy ",
        "call ",
        "do ",
        "execute ",
    ]
    if not lowered.startswith(("select ", "with ")):
        raise HTTPException(status_code=400, detail="Only SELECT/CTE queries are allowed.")
    if any(token in lowered for token in forbidden) or ";" in lowered[:-1]:
        raise HTTPException(status_code=400, detail="Unsafe SQL rejected.")


def build_model_messages(schema_text: str, history: list[dict[str, str]], message: str) -> list[dict[str, Any]]:
    system = f"""
You are a careful Text-to-SQL data analyst.
Use the database schema below and answer the user with business-friendly clarity.
When data is needed, call execute_readonly_sql with one safe PostgreSQL SELECT query.
If a SQL search returns no rows or the user uses approximate wording, use search_uploaded_tables as a broader fallback.
Prefer concise result sets. Always add LIMIT 100 unless the query is an aggregate.
Never modify data. Never invent columns or tables.
Uploaded tables are user-provided datasets and are very important.
If the user says Excel, spreadsheet, sheet, uploaded file, uploaded data, file, my data, this data, or imported data, use the latest_uploaded_table=true table.
If the user asks about an activity, service, course, consultancy, entity, person, product, or item and does not name a table, search the uploaded_* tables first.
For uploaded tables with text columns, use case-insensitive matching with ILIKE across relevant text columns such as name, description, group, inclusions, exclusions, and qualification.
For uploaded tables with numeric columns, answer aggregations such as count, sum, average, min, max, ranking, and grouping directly from those columns.
If a term is not exact, use broad ILIKE patterns and search multiple relevant text columns before concluding there is no match.
Do not say the data is unavailable until you have searched the relevant uploaded table text columns.

Schema:
{schema_text}
""".strip()
    return [{"role": "system", "content": system}, *history, {"role": "user", "content": message}]


async def call_openrouter(messages: list[dict[str, Any]]) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "HTTP-Referer": settings.openrouter_site_url,
        "X-Title": settings.openrouter_app_name,
    }
    payload = {
        "model": settings.openrouter_model,
        "messages": messages,
        "temperature": 0.1,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "get_database_schema",
                    "description": "Read the available public database tables and columns.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "execute_readonly_sql",
                    "description": "Run a safe read-only PostgreSQL query against Supabase.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sql": {
                                "type": "string",
                                "description": "A single SELECT or WITH query. Use PostgreSQL syntax.",
                            }
                        },
                        "required": ["sql"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_uploaded_tables",
                    "description": (
                        "Broadly search uploaded Excel/CSV tables for approximate text matches. "
                        "Use this when SQL returns no rows or user wording may differ from table values."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The user's search phrase or entity name to find in uploaded tables.",
                            }
                        },
                        "required": ["query"],
                    },
                },
            },
        ],
        "tool_choice": "auto",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"OpenRouter error: {response.text}")
    data = response.json()
    return data["choices"][0]["message"]


def parse_tool_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def make_title(message: str) -> str:
    words = re.sub(r"\s+", " ", message).strip()
    return words[:56] or f"Analysis {datetime.now(timezone.utc).strftime('%H:%M')}"
