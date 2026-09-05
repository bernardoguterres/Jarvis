import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App.tsx";
import ErrorBoundary from "./components/diagnostic/ErrorBoundary.tsx";

// Feature-detected once at startup — lets index.css apply a short plain
// CSS crossfade fallback (`.no-view-transitions`) only in browsers that
// lack `document.startViewTransition`, without any JS timing of its own.
if (typeof document.startViewTransition !== "function") {
  document.documentElement.classList.add("no-view-transitions");
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
