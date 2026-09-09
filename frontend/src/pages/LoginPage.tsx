import { FormEvent, useState } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth";

export default function LoginPage() {
  const { user, login } = useAuth();
  const [employeeId, setEmployeeId] = useState("E001");
  const [password, setPassword] = useState("password123");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/" replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(employeeId.trim(), password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "로그인 실패");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={onSubmit}>
        <h1>기업 메신저</h1>
        <p className="muted">사번과 비밀번호로 로그인하세요</p>
        <label>
          사번
          <input
            value={employeeId}
            onChange={(e) => setEmployeeId(e.target.value)}
            placeholder="예: E001"
            autoFocus
          />
        </label>
        <label>
          비밀번호
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && <div className="error">{error}</div>}
        <button type="submit" disabled={busy}>
          {busy ? "로그인 중..." : "로그인"}
        </button>
        <div className="hint">
          데모 계정: E001~E004 / password123
        </div>
      </form>
    </div>
  );
}
