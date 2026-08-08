import React from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { Moon, Sun, GitBranch, ServerCog, LayoutGrid, Radio, User, LogOut, Gauge, Workflow } from "lucide-react";
import { useTheme } from "../../context/ThemeContext";
import { useAuth } from "../../context/AuthContext";
import LlmFailureToggle from "../common/LlmFailureToggle";

const tabs = [
  { to: "/", label: "Overview", icon: LayoutGrid, end: true },
  { to: "/dev-collab", label: "Dev-Collaboration", icon: GitBranch },
  { to: "/aiops", label: "Incident Response", icon: ServerCog },
  { to: "/workflows", label: "Workflows", icon: Workflow },
  { to: "/monitoring", label: "Monitoring", icon: Gauge },
];

export default function Header({ connected }) {
  const { theme, toggleTheme } = useTheme();
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  function handleLogout() {
    logout();
    navigate("/", { replace: true });
  }

  return (
    <header className="flex items-center justify-between px-6 py-4 border-b border-base-border bg-base-surface">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-accent-devcollab to-accent-aiops" />
        <div>
          <h1 className="font-display text-sm font-semibold tracking-wide text-ink-primary">
            Development of Enterprise Workflow Platform with Decision Automation System
          </h1>
          <p className="text-xs text-ink-muted">Dev-Collaboration + AIOps, unified</p>
        </div>
      </div>

      <nav className="flex items-center gap-1 bg-base-bg p-1 rounded-xl border border-base-border">
        {tabs.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              `flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm transition-colors ${
                isActive
                  ? "bg-base-surface text-ink-primary shadow-sm"
                  : "text-ink-muted hover:text-ink-primary"
              }`
            }
          >
            <Icon size={15} />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="flex items-center gap-4">
        <LlmFailureToggle />
        <div className="flex items-center gap-2 text-xs text-ink-muted">
          <User size={13} />
          <span className="max-w-[120px] truncate">{user?.full_name}</span>
          <button onClick={handleLogout} className="p-1 rounded-md hover:text-ink-primary" title="Sign out">
            <LogOut size={13} />
          </button>
        </div>
        <div className="flex items-center gap-1.5 text-xs text-ink-muted">
          <Radio size={13} className={connected ? "text-accent-success" : "text-ink-faint"} />
          {connected ? "Live" : "Offline"}
        </div>
        <button
          onClick={toggleTheme}
          className="p-2 rounded-lg border border-base-border text-ink-muted hover:text-ink-primary transition-colors"
          aria-label="Toggle theme"
        >
          {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
        </button>
      </div>
    </header>
  );
}
