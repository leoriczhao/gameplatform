import React from "react";
import ReactDOM from "react-dom/client";
import { TooltipProvider } from "./components/ui/tooltip.jsx";
import App from "./App.jsx";
import { AuthProvider } from "./AuthContext.jsx";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <TooltipProvider>
      <AuthProvider>
        <App />
      </AuthProvider>
    </TooltipProvider>
  </React.StrictMode>
);
