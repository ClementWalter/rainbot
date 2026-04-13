import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { SessionProvider } from "./hooks/useSession";
import "./theme.css";

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root element in index.html");

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <BrowserRouter>
      <SessionProvider>
        <App />
      </SessionProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
