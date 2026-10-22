import { createContext, useContext, useState, type ReactNode } from "react";

// POC only: there is no authentication. The analyst identifier is typed in
// the header and recorded on status changes, investigations and resolutions.
const STORAGE_KEY = "loanops.analystId";

interface AnalystState {
  analystId: string;
  setAnalystId: (value: string) => void;
}

const AnalystContext = createContext<AnalystState>({ analystId: "", setAnalystId: () => undefined });

function readStored(): string {
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function AnalystProvider({ children }: { children: ReactNode }) {
  const [analystId, setState] = useState<string>(readStored);
  const setAnalystId = (value: string) => {
    setState(value);
    try {
      window.localStorage.setItem(STORAGE_KEY, value);
    } catch {
      // storage unavailable (private mode); keep the in-memory value
    }
  };
  return <AnalystContext.Provider value={{ analystId, setAnalystId }}>{children}</AnalystContext.Provider>;
}

export function useAnalyst(): AnalystState {
  return useContext(AnalystContext);
}

/** Mirrors the backend rule: analyst ids cannot use the reserved "system:" prefix. */
export function analystIdProblem(id: string): string | null {
  const trimmed = id.trim();
  if (!trimmed) return "Enter your analyst ID in the header first.";
  if (trimmed.toLowerCase().startsWith("system:")) return "IDs starting with 'system:' are reserved for the platform.";
  return null;
}
