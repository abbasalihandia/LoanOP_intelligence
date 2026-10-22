import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../api/client";

export interface Loaded<T> {
  data: T | undefined;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
}

/** Load data when `deps` change; `reload()` fetches again. Ignores stale responses. */
export function useLoad<T>(loader: () => Promise<T>, deps: unknown[]): Loaded<T> {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    loader()
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err : new ApiError(String(err)));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}

export type DetailTab = "overview" | "evidence" | "ai" | "resolution" | "audit";
const TABS: DetailTab[] = ["overview", "evidence", "ai", "resolution", "audit"];

export type Route = { name: "list" } | { name: "detail"; exceptionId: string; tab: DetailTab };

export function parseHash(hash: string): Route {
  const [path, queryString = ""] = hash.replace(/^#/, "").split("?");
  const match = /^\/exceptions\/([^/]+)$/.exec(path);
  if (match) {
    const tab = new URLSearchParams(queryString).get("tab") as DetailTab | null;
    return { name: "detail", exceptionId: decodeURIComponent(match[1]), tab: tab && TABS.includes(tab) ? tab : "overview" };
  }
  return { name: "list" };
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export function detailHref(exceptionId: string, tab: DetailTab = "overview"): string {
  return `#/exceptions/${encodeURIComponent(exceptionId)}${tab === "overview" ? "" : `?tab=${tab}`}`;
}

/** Seconds elapsed while `running` is true (for long AI calls). */
export function useElapsed(running: boolean): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!running) return;
    setSeconds(0);
    const started = Date.now();
    const id = window.setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(id);
  }, [running]);
  return seconds;
}
