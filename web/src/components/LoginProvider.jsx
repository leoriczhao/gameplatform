import { createContext, useContext, useState } from "react";
import LoginModal from "./LoginModal.jsx";

const LoginContext = createContext(() => {});

/* Any page calls const openLogin = useLogin(); openLogin() to show the shared modal. */
export function useLogin() {
  return useContext(LoginContext);
}

export function LoginProvider({ children }) {
  const [open, setOpen] = useState(false);
  return (
    <LoginContext.Provider value={() => setOpen(true)}>
      {children}
      <LoginModal open={open} onClose={() => setOpen(false)} />
    </LoginContext.Provider>
  );
}
