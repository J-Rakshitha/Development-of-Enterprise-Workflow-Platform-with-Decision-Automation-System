import React, { createContext, useContext, useEffect, useMemo, useState } from "react";
import apiClient from "../services/apiClient";

const AppConfigContext = createContext({
  loading: true,
  production: false,
  simulateEnabled: true,
  jobQueue: null,
});

function frontendProduction() {
  const viteEnv = import.meta.env.VITE_ENV || import.meta.env.MODE || "development";
  return viteEnv === "production";
}

export function AppConfigProvider({ children }) {
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiClient
      .get("/api/system/app-config")
      .then((res) => setConfig(res.data))
      .catch(() =>
        setConfig({
          production: frontendProduction(),
          simulate_enabled: !frontendProduction(),
        })
      )
      .finally(() => setLoading(false));
  }, []);

  const value = useMemo(() => {
    const backendProduction = Boolean(config?.production);
    const backendSimulate = config?.simulate_enabled !== false;
    const simulateEnabled = !frontendProduction() && !backendProduction && backendSimulate;
    return {
      loading,
      production: frontendProduction() || backendProduction,
      simulateEnabled,
      jobQueue: config?.job_queue || null,
      env: config?.env || import.meta.env.VITE_ENV || "development",
    };
  }, [config, loading]);

  return <AppConfigContext.Provider value={value}>{children}</AppConfigContext.Provider>;
}

export function useAppConfig() {
  return useContext(AppConfigContext);
}
