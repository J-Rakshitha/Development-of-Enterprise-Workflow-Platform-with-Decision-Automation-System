import React, { useCallback, useEffect, useState } from "react";
import { MessageSquare, Plus, Send, Loader2 } from "lucide-react";
import {
  listChatSessions,
  createChatSession,
  getChatMessages,
  askChatQuestion,
} from "../../services/apiClient";

export default function ChatHistoryPanel({ variant = "embedded" }) {
  const isSidebar = variant === "sidebar";
  const [sessions, setSessions] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const loadSessions = useCallback(async () => {
    try {
      const res = await listChatSessions();
      const rows = res.data || [];
      setSessions(rows);
      setActiveId((prev) => {
        if (prev && rows.some((s) => s.id === prev)) return prev;
        return rows.length ? rows[0].id : null;
      });
      setError("");
    } catch {
      setError("Could not load chat history.");
    }
  }, []);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  useEffect(() => {
    if (!activeId) {
      setMessages([]);
      return;
    }
    getChatMessages(activeId)
      .then((res) => setMessages(res.data || []))
      .catch(() => setMessages([]));
  }, [activeId]);

  async function handleNewSession() {
    setBusy(true);
    setError("");
    try {
      const res = await createChatSession("New conversation");
      setSessions((prev) => [res.data, ...prev.filter((s) => s.id !== res.data.id)]);
      setActiveId(res.data.id);
      setMessages([]);
    } catch {
      setError("Could not create conversation.");
    } finally {
      setBusy(false);
    }
  }

  async function ensureSession() {
    if (activeId) return activeId;
    const res = await createChatSession("New conversation");
    setSessions((prev) => [res.data, ...prev]);
    setActiveId(res.data.id);
    return res.data.id;
  }

  async function handleAsk(e) {
    e.preventDefault();
    if (!question.trim() || asking) return;
    setAsking(true);
    setError("");
    const q = question.trim();
    setQuestion("");
    setMessages((prev) => [...prev, { role: "user", content: q }]);
    try {
      const sessionId = await ensureSession();
      const res = await askChatQuestion(sessionId, q);
      setMessages((prev) => [...prev, { role: "assistant", content: res.data.answer }]);
      await loadSessions();
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Sorry, I could not answer that right now." },
      ]);
      setError("Chat request failed.");
    } finally {
      setAsking(false);
    }
  }

  const shellClass = isSidebar
    ? "flex flex-col h-full min-h-0 bg-base-surface border-r border-base-border"
    : "bg-base-surface border border-base-border rounded-xl p-4";

  return (
    <div className={shellClass}>
      <div className={`flex items-center justify-between ${isSidebar ? "px-3 py-3 border-b border-base-border" : "mb-3"}`}>
        <h2 className="text-sm font-semibold text-ink-primary flex items-center gap-2">
          <MessageSquare size={16} className="text-accent-success" />
          Chat History
        </h2>
        <button
          onClick={handleNewSession}
          disabled={busy}
          className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg border border-base-border disabled:opacity-50"
        >
          {busy ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />} New
        </button>
      </div>

      {error && (
        <p className={`text-[11px] text-red-400 ${isSidebar ? "px-3 pb-1" : "mb-2"}`}>{error}</p>
      )}

      {isSidebar ? (
        <div className="flex flex-col flex-1 min-h-0">
          <div className="flex-1 overflow-y-auto px-2 py-2 space-y-1">
            {sessions.map((s) => (
              <button
                key={s.id}
                onClick={() => setActiveId(s.id)}
                className={`w-full text-left text-[11px] px-2 py-1.5 rounded-lg truncate ${
                  activeId === s.id ? "bg-accent-devcollab/15 text-accent-devcollab" : "text-ink-muted hover:bg-base-bg"
                }`}
              >
                {s.title}
              </button>
            ))}
            {sessions.length === 0 && (
              <p className="text-[11px] text-ink-muted px-2 py-1">No conversations yet.</p>
            )}
          </div>
          <div className="border-t border-base-border p-2 flex flex-col min-h-[180px] max-h-[45vh]">
            <div className="flex-1 overflow-y-auto space-y-2 mb-2 pr-1">
              {messages.map((m, i) => (
                <div
                  key={i}
                  className={`text-xs px-2 py-1.5 rounded-lg ${
                    m.role === "user"
                      ? "ml-auto bg-accent-devcollab/15 text-ink-primary max-w-[95%]"
                      : "bg-base-bg text-ink-secondary border border-base-border"
                  }`}
                >
                  {m.content}
                </div>
              ))}
              {!activeId && messages.length === 0 && (
                <p className="text-[11px] text-ink-muted">Type a question or click New to start.</p>
              )}
            </div>
            <form onSubmit={handleAsk} className="flex gap-2">
              <input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Ask about conflicts, incidents..."
                className="flex-1 text-xs px-2 py-1.5 rounded-lg bg-base-bg border border-base-border"
              />
              <button type="submit" disabled={asking || !question.trim()} className="px-2 py-1.5 rounded-lg bg-accent-devcollab/15 text-accent-devcollab disabled:opacity-50">
                {asking ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
              </button>
            </form>
          </div>
        </div>
      ) : (
        <div className="flex gap-3 min-h-[220px]">
          <div className="w-36 shrink-0 space-y-1 overflow-y-auto">
            {sessions.map((s) => (
              <button key={s.id} onClick={() => setActiveId(s.id)} className={`w-full text-left text-[11px] px-2 py-1.5 rounded-lg truncate ${activeId === s.id ? "bg-accent-devcollab/15 text-accent-devcollab" : "text-ink-muted hover:bg-base-bg"}`}>
                {s.title}
              </button>
            ))}
          </div>
          <div className="flex-1 flex flex-col">
            <div className="flex-1 overflow-y-auto space-y-2 mb-2 pr-1">
              {messages.map((m, i) => (
                <div key={i} className={`text-xs px-3 py-2 rounded-lg max-w-[90%] ${m.role === "user" ? "ml-auto bg-accent-devcollab/15 text-ink-primary" : "bg-base-bg text-ink-secondary border border-base-border"}`}>
                  {m.content}
                </div>
              ))}
            </div>
            <form onSubmit={handleAsk} className="flex gap-2">
              <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask a follow-up question..." className="flex-1 text-xs px-3 py-2 rounded-lg bg-base-bg border border-base-border" />
              <button type="submit" disabled={asking || !question.trim()} className="px-3 py-2 rounded-lg bg-accent-devcollab/15 text-accent-devcollab disabled:opacity-50">
                {asking ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
