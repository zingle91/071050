import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { Message, Note, NotesUnreadCount, OrgTreeEmployee, OrgTreeNode, Room, UnreadUser } from "../api/types";
import { computeMessageUnreadCount, formatUnread, isLeftRoom, roomTitle } from "../api/types";
import { useAuth } from "../auth";
import NoteComposeModal from "../components/NoteComposeModal";
import OrgUserPicker, { type PickedUser } from "../components/OrgUserPicker";
import { useUserRealtime, type RealtimePayload } from "../hooks/useUserRealtime";
import {
  NOTE_COMPOSE_MSG,
  readStoredComposeDraft,
  type NoteComposeDraft,
} from "../noteCompose";

type Tab = "chat" | "notes" | "org";
/** Shared OrgUserPicker open modes — one component + one open flow (setPickerMode). */
type PickerMode = "dm" | "group" | "invite" | null;

/** Sort rooms newest-activity first (API order + live WS bumps). */
function roomActivityTs(r: Room): number {
  const raw = r.last_message_at || r.created_at;
  return new Date(raw).getTime() || 0;
}

function sortRoomsByRecent(rooms: Room[]): Room[] {
  return [...rooms].sort((a, b) => roomActivityTs(b) - roomActivityTs(a));
}


/** Move a room to the top and optionally patch fields (live sidebar reorder). */
function bumpRoomToTop(prev: Room[], roomId: number, patch: Partial<Room> = {}): Room[] {
  const idx = prev.findIndex((r) => r.id === roomId);
  if (idx < 0) return prev;
  const now = patch.last_message_at || new Date().toISOString();
  const updated: Room = { ...prev[idx], ...patch, last_message_at: now };
  if (idx === 0) {
    const copy = [...prev];
    copy[0] = updated;
    return copy;
  }
  return [updated, ...prev.filter((_, i) => i !== idx)];
}

