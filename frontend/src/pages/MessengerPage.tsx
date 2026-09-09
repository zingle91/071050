import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, wsUrl } from "../api/client";
import type { Employee, Message, Note, Room } from "../api/types";
import { useAuth } from "../auth";

type Tab = "chat" | "notes" | "org";

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
  const [noteTo, setNoteTo] = useState<number | "">("");
  const [groupName, setGroupName] = useState("");
  const [dmTarget, setDmTarget] = useState<number | "">("");
  const [status, setStatus] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

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

  useEffect(() => {
    refreshRooms().catch(console.error);
    refreshEmployees().catch(console.error);
    refreshNotes().catch(console.error);
  }, [refreshRooms, refreshEmployees, refreshNotes]);

  useEffect(() => {
    if (!activeRoomId) return;
    api<Message[]>(`/api/rooms/${activeRoomId}/messages`)
      .then(setMessages)
      .catch(console.error);

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
        }
      } catch {
        /* ignore */
      }
    };
    return () => ws.close();
  }, [activeRoomId]);

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
    if (!groupName.trim()) return;
    const room = await api<Room>("/api/rooms", {
      method: "POST",
      body: JSON.stringify({
        name: groupName,
        room_type: "group",
        member_ids: employees.filter((e) => !e.is_bot && e.id !== user?.id).map((e) => e.id),
      }),
    });
    setGroupName("");
    await refreshRooms();
    setActiveRoomId(room.id);
    setStatus("그룹 채팅방이 생성되었습니다");
  }

  async function createDm() {
    if (!dmTarget) return;
    const room = await api<Room>("/api/rooms", {
      method: "POST",
      body: JSON.stringify({
        name: "1:1",
        room_type: "direct",
        member_ids: [Number(dmTarget)],
      }),
    });
    setDmTarget("");
    await refreshRooms();
    setActiveRoomId(room.id);
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

  async function sendNote() {
    if (!noteTo || !noteBody.trim()) return;
    await api<Note>("/api/notes", {
      method: "POST",
      body: JSON.stringify({
        recipient_id: Number(noteTo),
        subject: noteSubject,
        content: noteBody,
      }),
    });
    setNoteSubject("");
    setNoteBody("");
    setNoteTo("");
    await refreshNotes();
    setStatus("쪽지를 보냈습니다");
  }

  async function markRead(id: number) {
    await api<Note>(`/api/notes/${id}/read`, { method: "POST" });
    await refreshNotes();
  }

  const humans = employees.filter((e) => !e.is_bot);

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
            {rooms.map((r) => (
              <button
                key={r.id}
                className={r.id === activeRoomId ? "room active" : "room"}
                onClick={() => setActiveRoomId(r.id)}
              >
                <span>{r.room_type === "direct" ? "1:1" : "그룹"}</span>
                <strong>{r.name}</strong>
              </button>
            ))}
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
                <input placeholder="그룹 이름" value={groupName} onChange={(e) => setGroupName(e.target.value)} />
                <button onClick={createGroup}>그룹 만들기</button>
              </div>
              <div className="create-row">
                <select value={dmTarget} onChange={(e) => setDmTarget(e.target.value ? Number(e.target.value) : "")}>
                  <option value="">1:1 상대 선택</option>
                  {humans.filter((e) => e.id !== user?.id).map((e) => (
                    <option key={e.id} value={e.id}>{e.name} ({e.employee_id})</option>
                  ))}
                </select>
                <button onClick={createDm}>1:1 시작</button>
                <button onClick={inviteBot} disabled={!activeRoomId}>AI 봇 초대</button>
              </div>
            </div>

            {activeRoom ? (
              <>
                <header className="chat-header">
                  <h2>{activeRoom.name}</h2>
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
              <select value={noteTo} onChange={(e) => setNoteTo(e.target.value ? Number(e.target.value) : "")}>
                <option value="">수신자 선택</option>
                {humans.filter((e) => e.id !== user?.id).map((e) => (
                  <option key={e.id} value={e.id}>{e.name} ({e.employee_id})</option>
                ))}
              </select>
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
            <h2>조직도 / 직원 목록</h2>
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
    </div>
  );
}
