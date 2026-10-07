import { useState, useEffect } from "react";
import { saved, remember } from "./workbenchConfig";

export default function useWorkspaceView() {
  const [activeView, setActiveView] = useState(() => {
    const view =
      new URLSearchParams(window.location.search).get("view") ||
      saved("workbench.view", "health");
    return ["health", "recordings", "localization", "navigation"].includes(view)
      ? view
      : "health";
  });
  useEffect(() => {
    remember("workbench.view", activeView);
    const url = new URL(window.location.href);
    url.searchParams.set("view", activeView);
    window.history.replaceState(null, "", url);
  }, [activeView]);
  return [activeView, setActiveView];
}
