import { createContext, useContext, useState } from "react";
import { toast } from "sonner";
import { useAuth } from "../AuthContext.jsx";
import { Button, Field, Modal } from "./ui.jsx";

const LabAuthContext = createContext(null);

export function useLabAuth() {
  return useContext(LabAuthContext) || { openAuth: () => {} };
}

function AuthForm({ initialMode, onClose }) {
  const { login, register } = useAuth();
  const [mode, setMode] = useState(initialMode || "login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const action = mode === "login" ? login : register;
      const user = await action(username.trim(), password);
      toast.success(mode === "login" ? `欢迎回来，${user.nickname || user.username}` : "账号已创建");
      onClose();
    } catch (e) {
      setError(e.message || "操作失败，请重试");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div className="lab-auth-tabs">
        <button type="button" className={mode === "login" ? "is-active" : ""} onClick={() => setMode("login")}>
          登录
        </button>
        <button type="button" className={mode === "register" ? "is-active" : ""} onClick={() => setMode("register")}>
          注册
        </button>
      </div>
      <Field label="用户名" hint="3–24 个字符">
        <input
          className="lab-input"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          minLength={3}
          maxLength={24}
          required
        />
      </Field>
      <Field label="密码" hint="至少 8 位">
        <input
          className="lab-input"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          minLength={8}
          maxLength={128}
          required
        />
      </Field>
      {error ? <div className="lab-form-error">{error}</div> : null}
      <div className="lab-modal__actions">
        <Button variant="ghost" onClick={onClose} type="button">
          取消
        </Button>
        <Button variant="primary" type="submit" disabled={busy}>
          {busy ? "处理中…" : mode === "login" ? "登录" : "创建账号"}
        </Button>
      </div>
      <p className="lab-mono" style={{ letterSpacing: 0, lineHeight: 1.6 }}>
        登录后可托管 ONNX 模型、查看对局记录与发起模型挑战。游客可直接试玩环境。
      </p>
    </form>
  );
}

export function LabAuthProvider({ children }) {
  const [state, setState] = useState({ open: false, mode: "login" });
  const openAuth = (mode = "login") => setState({ open: true, mode });
  const close = () => setState((s) => ({ ...s, open: false }));
  return (
    <LabAuthContext.Provider value={{ openAuth }}>
      {children}
      {state.open ? (
        <Modal title={state.mode === "login" ? "登录 Stream" : "创建 Stream 账号"} onClose={close}>
          <AuthForm initialMode={state.mode} onClose={close} />
        </Modal>
      ) : null}
    </LabAuthContext.Provider>
  );
}
