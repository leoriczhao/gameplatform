import { createContext, useCallback, useContext, useEffect, useState } from "react";

const ThemeContext = createContext(null);
const STORAGE_KEY = "gp_lab_theme";

function readSavedTheme() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "dark" || saved === "light") return saved;
  } catch (e) {
    /* localStorage unavailable */
  }
  return "light";
}

function readInitialTheme() {
  try {
    const fromQuery = new URLSearchParams(window.location.search).get("theme");
    if (fromQuery === "dark" || fromQuery === "light") return fromQuery;
  } catch (e) {
    /* no window */
  }
  return readSavedTheme();
}

export function LabThemeProvider({ children }) {
  const [theme, setTheme] = useState(readInitialTheme);

  useEffect(() => {
    document.documentElement.dataset.labTheme = theme;
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch (e) {
      /* ignore quota / privacy mode */
    }
  }, [theme]);

  const toggle = useCallback(
    () => setTheme((t) => (t === "dark" ? "light" : "dark")),
    [],
  );

  return (
    <ThemeContext.Provider value={{ theme, setTheme, toggle }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useLabTheme() {
  return useContext(ThemeContext) || { theme: "light", toggle: () => {}, setTheme: () => {} };
}
