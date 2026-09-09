import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, userWsUrl, wsUrl } from "../api/client";
import type { Employee, Message, Note, Room } from "../api/types";
import { formatUnread, roomTitle } from "../api/types";
import { useAuth } from "../auth";
import OrgUserPicker, { type PickedUser } from "../components/OrgUserPicker";

type Tab = "chat" | "notes" | "org";
/** Shared OrgUserPicker open modes — one component + one open flow (setPickerMode). */
type PickerMode = "dm" | "group" | "note" | "invite" | null;

export default function MessengerPage() {
  const { user, logout } = useAuth();
  const [tab, setTab] = useState<Tab>("chat");
  const [rooms, setRooms] = useState<Room[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [activeRoomId, setActiveRoomId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [inbox, setInbox] = useState<Note[]>([]);
  const [sentNotes, setSentNotes] = useState<Note[]>([]);
  const [noteSubject, setNoteSubject] = useState("");
  const [noteBody, setNoteBody] = useState("");
  const [noteRecipients, setNoteRecipients] = useState<PickedUser[]>([]);
  const [groupName, setGroupName] = useState("");
  const [groupMembers, setGroupMembers] = useState<PickedUser[]>([]);
  const [status, setStatus] = useState("");
  const [pickerMode, setPickerMode] = useState<PickerMode>(null);
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameValue, setRenameValue] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const userWsRef = useRef<WebSocket | null>(null);
  const activeRoomIdRef = useRef<number | null>(null);

  useEffect(() => {
    activeRoomIdRef.current = activeRoomId;
  }, [activeRoomId]);

  /** Single shared entry to open OrgUserPicker for every flow. */
  const openEmployeePicker = useCallback((mode: Exclude<PickerMode, null>) => {
    setPickerMode(mode);
  }, []);

  const activeRoom = useMemo(
    () => rooms.find((r) => r.id === activeRoomId) || null,
    [rooms, activeRoomId]
  );

  const refreshRooms = useCallback(async () => {
    const data = await api<Room[]>("/api/rooms");
    setRooms(data);
    if (!activeRoomId && data.length) setActiveRoomId(data[0].id);
  }, [activeRoomId]);

  const refreshEmployees = useCallback(async () => {
    setEmployees(await api<Employee[]>("/api/org/employees"));
  }, []);

  const refreshNotes = useCallback(async () => {
    const [a, b] = await Promise.all([
      api<Note[]>("/api/notes/inbox"),
      api<Note[]>("/api/notes/sent"),
    ]);
    setInbox(a);
    setSentNotes(b);
  }, []);

  const markRoomRead = useCallback(async (roomId: number) => {
    try {
      const updated = await api<Room>(`/api/rooms/${roomId}/read`, { method: "POST" });
      setRooms((prev) => prev.map((r) => (r.id === updated.id ? { ...r, ...updated, unread_count: 0 } : r)));
    } catch (e) {
      console.error(e);
    }
  }, []);

  useEffect(() => {
    refreshRooms().catch(console.error);
    refreshEmployees().catch(console.error);
    refreshNotes().catch(console.error);
  }, [refreshRooms, refreshEmployees, refreshNotes]);

  // Personal WebSocket: bump unread for rooms that are not currently open
  useEffect(() => {
    if (!user) return;
    userWsRef.current?.close();
    const ws = new WebSocket(userWsUrl());
    userWsRef.current = ws;
    ws.onmessage = (ev) => {
      try {
        const payload = JSON.parse(ev.data);
        if (payload.type !== "message" || !payload.data) return;
        const msg = payload.data as Message;
        const viewing = activeRoomIdRef.current;
        if (viewing === msg.room_id) {
          // Active room: treat as read; keep badge at 0 and advance last-read
          setRooms((prev) =>
            prev.map((r) => (r.id === msg.room_id ? { ...r, unread_count: 0 } : r))
          );
          markRoomRead(msg.room_id).catch(console.error);
          return;
        }
        if (msg.sender_id === user.id) return;
        setRooms((prev) =>
          prev.map((r) =>
            r.id === msg.room_id
              ? { ...r, unread_count: (r.unread_count || 0) + 1 }
              : r
          )
        );
      } catch {
        /* ignore */
      }
    };
    ws.onopen = () => {
      const ping = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send("ping");
      }, 25000);
      ws.addEventListener("close", () => clearInterval(ping));
    };
    return () => ws.close();
  }, [user, markRoomRead]);

  useEffect(() => {
    if (!activeRoomId) return;
    api<Message[]>(`/api/rooms/${activeRoomId}/messages`)
      .then(setMessages)
      .catch(console.error);

    // Clear unread when opening a room
    markRoomRead(activeRoomId).catch(console.error);

    wsRef.current?.close();
    const ws = new WebSocket(wsUrl(activeRoomId));
    wsRef.current = ws;
    ws.onmessage = (ev) => {
      try {
        const payload = JSON.parse(ev.data);
        if (payload.type === "message") {
          setMessages((prev) => {
            if (prev.some((m) => m.id === payload.data.id)) return prev;
            return [...prev, payload.data];
          });
          // Still viewing this room → keep read
          setRooms((prev) =>
            prev.map((r) => (r.id === activeRoomId ? { ...r, unread_count: 0 } : r))
          );
        }
      } catch {
        /* ignore */
      }
    };
    return () => ws.close();
  }, [activeRoomId, markRoomRead]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function sendMessage() {
    if (!activeRoomId || !text.trim()) return;
    const content = text;
    setText("");
    try {
      const msg = await api<Message>(`/api/rooms/${activeRoomId}/messages`, {
        method: "POST",
        body: JSON.stringify({ content }),
      });
      setMessages((prev) => (prev.some((m) => m.id === msg.id) ? prev : [...prev, msg]));
    } catch (e) {
      setStatus(e instanceof Error ? e.message : "전송 실패");
    }
  }

  async function createGroup() {
    if (!groupName.trim()) {
      setStatus("그룹 이름을 입력하세요");
      return;
    }
    if (!groupMembers.length) {
      openEmployeePicker("group");
      return;
    }
    const room = await api<Room>("/api/rooms", {
      method: "POST",
      body: JSON.stringify({
        name: groupName,
        room_type: "group",
        member_ids: groupMembers.map((m) => m.id),
      }),
    });
    setGroupName("");
    setGroupMembers([]);
    await refreshRooms();
    setActiveRoomId(room.id);
    setStatus("그룹 채팅방이 생성되었습니다");
  }

  /**
   * Chat start from 직원 선택:
   * - 1 person → create/open 1:1 (direct)
   * - 2+ people → create group room with those members (auto name)
   */
  async function startChatWith(users: PickedUser[]) {
    if (!users.length) return;
    if (users.length === 1) {
      const target = users[0];
      const room = await api<Room>("/api/rooms", {
        method: "POST",
        body: JSON.stringify({
          name: "1:1",
          room_type: "direct",
          member_ids: [target.id],
        }),
      });
      await refreshRooms();
      setActiveRoomId(room.id);
      setStatus(`${target.name}님과 1:1 채팅을 시작합니다`);
      return;
    }
    const preview = users
      .slice(0, 3)
      .map((u) => u.name)
      .join(", ");
    const name =
      users.length > 3 ? `${preview} 외 ${users.length - 3}명` : preview;
    const room = await api<Room>("/api/rooms", {
      method: "POST",
      body: JSON.stringify({
        name,
        room_type: "group",
        member_ids: users.map((u) => u.id),
      }),
    });
    await refreshRooms();
    setActiveRoomId(room.id);
    setTab("chat");
    setStatus(`그룹 채팅방(${users.length}명)을 만들었습니다`);
  }

  async function inviteBot() {
    if (!activeRoomId) return;
    const room = await api<Room>("/api/rooms/invite-bot", {
      method: "POST",
      body: JSON.stringify({ room_id: activeRoomId }),
    });
    setRooms((prev) => prev.map((r) => (r.id === room.id ? room : r)));
    setStatus("AI 봇을 초대했습니다. 메시지에 @AI 를 포함하거나 ? 로 시작하면 답합니다.");
  }

  async function inviteMembers(users: PickedUser[]) {
    if (!activeRoomId || !users.length) return;
    const room = await api<Room>(`/api/rooms/${activeRoomId}/members`, {
      method: "POST",
      body: JSON.stringify({ member_ids: users.map((u) => u.id) }),
    });
    setRooms((prev) => prev.map((r) => (r.id === room.id ? room : r)));
    setStatus(`${users.length}명을 초대했습니다`);
  }

  async function sendNote() {
    if (!noteRecipients.length) {
      openEmployeePicker("note");
      return;
    }
    if (!noteBody.trim()) {
      setStatus("쪽지 내용을 입력하세요");
      return;
    }
    const recipients = [...noteRecipients];
    for (const r of recipients) {
      await api<Note>("/api/notes", {
        method: "POST",
        body: JSON.stringify({
          recipient_id: r.id,
          subject: noteSubject,
          content: noteBody,
        }),
      });
    }
    setNoteSubject("");
    setNoteBody("");
    setNoteRecipients([]);
    await refreshNotes();
    setStatus(`쪽지를 ${recipients.length}명에게 보냈습니다`);
  }

  async function markRead(id: number) {
    await api<Note>(`/api/notes/${id}/read`, { method: "POST" });
    await refreshNotes();
  }

  function openRenameDialog() {
    if (!activeRoom) return;
    setRenameValue(activeRoom.display_name || "");
    setRenameOpen(true);
  }

  async function saveDisplayName(clear = false) {
    if (!activeRoomId) return;
    try {
      const body = clear ? { display_name: null } : { display_name: renameValue.trim() || null };
      const room = await api<Room>(`/api/rooms/${activeRoomId}/display-name`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      setRooms((prev) => prev.map((r) => (r.id === room.id ? { ...r, ...room } : r)));
      setRenameOpen(false);
      setStatus(clear || !renameValue.trim() ? "기본 채팅방 이름으로 복원했습니다" : "채팅방 이름을 저장했습니다");
    } catch (e) {
      setStatus(e instanceof Error ? e.message : "이름 저장 실패");
    }
  }

  function handlePickerConfirm(users: PickedUser[]) {
    const mode = pickerMode;
    setPickerMode(null);
    if (!users.length) return;
    if (mode === "dm") {
      startChatWith(users).catch((e) => setStatus(e instanceof Error ? e.message : "실패"));
    } else if (mode === "group") {
      setGroupMembers(users);
    } else if (mode === "note") {
      setNoteRecipients(users);
    } else if (mode === "invite") {
      inviteMembers(users).catch((e) => setStatus(e instanceof Error ? e.message : "실패"));
    }
  }

  const pickerExclude = useMemo(() => {
    const ids = [user?.id].filter(Boolean) as number[];
    if (pickerMode === "invite" && activeRoom) {
      for (const m of activeRoom.members) ids.push(m.employee_id);
    }
    return ids;
  }, [user?.id, pickerMode, activeRoom]);

  const includeBots = pickerMode === "invite";

  const confirmLabel =
    pickerMode === "dm"
      ? "시작"
      : pickerMode === "invite"
        ? "초대"
        : pickerMode === "note"
          ? "수신자 확정"
          : "선택 완료";

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <strong>기업 메신저</strong>
          <div className="muted small">
            {user?.name} ({user?.employee_id})
          </div>
        </div>
        <nav className="tabs">
          <button className={tab === "chat" ? "active" : ""} onClick={() => setTab("chat")}>채팅</button>
          <button className={tab === "notes" ? "active" : ""} onClick={() => setTab("notes")}>쪽지</button>
          <button className={tab === "org" ? "active" : ""} onClick={() => setTab("org")}>조직도</button>
        </nav>
        {tab === "chat" && (
          <div className="room-list">
            {rooms.map((r) => {
              const badge = formatUnread(r.unread_count);
              return (
                <button
                  key={r.id}
                  className={r.id === activeRoomId ? "room active" : "room"}
                  onClick={() => setActiveRoomId(r.id)}
                >
                  <span className="room-row-top">
                    <span className="room-type">{r.room_type === "direct" ? "1:1" : "그룹"}</span>
                    {badge && <span className="unread-badge">{badge}</span>}
                  </span>
                  <strong>{roomTitle(r)}</strong>
                </button>
              );
            })}
          </div>
        )}
        <button className="logout" onClick={logout}>로그아웃</button>
      </aside>

      <main className="main">
        {status && <div className="banner" onClick={() => setStatus("")}>{status}</div>}

        {tab === "chat" && (
          <div className="chat-layout">
            <div className="chat-toolbar">
              <div className="create-row">
                <input
                  placeholder="그룹 이름"
                  value={groupName}
                  onChange={(e) => setGroupName(e.target.value)}
                />
                <button type="button" className="secondary" onClick={() => openEmployeePicker("group")}>
                  직원 선택{groupMembers.length ? ` (${groupMembers.length})` : ""}
                </button>
                <button type="button" onClick={createGroup}>그룹 만들기</button>
              </div>
              {groupMembers.length > 0 && (
                <div className="picked-chips">
                  {groupMembers.map((m) => (
                    <span key={m.id} className="chip">{m.name}</span>
                  ))}
                </div>
              )}
              <div className="create-row">
                <button
                  type="button"
                  title="1명 선택 시 1:1, 여러 명 선택 시 그룹 채팅"
                  onClick={() => openEmployeePicker("dm")}
                >
                  직원 선택
                </button>
                <button
                  type="button"
                  className="secondary"
                  title="현재 그룹 채팅방에 멤버 초대"
                  onClick={() => openEmployeePicker("invite")}
                  disabled={!activeRoomId || activeRoom?.room_type === "direct"}
                >
                  직원 선택
                </button>
                <button type="button" onClick={inviteBot} disabled={!activeRoomId}>AI 봇 초대</button>
              </div>
            </div>

            {activeRoom ? (
              <>
                <header className="chat-header">
                  <div className="chat-header-title">
                    <h2>{roomTitle(activeRoom)}</h2>
                    <button
                      type="button"
                      className="icon-edit-btn"
                      title="채팅방 이름 편집 (나만 보임)"
                      aria-label="채팅방 이름 편집"
                      onClick={openRenameDialog}
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <path d="M12 20h9" />
                        <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
                      </svg>
                    </button>
                  </div>
                  <div className="muted small">
                    참여자: {activeRoom.members.map((m) => m.employee.name).join(", ")}
                  </div>
                </header>
                <div className="messages">
                  {messages.map((m) => (
                    <div key={m.id} className={m.sender_id === user?.id ? "msg mine" : "msg"}>
                      <div className="meta">
                        {m.sender?.name || m.sender_id}
                        {m.sender?.is_bot ? " 🤖" : ""} · {new Date(m.created_at).toLocaleString()}
                      </div>
                      <div className="bubble">{m.content}</div>
                    </div>
                  ))}
                  <div ref={bottomRef} />
                </div>
                <div className="composer">
                  <input
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    placeholder="메시지 입력 (@AI 또는 ?로 AI 호출)"
                    onKeyDown={(e) => e.key === "Enter" && sendMessage()}
                  />
                  <button onClick={sendMessage}>전송</button>
                </div>
              </>
            ) : (
              <div className="center">채팅방을 선택하거나 새로 만드세요</div>
            )}
          </div>
        )}

        {tab === "notes" && (
          <div className="notes-layout">
            <section>
              <h2>쪽지 보내기</h2>
              <button type="button" className="secondary" onClick={() => openEmployeePicker("note")}>
                직원 선택
                {noteRecipients.length ? ` · ${noteRecipients.length}명` : ""}
              </button>
              {noteRecipients.length > 0 && (
                <div className="picked-chips">
                  {noteRecipients.map((m) => (
                    <span key={m.id} className="chip">{m.name}</span>
                  ))}
                </div>
              )}
              <input placeholder="제목" value={noteSubject} onChange={(e) => setNoteSubject(e.target.value)} />
              <textarea placeholder="내용" value={noteBody} onChange={(e) => setNoteBody(e.target.value)} rows={4} />
              <button onClick={sendNote}>보내기</button>
            </section>
            <section>
              <h2>받은 쪽지</h2>
              {inbox.map((n) => (
                <div key={n.id} className={n.is_read ? "note" : "note unread"}>
                  <strong>{n.subject}</strong>
                  <div className="muted small">from {n.sender?.name} · {new Date(n.created_at).toLocaleString()}</div>
                  <p>{n.content}</p>
                  {!n.is_read && <button onClick={() => markRead(n.id)}>읽음</button>}
                </div>
              ))}
            </section>
            <section>
              <h2>보낸 쪽지</h2>
              {sentNotes.map((n) => (
                <div key={n.id} className="note">
                  <strong>{n.subject}</strong>
                  <div className="muted small">to {n.recipient?.name} · {new Date(n.created_at).toLocaleString()}</div>
                  <p>{n.content}</p>
                </div>
              ))}
            </section>
          </div>
        )}

        {tab === "org" && (
          <div className="org-layout">
            <div className="org-layout-head">
              <h2>조직도 / 직원 목록</h2>
              <button type="button" className="secondary" onClick={() => openEmployeePicker("dm")}>
                직원 선택
              </button>
            </div>
            <table>
              <thead>
                <tr>
                  <th>사번</th>
                  <th>이름</th>
                  <th>부서</th>
                  <th>구분</th>
                </tr>
              </thead>
              <tbody>
                {employees.map((e) => (
                  <tr key={e.id}>
                    <td>{e.employee_id}</td>
                    <td>{e.name}</td>
                    <td>{e.department?.name || "-"}</td>
                    <td>{e.is_bot ? "AI 봇" : "직원"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>

      <OrgUserPicker
        open={pickerMode !== null}
        title="직원 선택"
        confirmLabel={confirmLabel}
        excludeIds={pickerExclude}
        includeBots={includeBots}
        initialSelectedIds={
          pickerMode === "group"
            ? groupMembers.map((m) => m.id)
            : pickerMode === "note"
              ? noteRecipients.map((m) => m.id)
              : []
        }
        onClose={() => setPickerMode(null)}
        onConfirm={handlePickerConfirm}
      />

      {renameOpen && activeRoom && (
        <div className="modal-overlay" onClick={() => setRenameOpen(false)}>
          <div className="rename-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-labelledby="rename-title">
            <div className="rename-modal-header">
              <h2 id="rename-title">채팅방 이름 설정</h2>
              <button type="button" className="ghost" onClick={() => setRenameOpen(false)} aria-label="닫기">✕</button>
            </div>
            <p className="muted small rename-hint">
              이 이름은 나에게만 보입니다. 비우거나 「기본값으로」를 누르면 원래 제목(
              {activeRoom.name})으로 돌아갑니다.
            </p>
            <label className="rename-label">
              내 채팅방 이름
              <input
                autoFocus
                value={renameValue}
                onChange={(e) => setRenameValue(e.target.value)}
                placeholder="나만 보이는 이름"
                maxLength={200}
                onKeyDown={(e) => e.key === "Enter" && saveDisplayName(false)}
              />
            </label>
            <div className="rename-actions">
              <button type="button" className="secondary" onClick={() => saveDisplayName(true)}>
                기본값으로
              </button>
              <div className="rename-actions-right">
                <button type="button" className="secondary" onClick={() => setRenameOpen(false)}>취소</button>
                <button type="button" onClick={() => saveDisplayName(false)}>저장</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
