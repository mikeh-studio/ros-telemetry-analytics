import React from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/barlow-condensed/latin-400.css";
import "@fontsource/barlow-condensed/latin-600.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "@fontsource/ibm-plex-mono/latin-600.css";
import App from "./App";
import "./styles.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
