import React, { useCallback, useEffect, useState } from "react";
import { BrainCircuit, Search, Loader2 } from "lucide-react";
import { getKnowledgeBase, searchKnowledgeBase } from "../../services/apiClient";
import { useLiveSocketContext } from "../../context/LiveSocketContext";

const categoryLabel = {
  incident_resolution: "Incident Pattern",
  conflict_pattern: "Conflict Pattern",
};

/**
 * Long-term memory, visualized: every entry here is something the system
 * has "learned" from a past incident or conflict, and will reuse before
 * reasoning from scratch next time the same pattern appears.
 */
export default function KnowledgeBasePanel() {
  const [entries, setEntries] = useState([]);
  const [error, setError] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState(null);
  const [searching, setSearching] = useState(false);
  const { lastEvent } = useLiveSocketContext();

  const load = useCallback(() => {
    getKnowledgeBase()
      .then((res) => {
        setEntries(res.data);
        setError(false);
      })
      .catch(() => setError(true));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (lastEvent) load();
  }, [lastEvent, load]);

  async function handleSearch(e) {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    setSearching(true);
    try {
      const res = await searchKnowledgeBase(searchQuery.trim());
      setSearchResults(res.data);
    } catch {
      setSearchResults({ results: [], query: searchQuery });
    } finally {
      setSearching(false);
    }
  }

  return (
    <div className="bg-base-surface border border-base-border rounded-xl p-4">
      <h2 className="text-sm font-semibold text-ink-primary mb-1 flex items-center gap-2">
        <BrainCircuit size={16} className="text-accent-success" />
        Shared Knowledge Base
      </h2>
      <p className="text-xs text-ink-faint mb-3">
        Insights the agents have learned from past incidents and conflicts — reused instead of
        reasoning from scratch each time the same pattern appears.
      </p>

      <form onSubmit={handleSearch} className="flex gap-2 mb-3">
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Semantic search (Phase 5 RAG)..."
          className="flex-1 text-xs px-2.5 py-1.5 rounded-lg bg-base-bg border border-base-border text-ink-primary"
        />
        <button
          type="submit"
          disabled={searching}
          className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg bg-accent-success/15 text-accent-success border border-accent-success/30 disabled:opacity-50"
        >
          {searching ? <Loader2 size={12} className="animate-spin" /> : <Search size={12} />}
          Search
        </button>
      </form>

      {searchResults && searchResults.results?.length > 0 && (
        <div className="mb-3 space-y-1.5">
          <p className="text-[10px] uppercase tracking-wide text-accent-success font-medium">
            Semantic results ({searchResults.used_embeddings ? "embeddings" : "keyword"})
          </p>
          {searchResults.results.map((r, i) => (
            <div key={i} className="text-xs bg-base-bg border border-base-border rounded-lg px-2.5 py-2">
              <span className="text-ink-faint">{Math.round((r.similarity || 0) * 100)}% — </span>
              <span className="text-ink-secondary">{r.text?.slice(0, 120)}</span>
            </div>
          ))}
        </div>
      )}

      {!error && entries.length === 0 && (
        <p className="text-xs text-ink-muted">
          No knowledge recorded yet — it builds up as incidents and conflicts get resolved.
        </p>
      )}

      <div className="space-y-2">
        {entries.map((e) => (
          <div key={e.id} className="bg-base-bg border border-base-border rounded-lg px-3 py-2">
            <div className="flex items-center justify-between text-[11px] mb-1">
              <span className="text-accent-success font-medium">{categoryLabel[e.category] || e.category}</span>
              <span className="text-ink-faint">seen {e.success_count}×</span>
            </div>
            <p className="text-[11px] text-ink-faint font-mono mb-1">{e.key_signature}</p>
            <p className="text-xs text-ink-secondary leading-relaxed">{e.insight}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
