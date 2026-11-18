"use client";
// Load data from the API in a component, optionally refreshing every N ms.
//   const { data, error, loading, reload } = useApi("/agent/runs", { refreshMs: 5000 });
// Pass path = null to load nothing (e.g. until an id is known).

import { useCallback, useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";

export function useApi(path, { refreshMs = 0 } = {}) {
  const [state, setState] = useState({ data: null, error: null, loading: Boolean(path) });
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!path) return undefined;
    const controller = new AbortController();
    apiFetch(path, { signal: controller.signal })
      .then((data) => setState({ data, error: null, loading: false }))
      .catch((error) => {
        // AbortError = we cancelled it (component unmounted / path changed): ignore.
        if (error.name !== "AbortError") setState((s) => ({ ...s, error, loading: false }));
      });
    return () => controller.abort(); // a stale response can never overwrite newer data
  }, [path, tick]);

  useEffect(() => {
    if (!refreshMs || !path) return undefined;
    const id = setInterval(() => {
      // Don't poll a tab nobody is looking at (saves requests and battery).
      if (document.visibilityState === "visible") reload();
    }, refreshMs);
    return () => clearInterval(id);
  }, [refreshMs, path, reload]);

  return { ...state, reload };
}
