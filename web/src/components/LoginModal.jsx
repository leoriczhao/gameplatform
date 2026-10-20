import { useState } from "react";
import { toast } from "sonner";
import { LogInIcon, UserPlusIcon } from "lucide-react";
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from "./ui/dialog.jsx";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "./ui/tabs.jsx";
import { Button } from "./ui/button.jsx";
import { Input } from "./ui/input.jsx";
import { Label } from "./ui/label.jsx";
import { useAuth } from "../AuthContext.jsx";

const USERNAME_RE = /^[a-zA-Z0-9_]{3,24}$/;

export default function LoginModal({ open, onClose }) {
  const { login, register } = useAuth();
  const [tab, setTab] = useState("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const reset = () => {
    setError("");
    setUsername("");
    setPassword("");
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!USERNAME_RE.test(username)) {
      setError("用户名需为 3-24 位字母/数字/下划线");
      return;
    }
    if (password.length < 8) {
      setError("密码至少 8 位");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const user = tab === "login"
        ? await login(username, password)
        : await register(username, password);
      toast.success(`欢迎，${user.nickname || user.username}!`);
      reset();
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onClose(); }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="gradient-text">欢迎来到 Stream</DialogTitle>
          <DialogDescription>登录后可使用会话对战、模型托管与好友系统</DialogDescription>
        </DialogHeader>
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="login"><LogInIcon /> 登录</TabsTrigger>
            <TabsTrigger value="register"><UserPlusIcon /> 注册</TabsTrigger>
          </TabsList>
          <TabsContent value="login" />
          <TabsContent value="register" />
        </Tabs>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="login-username">用户名</Label>
            <Input
              id="login-username"
              autoFocus
              autoComplete="username"
              placeholder="3-24 位字母/数字/下划线"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="login-password">密码</Label>
            <Input
              id="login-password"
              type="password"
              autoComplete={tab === "login" ? "current-password" : "new-password"}
              placeholder="至少 8 位"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {error ? <p className="text-sm text-red-600">{error}</p> : null}
          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? "处理中…" : tab === "login" ? "登录" : "注册并登录"}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