export default function MessengerPage() {
  const { user, logout } = useAuth();
  const [tab, setTab] = useState<Tab>("chat");
  const [rooms, setRooms] = useState<Room[]>([]);
  const [orgTree, setOrgTree] = useState<OrgTreeNode | null>(null);
  const [orgExpanded, setOrgExpanded] = useState<Set<string>>(new Set(["root"]));
  const [activeRoomId, setActiveRoomId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [inbox, setInbox] = useState<Note[]>([]);
  const [sentNotes, setSentNotes] = useState<Note[]>([]);
  const [notesSubTab, setNotesSubTab] = useState<"inbox" | "sent">("inbox");
  const [notesUnread, setNotesUnread] = useState(0);
  const [noteComposeOpen, setNoteComposeOpen] = useState(false);
  const [noteComposeDraft, setNoteComposeDraft] = useState<NoteComposeDraft | null>(null);
  const [groupName, setGroupName] = useState("");
  const [groupMembers, setGroupMembers] = useState<PickedUser[]>([]);
  const [status, setStatus] = useState("");
  const [pickerMode, setPickerMode] = useState<PickerMode>(null);
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameValue, setRenameValue] = useState("");
  const [unreadPopoverMsgId, setUnreadPopoverMsgId] = useState<number | null>(null);
  const [unreadUsers, setUnreadUsers] = useState<UnreadUser[]>([]);
  const [unreadLoading, setUnreadLoading] = useState(false);
  const [roomMenuOpen, setRoomMenuOpen] = useState(false);
  const [kickOpen, setKickOpen] = useState(false);
  const [kickSelected, setKickSelected] = useState<number[]>([]);
  const [historyDeleteRoomId, setHistoryDeleteRoomId] = useState<number | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const activeRoomIdRef = useRef<number | null>(null);
  const unreadPopoverRef = useRef<HTMLDivElement>(null);
  const roomMenuRef = useRef<HTMLDivElement>(null);

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
    const viewing = activeRoomIdRef.current;
    // While a room is open, keep sidebar badge at 0 even if a list refresh
    // races ahead of mark-read (stale unread_count from server).
    setRooms(
      sortRoomsByRecent(
        data.map((r) => (viewing != null && r.id === viewing ? { ...r, unread_count: 0 } : r))
      )
    );
    if (!activeRoomId && data.length) setActiveRoomId(data[0].id);
  }, [activeRoomId]);

  const refreshEmployees = useCallback(async () => {
    const tree = await api<OrgTreeNode>("/api/org/tree");
    setOrgTree(tree);
    // Keep departments collapsed; only root open
    setOrgExpanded(new Set(["root"]));
  }, []);

  const refreshNotes = useCallback(async () => {
    const [a, b, u] = await Promise.all([
      api<Note[]>("/api/notes/inbox"),
      api<Note[]>("/api/notes/sent"),
      api<NotesUnreadCount>("/api/notes/unread-count"),
    ]);
    setInbox(a);
    setSentNotes(b);
    setNotesUnread(u.count || 0);
  }, []);

  const refreshNotesUnread = useCallback(async () => {
    try {
      const u = await api<NotesUnreadCount>("/api/notes/unread-count");
      setNotesUnread(u.count || 0);
    } catch (e) {
      console.error(e);
    }
  }, []);

  const markRoomRead = useCallback(async (roomId: number) => {
    // Optimistic clear only while this room is still the center view.
    if (activeRoomIdRef.current === roomId) {
      setRooms((prev) =>
        prev.map((r) => (r.id === roomId ? { ...r, unread_count: 0 } : r))
      );
    }
    try {
      const updated = await api<Room>(`/api/rooms/${roomId}/read`, { method: "POST" });
      setRooms((prev) =>
        prev.map((r) => {
          if (r.id !== updated.id) return r;
          // Still viewing: force badge 0 (active-room messages must not count).
          if (activeRoomIdRef.current === updated.id) {
            return {
              ...r,
              ...updated,
              unread_count: 0,
              display_name: updated.display_name ?? r.display_name,
            };
          }
          // User left this room before POST returned: do NOT clobber newer WS bumps
          // with the stale unread_count:0 from this mark-read response.
          return {
            ...r,
            members: updated.members ?? r.members,
            last_message_at: updated.last_message_at ?? r.last_message_at,
            membership_status: updated.membership_status ?? r.membership_status,
            unread_count: r.unread_count,
            display_name: r.display_name,
          };
        })
      );
    } catch (e) {
      console.error(e);
    }
  }, []);

  useEffect(() => {
    refreshRooms().catch(console.error);
    refreshEmployees().catch(console.error);
    refreshNotes().catch(console.error);
  }, [refreshRooms, refreshEmployees, refreshNotes]);

  // Single user-level WebSocket: center append + sidebar unread + read receipts
  const onRealtime = useCallback(
    (payload: RealtimePayload) => {
      if (!user) return;

      if (payload.type === "note") {
        const count = typeof payload.unread_count === "number" ? payload.unread_count : null;
        if (count != null) setNotesUnread(count);
        const note = payload.data as Note | undefined;
        if (payload.action === "received" && note) {
          setInbox((prev) => (prev.some((n) => n.id === note.id) ? prev : [note, ...prev]));
        }
        if (payload.action === "read" && note) {
          setInbox((prev) => prev.map((n) => (n.id === note.id ? { ...n, ...note } : n)));
        }
        if (count == null) {
          queueMicrotask(() => {
            refreshNotesUnread().catch(console.error);
          });
        }
        return;
      }

      if (payload.type === "membership_change") {
        const roomId = payload.room_id;
        const removed = payload.removed_ids || [];
        if (roomId == null) return;

        if (payload.action === "dismiss_history" && removed.includes(user.id)) {
          setRooms((prev) => prev.filter((r) => r.id !== roomId));
          if (activeRoomIdRef.current === roomId) {
            setActiveRoomId(null);
            setMessages([]);
          }
          return;
        }

        const iWasRemoved = removed.includes(user.id);
        if (iWasRemoved) {
          const removedRooms = (payload.removed_rooms || {}) as Record<string, Room>;
          const myRoom = removedRooms[String(user.id)];
          setRooms((prev) => {
            const idx = prev.findIndex((r) => r.id === roomId);
            const nextRoom: Room = myRoom
              ? { ...myRoom, unread_count: 0 }
              : {
                  ...(prev[idx] || (payload.room as Room)),
                  membership_status: payload.action === "kick" ? "kicked" : "left",
                  unread_count: 0,
                  members: (payload.room as Room | undefined)?.members || (prev[idx]?.members ?? []),
                };
            if (idx >= 0) {
              const copy = [...prev];
              copy[idx] = { ...copy[idx], ...nextRoom, id: roomId };
              return copy;
            }
            return [nextRoom, ...prev];
          });
          setRoomMenuOpen(false);
          setKickOpen(false);
          setStatus(payload.action === "kick" ? "채팅방에서 내보내졌습니다" : "채팅방에서 나갔습니다");
          // Keep history open; system message arrives via separate "message" event
          return;
        }
        const roomData = payload.room as Room | undefined | null;
        if (roomData && typeof roomData === "object" && "id" in roomData) {
          setRooms((prev) =>
            prev.map((r) =>
              r.id === roomId
                ? {
                    ...r,
                    ...roomData,
                    // keep my unread / display_name / membership if server payload used another viewer
                    unread_count: r.unread_count,
                    display_name: r.display_name,
                    membership_status: r.membership_status || "active",
                    left_at: r.left_at,
                    members: roomData.members || r.members,
                  }
                : r
            )
          );
          if (activeRoomIdRef.current === roomId && roomData.members) {
            queueMicrotask(() => {
              setMessages((msgs) =>
                msgs.map((msg) => ({
                  ...msg,
                  unread_count: msg.is_system ? 0 : computeMessageUnreadCount(msg, roomData.members),
                }))
              );
            });
          }
        } else {
          queueMicrotask(() => {
            refreshRooms().catch(console.error);
          });
        }
        return;
      }

      if (payload.type === "read_update") {
        const roomId = payload.room_id;
        const readerId = payload.user_id;
        const lastReadAt = payload.last_read_at ?? null;
        if (roomId == null || readerId == null) return;

        setRooms((prev) => {
          const next = prev.map((r) => {
            if (r.id !== roomId) return r;
            const members = r.members.map((m) =>
              m.employee_id === readerId ? { ...m, last_read_at: lastReadAt } : m
            );
            // Self mark-read / open: clear sidebar badge immediately via WS
            // (HTTP response may arrive later; avoid residual unread).
            const clearMine = readerId === user.id;
            return {
              ...r,
              members,
              unread_count: clearMine ? 0 : r.unread_count,
            };
          });
          const room = next.find((r) => r.id === roomId);
          if (room && activeRoomIdRef.current === roomId) {
            const members = room.members;
            queueMicrotask(() => {
              setMessages((msgs) =>
                msgs.map((msg) => ({
                  ...msg,
                  unread_count: computeMessageUnreadCount(msg, members),
                }))
              );
            });
          }
          return next;
        });
        return;
      }

      if (payload.type !== "message" || !payload.data) return;
      const msg = payload.data as Message;
      const roomId = msg.room_id ?? payload.room_id;
      if (roomId == null) return;
      const viewing = activeRoomIdRef.current;
      const delta = typeof payload.unread_delta === "number" ? payload.unread_delta : 1;
      const activityAt = msg.created_at || new Date().toISOString();

      if (viewing === roomId) {
        setMessages((prev) => {
          if (prev.some((m) => m.id === msg.id)) return prev;
          return [...prev, msg];
        });
        // Active center room: never increment sidebar unread; confirm with mark-read
        setRooms((prev) => bumpRoomToTop(prev, roomId, { unread_count: 0, last_message_at: activityAt }));
        if (!msg.is_system && msg.sender_id !== user.id) {
          markRoomRead(roomId).catch(console.error);
        }
        return;
      }

      // Inactive room: always reorder by latest message; unread only for others' non-system
      setRooms((prev) => {
        if (!prev.some((r) => r.id === roomId)) {
          queueMicrotask(() => {
            refreshRooms().catch(console.error);
          });
          return prev;
        }
        const room = prev.find((r) => r.id === roomId)!;
        let unread = room.unread_count || 0;
        if (
          !msg.is_system &&
          msg.sender_id !== user.id &&
          delta > 0 &&
          !isLeftRoom(room)
        ) {
          unread = unread + delta;
        }
        return bumpRoomToTop(prev, roomId, {
          unread_count: unread,
          last_message_at: activityAt,
        });
      });
    },
    [user, markRoomRead, refreshRooms, refreshNotesUnread]
  );

  useUserRealtime(!!user, onRealtime);

  // Refresh notes list + badge when opening 쪽지 tab / window
  useEffect(() => {
    if (tab !== "notes") return;
    refreshNotes().catch(console.error);
  }, [tab, refreshNotes]);

  // Compose drafts from note detail popup (postMessage) or sessionStorage fallback
  useEffect(() => {
    function onMessage(ev: MessageEvent) {
      if (ev.origin !== window.location.origin) return;
      const data = ev.data;
      if (!data || data.source !== NOTE_COMPOSE_MSG || !data.draft) return;
      applyNoteComposeDraft(data.draft as NoteComposeDraft);
    }
    window.addEventListener("message", onMessage);
    const stored = readStoredComposeDraft();
    if (stored) applyNoteComposeDraft(stored);
    return () => window.removeEventListener("message", onMessage);
  }, []);


  useEffect(() => {
    const onFocus = () => {
      refreshNotesUnread().catch(console.error);
      if (tab === "notes") refreshNotes().catch(console.error);
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [tab, refreshNotes, refreshNotesUnread]);


  useEffect(() => {
    if (!activeRoomId) return;
    setUnreadPopoverMsgId(null);
    setRoomMenuOpen(false);
    setKickOpen(false);
    // Optimistic clear as soon as center room switches (before POST /read returns)
    setRooms((prev) =>
      prev.map((r) => (r.id === activeRoomId ? { ...r, unread_count: 0 } : r))
    );
    api<Message[]>(`/api/rooms/${activeRoomId}/messages`)
      .then(setMessages)
      .catch(console.error);

    // Persist mark-read + server confirm (also drives peer read_update digits)
    markRoomRead(activeRoomId).catch(console.error);
  }, [activeRoomId, markRoomRead]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Close unread popover on outside click / Escape
  useEffect(() => {
    if (unreadPopoverMsgId == null) return;
    const onDown = (e: MouseEvent) => {
      if (unreadPopoverRef.current && !unreadPopoverRef.current.contains(e.target as Node)) {
        setUnreadPopoverMsgId(null);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setUnreadPopoverMsgId(null);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [unreadPopoverMsgId]);

  useEffect(() => {
    if (!roomMenuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (roomMenuRef.current && !roomMenuRef.current.contains(e.target as Node)) {
        setRoomMenuOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setRoomMenuOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [roomMenuOpen]);

  async function openUnreadPopover(msg: Message) {
    if (!activeRoomId || !msg.unread_count) return;
    if (unreadPopoverMsgId === msg.id) {
      setUnreadPopoverMsgId(null);
      return;
    }
    setUnreadPopoverMsgId(msg.id);
    setUnreadUsers([]);
    setUnreadLoading(true);
    try {
      const users = await api<UnreadUser[]>(
        `/api/rooms/${activeRoomId}/messages/${msg.id}/unreaders`
      );
      setUnreadUsers(users);
    } catch (e) {
      console.error(e);
      setUnreadUsers([]);
    } finally {
      setUnreadLoading(false);
    }
  }

  async function sendMessage() {
    if (!activeRoomId || !text.trim() || sending) return;
    // Composer only — never prepend/append room history or peer utterances
    const content = text.trim();
    if (content.length > 4000) {
      setStatus("메시지는 4000자를 넘을 수 없습니다");
      return;
    }
    const clientMessageId =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `c-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
    setSending(true);
    setText("");
    try {
      const msg = await api<Message>(`/api/rooms/${activeRoomId}/messages`, {
        method: "POST",
        headers: { "Idempotency-Key": clientMessageId },
        body: JSON.stringify({ content, client_message_id: clientMessageId }),
      });
      setMessages((prev) => (prev.some((m) => m.id === msg.id) ? prev : [...prev, msg]));
      setRooms((prev) =>
        bumpRoomToTop(prev, activeRoomId, {
          unread_count: 0,
          last_message_at: msg.created_at,
        })
      );
    } catch (e) {
      // Restore draft so user can retry without losing text
      setText((prev) => prev || content);
      setStatus(e instanceof Error ? e.message : "전송 실패");
    } finally {
      setSending(false);
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

  function openNoteCompose(draft: NoteComposeDraft | null = null) {
    setNoteComposeDraft(draft);
    setNoteComposeOpen(true);
  }

  function applyNoteComposeDraft(draft: NoteComposeDraft) {
    // Optional fallback: drafts from popup postMessage / sessionStorage
    openNoteCompose(draft);
    setTab("notes");
  }

  function openNoteDetail(n: Note) {
    const url = `${window.location.origin}/notes/${n.id}`;
    // Standalone resizable browser popup (no fixed size lock / no resize disable).
    const features = "popup=yes,resizable=yes,scrollbars=yes";
    const win = window.open(url, `note-detail-${n.id}`, features);
    if (!win) {
      setStatus("팝업이 차단되었습니다. 브라우저에서 팝업을 허용해 주세요.");
      return;
    }
    // Optimistic unread update; popup GET marks read and WS refreshes badge.
    if (!n.is_read) {
      setInbox((prev) =>
        prev.map((x) =>
          x.id === n.id ? { ...x, is_read: true, read_at: x.read_at || new Date().toISOString() } : x
        )
      );
      setNotesUnread((c) => Math.max(0, c - 1));
    }
    win.focus();
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

  async function leaveActiveRoom() {
    if (!activeRoomId) return;
    setRoomMenuOpen(false);
    if (!window.confirm("이 채팅방에서 나가시겠습니까?")) return;
    const roomId = activeRoomId;
    try {
      const room = await api<Room>(`/api/rooms/${roomId}/leave`, { method: "POST" });
      setRooms((prev) => prev.map((r) => (r.id === room.id ? { ...r, ...room, unread_count: 0 } : r)));
      setStatus("채팅방에서 나갔습니다");
      // Reload messages so the system line appears even if WS races
      const msgs = await api<Message[]>(`/api/rooms/${roomId}/messages`);
      setMessages(msgs);
    } catch (e) {
      setStatus(e instanceof Error ? e.message : "나가기 실패");
    }
  }

  function requestDeleteHistory(roomId: number, e?: { stopPropagation(): void; preventDefault(): void }) {
    e?.stopPropagation();
    e?.preventDefault();
    setHistoryDeleteRoomId(roomId);
  }

  async function confirmDeleteHistory() {
    const roomId = historyDeleteRoomId;
    if (roomId == null) return;
    try {
      await api(`/api/rooms/${roomId}/history`, { method: "DELETE" });
      setRooms((prev) => prev.filter((r) => r.id !== roomId));
      if (activeRoomIdRef.current === roomId) {
        setActiveRoomId(null);
        setMessages([]);
      }
      setHistoryDeleteRoomId(null);
      setStatus("채팅 이력을 삭제했습니다");
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "이력 삭제 실패");
    }
  }

  function openKickDialog() {
    setRoomMenuOpen(false);
    setKickSelected([]);
    setKickOpen(true);
  }

  async function confirmKick() {
    if (!activeRoomId || !kickSelected.length) return;
    try {
      const room = await api<Room>(`/api/rooms/${activeRoomId}/kick`, {
        method: "POST",
        body: JSON.stringify({ member_ids: kickSelected }),
      });
      setRooms((prev) => prev.map((r) => (r.id === room.id ? { ...r, ...room } : r)));
      setKickOpen(false);
      setKickSelected([]);
      setStatus(`${kickSelected.length}명을 내보냈습니다`);
      setMessages((msgs) =>
        msgs.map((msg) => ({
          ...msg,
          unread_count: msg.is_system ? 0 : computeMessageUnreadCount(msg, room.members),
        }))
      );
      // Pull latest so system notifications are present even if WS races
      const msgs = await api<Message[]>(`/api/rooms/${activeRoomId}/messages`);
      setMessages(msgs);
    } catch (e) {
      setStatus(e instanceof Error ? e.message : "내보내기 실패");
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


  function toggleOrgExpand(key: string) {
    setOrgExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function renderOrgBrowseNode(node: OrgTreeNode, depth: number) {
    const key = node.node_type === "group" ? "root" : `dept-${node.id}`;
    const isOpen = orgExpanded.has(key);
    const emps = (node.employees || []).filter((e) => !e.is_bot);
    const childCount =
      (node.children || []).length + emps.length;
    return (
      <div key={key} className="org-tree-node" style={{ marginLeft: depth ? 12 : 0 }}>
        <div className="org-tree-header">
          <button type="button" className="org-tree-toggle" onClick={() => toggleOrgExpand(key)}>
            <span className="caret">{isOpen ? "▼" : "▶"}</span>
            <strong>{node.name}</strong>
            <span className="muted small"> ({childCount})</span>
          </button>
        </div>
        {isOpen && (
          <div className="org-tree-children org-tree-vertical">
            {(node.children || []).map((c) => renderOrgBrowseNode(c, depth + 1))}
            {emps.map((e: OrgTreeEmployee) => (
              <div key={e.id} className="org-picker-row org-browse-emp">
                <span className="org-picker-name">
                  {e.name}
                  <span className="muted small"> ({e.employee_id})</span>
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  const confirmLabel =
    pickerMode === "dm"
      ? "시작"
      : pickerMode === "invite"
        ? "초대"
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
          <button className={tab === "notes" ? "active" : ""} onClick={() => setTab("notes")}>
            <span className="tab-label">
              쪽지
              {formatUnread(notesUnread) && (
                <span className="unread-badge tab-unread-badge">{formatUnread(notesUnread)}</span>
              )}
            </span>
          </button>
          <button className={tab === "org" ? "active" : ""} onClick={() => setTab("org")}>조직도</button>
        </nav>
        {tab === "chat" && (
          <div className="room-list">
            {rooms.map((r) => {
              const badge = !isLeftRoom(r) ? formatUnread(r.unread_count) : "";
              const left = isLeftRoom(r);
              const active = r.id === activeRoomId;
              return (
                <div
                  key={r.id}
                  className={
                    "room-row" +
                    (active ? " active" : "") +
                    (left ? " room-left" : "")
                  }
                >
                  <button
                    type="button"
                    className={active ? "room active" : "room"}
                    onClick={() => {
                      setActiveRoomId(r.id);
                      setRooms((prev) =>
                        prev.map((x) => (x.id === r.id ? { ...x, unread_count: 0 } : x))
                      );
                    }}
                  >
                    <span className="room-row-top">
                      <span className="room-type">{r.room_type === "direct" ? "1:1" : "그룹"}</span>
                      {left ? (
                        <span className="left-room-badge" title="방에서 나온 채팅">나감</span>
                      ) : (
                        badge && <span className="unread-badge">{badge}</span>
                      )}
                    </span>
                    <strong>{roomTitle(r)}</strong>
                    {left && <span className="left-room-label">방에서 나온 채팅</span>}
                  </button>
                  {left && (
                    <button
                      type="button"
                      className="room-dismiss-x"
                      title="채팅 이력 삭제"
                      aria-label="채팅 이력 삭제"
                      onClick={(e) => requestDeleteHistory(r.id, e)}
                    >
                      ×
                    </button>
                  )}
                </div>
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
                  disabled={!activeRoomId || activeRoom?.room_type === "direct" || isLeftRoom(activeRoom)}
                >
                  직원 선택
                </button>
                <button type="button" onClick={inviteBot} disabled={!activeRoomId || isLeftRoom(activeRoom)}>AI 봇 초대</button>
              </div>
            </div>

            {activeRoom ? (
              <>
                <header className="chat-header">
                  <div className="chat-header-main">
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
                      참여자: {activeRoom.members.map((m) => m.employee.name).join(", ") || "(없음)"}
                      {isLeftRoom(activeRoom) ? " · 방에서 나옴" : ""}
                    </div>
                  </div>
                  {!isLeftRoom(activeRoom) && (
                  <div className="chat-header-actions" ref={roomMenuRef}>
                    <button
                      type="button"
                      className="chat-menu-btn"
                      title="메뉴"
                      aria-label="채팅방 메뉴"
                      aria-expanded={roomMenuOpen}
                      onClick={() => setRoomMenuOpen((v) => !v)}
                    >
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                        <circle cx="12" cy="5" r="2" />
                        <circle cx="12" cy="12" r="2" />
                        <circle cx="12" cy="19" r="2" />
                      </svg>
                    </button>
                    {roomMenuOpen && (
                      <div className="chat-menu-dropdown" role="menu">
                        <button type="button" role="menuitem" className="danger" onClick={leaveActiveRoom}>
                          나가기
                        </button>
                        <button
                          type="button"
                          role="menuitem"
                          onClick={openKickDialog}
                          disabled={activeRoom.members.filter((m) => m.employee_id !== user?.id).length === 0}
                        >
                          내보내기
                        </button>
                      </div>
                    )}
                  </div>
                  )}
                </header>
                <div className="messages">
                  {messages.map((m) => {
                    if (m.is_system) {
                      return (
                        <div key={m.id} className="msg system">
                          <div className="system-line">{m.content}</div>
                        </div>
                      );
                    }
                    const mine = m.sender_id === user?.id;
                    const unreadN = m.unread_count || 0;
                    const showUnread = mine && unreadN > 0;
                    return (
                      <div key={m.id} className={mine ? "msg mine" : "msg"}>
                        <div className="meta">
                          {m.sender?.name || m.sender_id}
                          {m.sender?.is_bot ? " 🤖" : ""} · {new Date(m.created_at).toLocaleString()}
                        </div>
                        <div className="bubble-row">
                          {showUnread && (
                            <div className="msg-unread-wrap" ref={unreadPopoverMsgId === m.id ? unreadPopoverRef : undefined}>
                              <button
                                type="button"
                                className="msg-unread-count"
                                title="읽지 않은 사람"
                                aria-label={`읽지 않은 사람 ${unreadN}명`}
                                onClick={() => openUnreadPopover(m)}
                              >
                                {unreadN > 99 ? "99+" : unreadN}
                              </button>
                              {unreadPopoverMsgId === m.id && (
                                <div className="msg-unread-popover" role="dialog" aria-label="읽지 않은 사람">
                                  <div className="msg-unread-popover-title">읽지 않은 사람</div>
                                  {unreadLoading ? (
                                    <div className="muted small">불러오는 중…</div>
                                  ) : unreadUsers.length === 0 ? (
                                    <div className="muted small">모두 읽었습니다</div>
                                  ) : (
                                    <ul className="msg-unread-list">
                                      {unreadUsers.map((u) => (
                                        <li key={u.id}>
                                          <span className="msg-unread-name">{u.name}</span>
                                          <span className="msg-unread-emp muted small">{u.employee_id}</span>
                                        </li>
                                      ))}
                                    </ul>
                                  )}
                                </div>
                              )}
                            </div>
                          )}
                          <div className="bubble">{m.content}</div>
                        </div>
                      </div>
                    );
                  })}
                  <div ref={bottomRef} />
                </div>
                {isLeftRoom(activeRoom) ? (
                  <div className="composer composer-left">
                    <div className="muted small">방에서 나온 채팅입니다. 메시지를 보낼 수 없습니다.</div>
                  </div>
                ) : (
                <div className="composer">
                  <input
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    placeholder="메시지 입력 (@AI 또는 ?로 AI 호출)"
                    disabled={sending}
                    maxLength={4000}
                    onKeyDown={(e) => {
                      if (e.key !== "Enter" || e.nativeEvent.isComposing || sending) return;
                      e.preventDefault();
                      void sendMessage();
                    }}
                  />
                  <button type="button" onClick={() => void sendMessage()} disabled={sending || !text.trim()}>
                    {sending ? "전송 중…" : "전송"}
                  </button>
                </div>
                )}
              </>
            ) : (
              <div className="center">채팅방을 선택하거나 새로 만드세요</div>
            )}
          </div>
        )}

        {tab === "notes" && (
          <div className="notes-layout">
            <div className="notes-subtabs">
              <button
                type="button"
                className={notesSubTab === "inbox" ? "active" : ""}
                onClick={() => setNotesSubTab("inbox")}
              >
                받은 쪽지
                {formatUnread(notesUnread) && (
                  <span className="unread-badge tab-unread-badge">{formatUnread(notesUnread)}</span>
                )}
              </button>
              <button
                type="button"
                className={notesSubTab === "sent" ? "active" : ""}
                onClick={() => setNotesSubTab("sent")}
              >
                보낸 쪽지
              </button>
            </div>

            <div className="notes-list">
              {notesSubTab === "inbox" && (
                inbox.length === 0 ? (
                  <div className="muted center notes-empty">받은 쪽지가 없습니다</div>
                ) : (
                  inbox.map((n) => (
                    <button
                      type="button"
                      key={n.id}
                      className={n.is_read ? "note-card" : "note-card unread"}
                      onClick={() => openNoteDetail(n)}
                    >
                      <div className="note-card-top">
                        <strong className="note-card-title">{n.subject || "(제목 없음)"}</strong>
                        {!n.is_read && <span className="note-unread-dot" aria-label="읽지 않음" />}
                      </div>
                      <div className="muted small">
                        보낸 사람: {n.sender?.name || n.sender_id} · {new Date(n.created_at).toLocaleString()}
                      </div>
                    </button>
                  ))
                )
              )}
              {notesSubTab === "sent" && (
                sentNotes.length === 0 ? (
                  <div className="muted center notes-empty">보낸 쪽지가 없습니다</div>
                ) : (
                  sentNotes.map((n) => (
                    <button
                      type="button"
                      key={n.id}
                      className="note-card"
                      onClick={() => openNoteDetail(n)}
                    >
                      <div className="note-card-top">
                        <strong className="note-card-title">{n.subject || "(제목 없음)"}</strong>
                      </div>
                      <div className="muted small">
                        받는 사람: {n.recipient?.name || n.recipient_id} · {new Date(n.created_at).toLocaleString()}
                      </div>
                    </button>
                  ))
                )
              )}
            </div>

            <div className="notes-footer">
              <button
                type="button"
                className="notes-send-btn"
                onClick={() => openNoteCompose(null)}
              >
                쪽지 보내기
              </button>
            </div>
          </div>
        )}

        {tab === "org" && (
          <div className="org-layout">
            <div className="org-layout-head">
              <h2>조직도</h2>
              <button type="button" className="secondary" onClick={() => openEmployeePicker("dm")}>
                직원 선택
              </button>
            </div>
            <p className="muted small org-layout-hint">
              조직을 클릭하면 하위 조직·소속 직원이 펼쳐집니다. 기본은 접힌 상태입니다.
            </p>
            <div className="org-tree-vertical org-browse-tree">
              {orgTree ? (
                renderOrgBrowseNode(orgTree, 0)
              ) : (
                <div className="muted center" style={{ padding: "2rem" }}>
                  조직도를 불러오는 중…
                </div>
              )}
            </div>
          </div>
        )}
      </main>

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

      {historyDeleteRoomId != null && (
        <div className="modal-overlay" onClick={() => setHistoryDeleteRoomId(null)}>
          <div className="kick-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-labelledby="history-del-title">
            <div className="kick-modal-header">
              <h2 id="history-del-title">채팅 이력 삭제</h2>
              <button type="button" className="ghost" onClick={() => setHistoryDeleteRoomId(null)} aria-label="닫기">✕</button>
            </div>
            <p>채팅 이력을 삭제하시겠습니까?</p>
            <div className="kick-actions">
              <button type="button" className="secondary" onClick={() => setHistoryDeleteRoomId(null)}>취소</button>
              <button type="button" className="danger-solid" onClick={confirmDeleteHistory}>확인</button>
            </div>
          </div>
        </div>
      )}

      {kickOpen && activeRoom && (
        <div className="modal-overlay" onClick={() => setKickOpen(false)}>
          <div className="kick-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-labelledby="kick-title">
            <div className="kick-modal-header">
              <h2 id="kick-title">멤버 내보내기</h2>
              <button type="button" className="ghost" onClick={() => setKickOpen(false)} aria-label="닫기">✕</button>
            </div>
            <p className="muted small">내보낼 참여자를 선택하세요. (본인은 나가기로 퇴장합니다)</p>
            <ul className="kick-member-list">
              {activeRoom.members
                .filter((m) => m.employee_id !== user?.id)
                .map((m) => {
                  const checked = kickSelected.includes(m.employee_id);
                  return (
                    <li key={m.id}>
                      <label>
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() =>
                            setKickSelected((prev) =>
                              checked
                                ? prev.filter((id) => id !== m.employee_id)
                                : [...prev, m.employee_id]
                            )
                          }
                        />
                        <span>
                          {m.employee.name}
                          {m.employee.is_bot ? " 🤖" : ""}
                          <span className="muted small"> · {m.employee.employee_id}</span>
                        </span>
                      </label>
                    </li>
                  );
                })}
            </ul>
            <div className="kick-actions">
              <button type="button" className="secondary" onClick={() => setKickOpen(false)}>취소</button>
              <button type="button" onClick={confirmKick} disabled={!kickSelected.length}>
                내보내기{kickSelected.length ? ` (${kickSelected.length})` : ""}
              </button>
            </div>
          </div>
        </div>
      )}
      <NoteComposeModal
        open={noteComposeOpen}
        draft={noteComposeDraft}
        excludeIds={user?.id ? [user.id] : []}
        onClose={() => {
          setNoteComposeOpen(false);
          setNoteComposeDraft(null);
        }}
        onSent={(count) => {
          setNoteComposeOpen(false);
          setNoteComposeDraft(null);
          refreshNotes()
            .then(() => {
              setNotesSubTab("sent");
              setStatus(`쪽지를 ${count}명에게 보냈습니다`);
            })
            .catch(console.error);
        }}
        onError={setStatus}
      />

      <OrgUserPicker
        open={pickerMode !== null}
        title="직원 선택"
        confirmLabel={confirmLabel}
        excludeIds={pickerExclude}
        includeBots={includeBots}
        initialSelectedIds={
          pickerMode === "group" ? groupMembers.map((m) => m.id) : []
        }
        onClose={() => setPickerMode(null)}
        onConfirm={handlePickerConfirm}
      />



    </div>
  );
}
