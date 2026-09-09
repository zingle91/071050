import { useEffect, useRef } from "react";
import { userWsUrl } from "../api/client";

const PING_MS = 25000;
const BACKOFF_START_MS = 800;
const BACKOFF_MAX_MS = 20000;

export type RealtimePayload = {
  type: string;
  data?: unknown;
  room_id?: number;
  unread_delta?: number;
  user_id?: number;
  last_read_at?: string | null;
  action?: string;
  actor_id?: number;
  removed_ids?: number[];
  room?: unknown;
  removed_rooms?: Record<string, unknown>;
  system_messages?: unknown[];
  /** Notes unread badge sync */
  unread_count?: number;
};

/**
 * One persistent /ws/user connection per logged-in user.
 * Reconnects with exponential backoff; lightweight ping keepalive.
 */
export function useUserRealtime(
  enabled: boolean,
  onEvent: (payload: RealtimePayload) => void
) {
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    if (!enabled) return;

    let closed = false;
    let ws: WebSocket | null = null;
    let pingTimer: ReturnType<typeof setInterval> | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;

    const clearPing = () => {
      if (pingTimer) {
        clearInterval(pingTimer);
        pingTimer = null;
      }
    };

    const clearReconnect = () => {
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };

    const scheduleReconnect = () => {
      if (closed) return;
      clearReconnect();
      const delay = Math.min(BACKOFF_MAX_MS, BACKOFF_START_MS * 2 ** attempt);
      attempt += 1;
      reconnectTimer = setTimeout(connect, delay);
    };

    const connect = () => {
      if (closed) return;
      clearPing();
      try {
        ws?.close();
      } catch {
        /* ignore */
      }

      let socket: WebSocket;
      try {
        socket = new WebSocket(userWsUrl());
      } catch {
        scheduleReconnect();
        return;
      }
      ws = socket;

      socket.onopen = () => {
        attempt = 0;
        clearPing();
        pingTimer = setInterval(() => {
          if (socket.readyState === WebSocket.OPEN) {
            try {
              socket.send("ping");
            } catch {
              /* ignore */
            }
          }
        }, PING_MS);
      };

      socket.onmessage = (ev) => {
        try {
          const payload = JSON.parse(ev.data) as RealtimePayload;
          if (payload?.type === "pong") return;
          onEventRef.current(payload);
        } catch {
          /* ignore non-JSON */
        }
      };

      socket.onerror = () => {
        /* onclose handles reconnect */
      };

      socket.onclose = () => {
        clearPing();
        if (ws === socket) ws = null;
        scheduleReconnect();
      };
    };

    connect();

    return () => {
      closed = true;
      clearPing();
      clearReconnect();
      try {
        ws?.close();
      } catch {
        /* ignore */
      }
      ws = null;
    };
  }, [enabled]);
}
