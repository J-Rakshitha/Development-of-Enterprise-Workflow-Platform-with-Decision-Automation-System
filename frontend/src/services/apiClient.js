import axios from "axios";

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
export const WS_URL = API_BASE_URL.replace("http", "ws") + "/ws/live";

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000,
});

apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem("coordination_engine_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// ---------- Auth (Phase C) ----------
export const login = (payload) => apiClient.post("/api/auth/login", payload);
export const register = (payload) => apiClient.post("/api/auth/register", payload);
export const getMe = () => apiClient.get("/api/auth/me");
export const listUsers = () => apiClient.get("/api/auth/users");

// ---------- Monitoring (Phase B + Milestone 4) ----------
export const getMonitoringStatus = () => apiClient.get("/api/monitoring/status");
export const getMonitoringHistory = (serviceName, limit = 20) =>
  apiClient.get(`/api/monitoring/history/${serviceName}`, { params: { limit } });
export const getMonitoringUptime = (serviceName, hours = 24) =>
  apiClient.get(`/api/monitoring/uptime/${serviceName}`, { params: { hours } });
export const getMonitoringSummary = () => apiClient.get("/api/monitoring/summary");

// ---------- Dev-Collaboration ----------
export const startEditSession = (payload) => apiClient.post("/api/dev-collab/edit-session/start", payload);
export const endEditSession = (sessionId) => apiClient.post(`/api/dev-collab/edit-session/${sessionId}/end`);
export const getActiveSessions = () => apiClient.get("/api/dev-collab/active-sessions");
export const checkConflicts = () => apiClient.post("/api/dev-collab/check-conflicts");
export const listConflicts = () => apiClient.get("/api/dev-collab/conflicts");
export const suggestResolution = (conflictId) =>
  apiClient.post(`/api/dev-collab/conflicts/${conflictId}/suggest-resolution`);
export const approveConflict = (conflictId) =>
  apiClient.post(`/api/dev-collab/conflicts/${conflictId}/approve`, null, { timeout: 30000 });
export const rejectConflict = (conflictId, note = "") =>
  apiClient.post(`/api/dev-collab/conflicts/${conflictId}/reject`, { note });
export const deferConflict = (conflictId, note = "") =>
  apiClient.post(`/api/dev-collab/conflicts/${conflictId}/resolve-later`, { note });
export const undoConflictAction = (conflictId) =>
  apiClient.post(`/api/dev-collab/conflicts/${conflictId}/undo`);
export const submitRepo = (repoUrl) =>
  apiClient.post("/api/dev-collab/repo/submit", { repo_url: repoUrl }, { timeout: 60000 });
export const getMyRepo = () => apiClient.get("/api/dev-collab/repo/mine");
export const recheckRepo = () =>
  apiClient.post("/api/dev-collab/repo/recheck", null, { timeout: 60000 });
// LLM + Slack notifications can take 15–20s — use a longer timeout than default 10s
export const simulateDemoConflict = () =>
  apiClient.post("/api/dev-collab/simulate-demo-conflict", null, { timeout: 45000 });
export const listCommits = () => apiClient.get("/api/dev-collab/commits");
export const githubStatus = () => apiClient.get("/api/dev-collab/github/status");
export const githubSync = () => apiClient.post("/api/dev-collab/github/sync", null, { timeout: 45000 });
export const repositoryDiscovery = (params) =>
  apiClient.post("/api/dev-collab/repository/discovery", null, { params, timeout: 60000 });

// ---------- AIOps ----------
export const ingestMetrics = (payload) => apiClient.post("/api/incidents/ingest-metrics", payload);
export const simulateIncident = () =>
  apiClient.post("/api/incidents/simulate", null, { timeout: 45000 });
export const listIncidents = () => apiClient.get("/api/incidents/");

// ---------- System ----------
export const getAppConfig = () => apiClient.get("/api/system/app-config");
export const getStats = () => apiClient.get("/api/system/stats");
export const getKnowledgeBase = () => apiClient.get("/api/system/knowledge-base");
export const searchKnowledgeBase = (query) =>
  apiClient.get("/api/system/knowledge-base/search", { params: { q: query } });
export const toggleLlmFailure = (enabled) => apiClient.post(`/api/system/toggle-llm-failure?enabled=${enabled}`);
export const getLlmFailureStatus = () => apiClient.get("/api/system/llm-failure-status");
export const getDecisionLog = () => apiClient.get("/api/system/decision-log");
export const getNotifications = () => apiClient.get("/api/system/notifications");
export const getIntegrations = () => apiClient.get("/api/system/integrations");
export const testEmail = () => apiClient.post("/api/system/test-email");
export const testDiscordWebhook = (url) =>
  apiClient.post("/api/system/test-discord-webhook", url ? { url } : {});

// ---------- Tool Integration (Milestone 2) ----------
export const listTools = () => apiClient.get("/api/tools/");
export const selectAndExecuteTool = (payload) => apiClient.post("/api/tools/select-and-execute", payload);
export const getToolAccuracy = () => apiClient.get("/api/tools/accuracy");

// ---------- Chat History (E6) ----------
export const listChatSessions = () => apiClient.get("/api/chat/sessions");
export const createChatSession = (title = "New conversation") =>
  apiClient.post("/api/chat/sessions", { title });
export const getChatMessages = (sessionId) =>
  apiClient.get(`/api/chat/sessions/${sessionId}/messages`);
export const askChatQuestion = (sessionId, question) =>
  apiClient.post(`/api/chat/sessions/${sessionId}/ask`, { question });

// ---------- Workflow Orchestration (Milestone 4) ----------
export const listWorkflowDefinitions = () => apiClient.get("/api/workflows/definitions");
export const startWorkflow = (templateKey, context = {}) =>
  apiClient.post("/api/workflows/start", { template_key: templateKey, context }, { timeout: 60000 });
export const listWorkflowRuns = (status) =>
  apiClient.get("/api/workflows/runs", { params: status ? { status } : {} });
export const getWorkflowRun = (runId) => apiClient.get(`/api/workflows/runs/${runId}`);
export const getWorkflowTimeline = (runId) => apiClient.get(`/api/workflows/runs/${runId}/timeline`);
export const resumeWorkflow = (runId) =>
  apiClient.post(`/api/workflows/runs/${runId}/resume`, null, { timeout: 60000 });
export const cancelWorkflow = (runId) => apiClient.post(`/api/workflows/runs/${runId}/cancel`);
export const getWorkflowStats = () => apiClient.get("/api/workflows/stats");

// ---------- Agent Metrics & Admin (Milestone 4) ----------
export const getAgentMetrics = () => apiClient.get("/api/system/agent-metrics");
export const acknowledgeNotification = (id) =>
  apiClient.post(`/api/system/notifications/${id}/acknowledge`);
export const getAdminSystemHealth = () => apiClient.get("/api/admin/system-health");
export const triggerProbe = () => apiClient.post("/api/admin/monitoring/trigger-probe", null, { timeout: 30000 });
export const getAdminMonitoringConfig = () => apiClient.get("/api/admin/monitoring/config");
export const listMonitoredServices = () => apiClient.get("/api/admin/monitored-services");
export const createMonitoredService = (payload) =>
  apiClient.post("/api/admin/monitored-services", payload);
export const updateMonitoredService = (id, payload) =>
  apiClient.put(`/api/admin/monitored-services/${id}`, payload);
export const deleteMonitoredService = (id) =>
  apiClient.delete(`/api/admin/monitored-services/${id}`);

export const healthCheck = () => apiClient.get("/api/system/health");

export default apiClient;
