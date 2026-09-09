const TOKEN_KEY = "messenger_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export async function api<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const headers = new Headers(options.headers || {});
  if (!headers.has("Content-Type") && options.body) {
    headers.set("Content-Type", "application/json");
  }
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(path, { ...options, headers });
  if (res.status === 401) {
    setToken(null);
    if (!path.includes("/auth/login")) {
      window.location.href = "/login";
    }
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || JSON.stringify(data);
    } catch {
      /* ignore */
    }
    throw new Error(typeof detail === "string" ? detail : "요청 실패");
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

function wsBase(): { proto: string; host: string; token: string } {
  const token = getToken() || "";
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const host = window.location.host;
  return { proto, host, token };
}

export function wsUrl(roomId: number): string {
  const { proto, host, token } = wsBase();
  return `${proto}://${host}/ws/rooms/${roomId}?token=${encodeURIComponent(token)}`;
}

export function userWsUrl(): string {
  const { proto, host, token } = wsBase();
  return `${proto}://${host}/ws/user?token=${encodeURIComponent(token)}`;
}
