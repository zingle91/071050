import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Note } from "../api/types";
import { useAuth } from "../auth";
import {
  buildForwardDraft,
  buildReplyAllDraft,
  buildReplyDraft,
  postComposeToOpener,
  type NoteComposeDraft,
} from "../noteCompose";

export default function NoteDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { user, loading: authLoading } = useAuth();
  const navigate = useNavigate();
  const [note, setNote] = useState<Note | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const noteId = Number(id);
    if (!Number.isFinite(noteId) || noteId <= 0) {
      setError("잘못된 쪽지입니다");
      setLoading(false);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const detail = await api<Note>(`/api/notes/${noteId}`);
        if (cancelled) return;
        setNote(detail);
        document.title = `${detail.subject || "(제목 없음)"} · 쪽지`;
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "쪽지를 열 수 없습니다");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  const runCompose = useCallback(
    (draft: NoteComposeDraft) => {
      const sent = postComposeToOpener(draft);
      if (sent) {
        // Keep popup open so user can still see the note; compose opens in opener.
        return;
      }
      // No opener (direct URL): stash draft and go to main messenger compose.
      navigate("/", { replace: true });
    },
    [navigate]
  );

  if (authLoading || loading) {
    return <div className="note-popup-page center">로딩 중...</div>;
  }
  if (error) {
    return (
      <div className="note-popup-page">
        <div className="note-popup-card">
          <p className="status">{error}</p>
          <button type="button" className="secondary" onClick={() => window.close()}>
            닫기
          </button>
        </div>
      </div>
    );
  }
  if (!note || !user) {
    return <div className="note-popup-page center">쪽지를 찾을 수 없습니다</div>;
  }

  const isMine = note.sender_id === user.id;
  const recipientNames =
    note.recipients && note.recipients.length
      ? note.recipients.map((r) => r.name).join(", ")
      : note.recipient?.name || String(note.recipient_id);

  return (
    <div className="note-popup-page">
      <div className="note-popup-card">
        <div className="note-detail-header">
          <h1 id="note-detail-title">{note.subject || "(제목 없음)"}</h1>
          <button type="button" className="ghost" onClick={() => window.close()} aria-label="닫기">
            ✕
          </button>
        </div>
        <div className="muted small note-detail-meta">
          <div>보낸 사람: {note.sender?.name || note.sender_id}</div>
          <div>받는 사람: {recipientNames}</div>
          <div>
            {new Date(note.created_at).toLocaleString()}
            {note.is_read && note.read_at
              ? ` · 읽음 ${new Date(note.read_at).toLocaleString()}`
              : note.recipient_id === user.id && note.is_read
                ? " · 읽음"
                : ""}
          </div>
        </div>
        <div className="note-detail-body">{note.content}</div>
        <div className="note-detail-actions note-detail-actions-row">
          <button
            type="button"
            className="secondary"
            onClick={() => runCompose(buildForwardDraft(note))}
          >
            전달하기
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => runCompose(buildReplyDraft(note, user.id))}
            disabled={isMine && !(note.recipients?.length || note.recipient)}
          >
            답장하기
          </button>
          <button
            type="button"
            onClick={() => runCompose(buildReplyAllDraft(note, user.id))}
          >
            전체 답장하기
          </button>
        </div>
      </div>
    </div>
  );
}
