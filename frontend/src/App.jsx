import React from "react";
import { HashRouter, Routes, Route, Navigate } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { ThemeProvider } from "./context/ThemeContext";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { AppConfigProvider } from "./context/AppConfigContext";
import { LiveSocketProvider, useLiveSocketContext } from "./context/LiveSocketContext";
import Header from "./components/layout/Header";
import ChatHistoryPanel from "./components/common/ChatHistoryPanel";

import LoginPage from "./pages/LoginPage";
import OverviewPage from "./pages/OverviewPage";
import DevCollabPage from "./pages/DevCollabPage";
import AIOpsPage from "./pages/AIOpsPage";
import MonitoringPage from "./pages/MonitoringPage";
import WorkflowsPage from "./pages/WorkflowsPage";

function AppShell() {
  const { user, loading } = useAuth();
  const { connected } = useLiveSocketContext();

  if (loading) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-3 bg-base-bg text-ink-muted">
        <Loader2 size={28} className="animate-spin text-accent-devcollab" />
        <p className="text-sm">Loading platform...</p>
      </div>
    );
  }

  if (!user) {
    return <LoginPage />;
  }

  return (
    <div className="min-h-screen bg-base-bg text-ink-primary flex flex-col">
      <Header connected={connected} />
      <div className="flex flex-1 min-h-0">
        <aside className="w-56 shrink-0 hidden md:flex flex-col min-h-0">
          <ChatHistoryPanel variant="sidebar" />
        </aside>
        <main className="flex-1 overflow-y-auto min-h-0">
          <Routes>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/dev-collab" element={<DevCollabPage />} />
            <Route path="/aiops" element={<AIOpsPage />} />
            <Route path="/monitoring" element={<MonitoringPage />} />
            <Route path="/workflows" element={<WorkflowsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <AppConfigProvider>
          <LiveSocketProvider>
            <HashRouter>
              <AppShell />
            </HashRouter>
          </LiveSocketProvider>
        </AppConfigProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}
