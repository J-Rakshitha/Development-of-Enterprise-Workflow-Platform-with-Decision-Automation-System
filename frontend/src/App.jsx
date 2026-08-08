import React from "react";
import { HashRouter, Routes, Route, Navigate } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { ThemeProvider } from "./context/ThemeContext";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { LiveSocketProvider, useLiveSocketContext } from "./context/LiveSocketContext";
import Header from "./components/layout/Header";

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
    <div className="min-h-screen bg-base-bg text-ink-primary">
      <Header connected={connected} />
      <main>
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
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <LiveSocketProvider>
          <HashRouter>
            <AppShell />
          </HashRouter>
        </LiveSocketProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}
