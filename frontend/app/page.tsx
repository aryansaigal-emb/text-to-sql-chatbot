"use client";

import {
  Activity,
  Bot,
  Database,
  FileSpreadsheet,
  Loader2,
  MessageSquarePlus,
  Play,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  Table2,
  User
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { Streamdown } from "streamdown";

type QueryResult = {
  sql?: string | null;
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
};

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  query?: QueryResult | null;
};

type SessionSummary = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

type HealthResponse = {
  ok: boolean;
  database: boolean;
  model: string;
};

const API_URL = "/backend-api";
const DISPLAY_API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8020";

const examples = [
  "What is total revenue by region?",
  "Which industries have the highest monthly recurring revenue?",
  "Show open support tickets by priority.",
  "Which products generated the most order item revenue?"
];

export default function Home() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      content:
        "Ask a question about your Supabase data. I will inspect the schema, generate safe SQL, run it, and explain the result."
    }
  ]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [schema, setSchema] = useState("Loading schema...");
  const [isLoading, setIsLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [apiStatus, setApiStatus] = useState<"checking" | "ready" | "offline">("checking");
  const [statusDetail, setStatusDetail] = useState("Checking backend...");
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  useEffect(() => {
    void initializeApp();
  }, []);

  const latestQuery = useMemo(
    () => [...messages].reverse().find((message) => message.query)?.query,
    [messages]
  );

  async function initializeApp() {
    const ready = await refreshStatus();
    if (ready) {
      await Promise.all([refreshSessions(), refreshSchema()]);
    }
  }

  async function refreshStatus() {
    try {
      const response = await fetch(`${API_URL}/health`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(await responseError(response, `Backend returned HTTP ${response.status}`));
      }
      const data = (await readJson(response)) as HealthResponse;
      if (!data.database) {
        setApiStatus("offline");
        setStatusDetail("Backend is running, but Supabase is not connected.");
        return false;
      }
      setApiStatus("ready");
      setStatusDetail(`Backend ready using ${data.model}`);
      return true;
    } catch {
      setApiStatus("offline");
      setStatusDetail("Backend is not reachable from the browser.");
      setSchema("Backend is not reachable yet.");
      return false;
    }
  }

  async function refreshSessions() {
    try {
      const response = await fetch(`${API_URL}/sessions`, { cache: "no-store" });
      if (response.ok) {
        setSessions(await readJson(response));
      }
    } catch {
      setSessions([]);
    }
  }

  async function refreshSchema() {
    try {
      const response = await fetch(`${API_URL}/schema`, { cache: "no-store" });
      if (response.ok) {
        const data = await readJson(response);
        setSchema(data.schema || "No public tables found.");
      } else {
        setSchema(await responseError(response, "Connect backend/.env to Supabase to load schema."));
      }
    } catch {
      setSchema("Backend is not reachable yet.");
    }
  }

  async function submitChat(event?: FormEvent, override?: string) {
    event?.preventDefault();
    const message = (override ?? input).trim();
    if (!message || isLoading) {
      return;
    }

    setInput("");
    setIsLoading(true);
    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: message
    };
    setMessages((current) => [...current, userMessage]);

    try {
      const response = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, session_id: sessionId })
      });
      const data = await readJson(response);
      if (!response.ok) {
        throw new Error(data.detail || "The backend could not answer.");
      }
      setSessionId(data.session_id);
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: data.answer,
          query: data.query
        }
      ]);
      void refreshSessions();
      void refreshSchema();
    } catch (error) {
      const content = error instanceof Error ? error.message : "Something went wrong.";
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content
        }
      ]);
    } finally {
      setIsLoading(false);
    }
  }

  function startNewChat() {
    setSessionId(null);
    setMessages([
      {
        id: crypto.randomUUID(),
        role: "assistant",
        content:
          "New analysis started. Ask about revenue, subscriptions, products, customer health, or support tickets."
      }
    ]);
  }

  async function loadSession(id: string) {
    setSessionId(id);
    try {
      const response = await fetch(`${API_URL}/sessions/${id}/messages`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(await responseError(response, "Could not load this session."));
      }
      const data = await readJson(response);
      setMessages(
        data.map((message: { id: number; role: "user" | "assistant"; content: string; query?: QueryResult }) => ({
          id: String(message.id),
          role: message.role,
          content: message.content,
          query: message.query
        }))
      );
    } catch {
      setMessages([
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: "I could not load that session from Supabase."
        }
      ]);
    }
  }

  async function uploadDataset(file: File | undefined) {
    if (!file || isUploading) {
      return;
    }
    setIsUploading(true);
    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch(`${API_URL}/upload-table`, {
        method: "POST",
        body: formData
      });
      const data = await readJson(response);
      if (!response.ok) {
        throw new Error(data.detail || "Upload failed.");
      }
      await refreshSchema();
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: `Uploaded ${data.original_filename} into Supabase table ${data.table_name} with ${data.rows_inserted} rows. You can now ask questions about ${data.table_name}.`
        }
      ]);
    } catch (error) {
      const content = error instanceof Error ? error.message : "Upload failed.";
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content
        }
      ]);
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <Database size={22} />
          </div>
          <div>
            <h1>QueryPilot</h1>
            <p>Supabase Text-to-SQL</p>
          </div>
        </div>

        <button className="primary-action" onClick={startNewChat}>
          <MessageSquarePlus size={18} />
          New analysis
        </button>

        <section className="panel upload-panel">
          <div className="panel-heading">
            <span>Upload Data</span>
            {isUploading ? <Loader2 className="spin" size={15} /> : <FileSpreadsheet size={15} />}
          </div>
          <label className={isUploading ? "upload-box disabled" : "upload-box"}>
            <FileSpreadsheet size={18} />
            <span>{isUploading ? "Uploading..." : "Excel or CSV"}</span>
            <input
              type="file"
              accept=".xlsx,.xls,.csv"
              disabled={isUploading}
              onChange={(event) => {
                void uploadDataset(event.target.files?.[0]);
                event.target.value = "";
              }}
            />
          </label>
          <p className="muted">Creates a new Supabase table you can query immediately.</p>
        </section>

        <section className="panel">
          <div className="panel-heading">
            <span>Connection</span>
            <button className="icon-button" onClick={refreshStatus} title="Refresh status">
              <RefreshCw size={15} />
            </button>
          </div>
          <div className={`status-pill ${apiStatus}`}>
            <span />
            {apiStatus === "ready" ? "Backend ready" : apiStatus === "checking" ? "Checking" : "Offline"}
          </div>
          <p className="muted">{statusDetail}</p>
          <p className="muted">API: {DISPLAY_API_URL}</p>
        </section>

        <section className="panel history-panel">
          <div className="panel-heading">
            <span>Recent Sessions</span>
            <Search size={15} />
          </div>
          <div className="session-list">
            {sessions.length === 0 ? (
              <p className="muted">Sessions appear after your first question.</p>
            ) : (
              sessions.map((session) => (
                <button
                  key={session.id}
                  className={session.id === sessionId ? "session active" : "session"}
                  onClick={() => loadSession(session.id)}
                  title={session.title}
                >
                  {session.title}
                </button>
              ))
            )}
          </div>
        </section>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">Ask in plain English</p>
            <h2>Explore your database without writing SQL by hand.</h2>
          </div>
          <div className="trust-row">
            <span>
              <ShieldCheck size={16} />
              Read-only SQL
            </span>
            <span>
              <Sparkles size={16} />
              Tool calling
            </span>
            <span>
              <Table2 size={16} />
              Rich demo data
            </span>
          </div>
        </header>

        <div className="content-grid">
          <section className="chat-surface">
            <div className="message-list">
              {messages.map((message) => (
                <article key={message.id} className={`message ${message.role}`}>
                  <div className="avatar">{message.role === "assistant" ? <Bot size={18} /> : <User size={18} />}</div>
                  <div className="bubble">
                    {message.role === "assistant" ? (
                      <div className="markdown-answer">
                        <Streamdown>{message.content}</Streamdown>
                      </div>
                    ) : (
                      <p>{message.content}</p>
                    )}
                    {message.query?.sql ? <SqlCard query={message.query} /> : null}
                  </div>
                </article>
              ))}
              {isLoading ? (
                <article className="message assistant">
                  <div className="avatar">
                    <Bot size={18} />
                  </div>
                  <div className="bubble thinking">
                    <Loader2 size={18} />
                    Inspecting schema and running tools...
                  </div>
                </article>
              ) : null}
              <div ref={bottomRef} />
            </div>

            <div className="example-row">
              {examples.map((example) => (
                <button key={example} onClick={() => submitChat(undefined, example)}>
                  <Play size={14} />
                  {example}
                </button>
              ))}
            </div>

            <form className="composer" onSubmit={submitChat}>
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder="Ask: MRR by industry, top products, open tickets, customer health, overdue orders..."
                rows={2}
              />
              <button type="submit" disabled={isLoading || !input.trim()} title="Send question">
                {isLoading ? <Loader2 className="spin" size={20} /> : <Send size={20} />}
              </button>
            </form>
          </section>

          <aside className="inspector">
            <section className="panel schema-panel">
              <div className="panel-heading">
                <span>Database Schema</span>
                <button className="icon-button" onClick={refreshSchema} title="Refresh schema">
                  <RefreshCw size={15} />
                </button>
              </div>
              <pre>{schema}</pre>
            </section>

            <section className="panel metric-panel">
              <div className="metric">
                <Activity size={18} />
                <div>
                  <span>{latestQuery?.row_count ?? 0}</span>
                  <p>Rows in latest result</p>
                </div>
              </div>
              <div className="metric">
                <Table2 size={18} />
                <div>
                  <span>{latestQuery?.columns.length ?? 0}</span>
                  <p>Columns returned</p>
                </div>
              </div>
            </section>
          </aside>
        </div>
      </section>
    </main>
  );
}

async function readJson(response: Response) {
  const text = await response.text();
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(text);
  }
}

async function responseError(response: Response, fallback: string) {
  const text = await response.text();
  if (!text) {
    return fallback;
  }
  try {
    const data = JSON.parse(text);
    return data.detail || data.error || fallback;
  } catch {
    return text;
  }
}

function SqlCard({ query }: { query: QueryResult }) {
  return (
    <div className="sql-card">
      <div className="sql-label">Generated SQL</div>
      <pre>{query.sql}</pre>
      {query.rows.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {query.columns.map((column) => (
                  <th key={column}>{column}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {query.rows.slice(0, 8).map((row, index) => (
                <tr key={index}>
                  {query.columns.map((column) => (
                    <td key={column}>{formatCell(row[column])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="empty-result">The query returned no rows.</p>
      )}
    </div>
  );
}

function formatCell(value: unknown) {
  if (value === null || value === undefined) {
    return "NULL";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}
