import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, wsUrl } from "../api/client";
import type { Employee, Message, Note, Room } from "../api/types";
import { useAuth } from "../auth";
import OrgUserPicker, { type PickedUser } from "../components/OrgUserPicker";

type Tab = "chat" | "notes" | "org";
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
    if (!groupName.trim()) {
      setStatus("그룹 이름을 입력하세요");
      return;
    }
    if (!groupMembers.length) {
      setPickerMode("group");
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

  async function createDmWith(users: PickedUser[]) {
    if (!users.length) return;
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
      setPickerMode("note");
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

  function handlePickerConfirm(users: PickedUser[]) {
    const mode = pickerMode;
    setPickerMode(null);
    if (!users.length) return;
    if (mode === "dm") {
      createDmWith(users).catch((e) => setStatus(e instanceof Error ? e.message : "실패"));
    } else if (mode === "group") {
      setGroupMembers(users);
    } else if (mode === "note") {
      setNoteRecipients(users);
    } else if (mode === "invite") {
      inviteMembers(users).catch((e) => setStatus(e instanceof Error ? e.message : "실패"));
    }
  }

  const pickerTitle =
    pickerMode === "dm"
      ? "1:1 상대 선택"
      : pickerMode === "group"
        ? "그룹 멤버 선택"
        : pickerMode === "note"
          ? "쪽지 수신자 선택"
          : pickerMode === "invite"
            ? "멤버 초대"
            : "회사 조직도";

  const pickerMax =
    pickerMode === "dm" ? 1 : undefined;

  const pickerExclude = useMemo(() => {
    const ids = [user?.id].filter(Boolean) as number[];
    if (pickerMode === "invite" && activeRoom) {
      for (const m of activeRoom.members) ids.push(m.employee_id);
    }
    return ids;
  }, [user?.id, pickerMode, activeRoom]);

  const includeBots = pickerMode === "invite";

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
                <input
                  placeholder="그룹 이름"
                  value={groupName}
                  onChange={(e) => setGroupName(e.target.value)}
                />
                <button type="button" className="secondary" onClick={() => setPickerMode("group")}>
                  멤버 선택{groupMembers.length ? ` (${groupMembers.length})` : ""}
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
                <button type="button" onClick={() => setPickerMode("dm")}>1:1 시작 (조직도)</button>
                <button
                  type="button"
                  onClick={() => setPickerMode("invite")}
                  disabled={!activeRoomId || activeRoom?.room_type === "direct"}
                >
                  멤버 초대
                </button>
                <button type="button" onClick={inviteBot} disabled={!activeRoomId}>AI 봇 초대</button>
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
              <button type="button" className="secondary" onClick={() => setPickerMode("note")}>
                수신자 선택 (조직도)
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
              <button type="button" className="secondary" onClick={() => setPickerMode("dm")}>
                조직도에서 선택
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
        title={pickerTitle}
        confirmLabel={
          pickerMode === "dm"
            ? "1:1 시작"
            : pickerMode === "invite"
              ? "초대"
              : pickerMode === "note"
                ? "수신자 확정"
                : "선택 완료"
        }
        maxSelect={pickerMax}
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
    </div>
  );
}
