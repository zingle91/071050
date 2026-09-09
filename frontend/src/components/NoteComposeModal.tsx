import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Note } from "../api/types";
import OrgUserPicker, { type PickedUser } from "./OrgUserPicker";
import type { NoteComposeDraft } from "../noteCompose";

type Props = {
  open: boolean;
  /** Prefill when the modal opens; null/undefined = blank compose */
  draft?: NoteComposeDraft | null;
  /** Exclude self (and any other ids) from recipient picker */
  excludeIds?: number[];
  onClose: () => void;
  /** Called after successful send with recipient count */
  onSent?: (recipientCount: number) => void;
  /** Validation / API error messages */
  onError?: (message: string) => void;
};

const EMPTY: NoteComposeDraft = { subject: "", body: "", recipients: [] };

export default function NoteComposeModal({
  open,
  draft,
  excludeIds = [],
  onClose,
  onSent,
  onError,
}: Props) {
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [recipients, setRecipients] = useState<PickedUser[]>([]);
  const [sending, setSending] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);

  useEffect(() => {
    if (!open) {
      setPickerOpen(false);
      setSending(false);
      return;
    }
    const d = draft || EMPTY;
    setSubject(d.subject || "");
    setBody(d.body || "");
    setRecipients(d.recipients || []);
    setPickerOpen(false);
    setSending(false);
  }, [open, draft]);

  if (!open) return null;

  async function send() {
    if (!recipients.length) {
      setPickerOpen(true);
      return;
    }
    if (!subject.trim()) {
      onError?.("쪽지 제목을 입력하세요");
      return;
    }
    if (!body.trim()) {
      onError?.("쪽지 내용을 입력하세요");
      return;
    }
    const to = [...recipients];
    setSending(true);
    try {
      await api<Note[]>("/api/notes", {
        method: "POST",
        body: JSON.stringify({
          recipient_ids: to.map((r) => r.id),
          subject: subject.trim(),
          content: body.trim(),
        }),
      });
      onSent?.(to.length);
    } catch (e) {
      onError?.(e instanceof Error ? e.message : "쪽지 전송 실패");
    } finally {
      setSending(false);
    }
  }

  return (
    <>
      <div
        className="modal-overlay"
        onClick={() => !sending && onClose()}
        role="presentation"
      >
        <div
          className="note-compose-modal"
          onClick={(e) => e.stopPropagation()}
          role="dialog"
          aria-labelledby="note-compose-title"
        >
          <div className="note-compose-header">
            <h2 id="note-compose-title">쪽지 보내기</h2>
            <button
              type="button"
              className="ghost"
              onClick={() => !sending && onClose()}
              aria-label="닫기"
            >
              ✕
            </button>
          </div>
          <label className="note-field">
            수신자
            <div className="note-recipient-row">
              <button
                type="button"
                className="secondary"
                onClick={() => setPickerOpen(true)}
                disabled={sending}
              >
                직원 선택{recipients.length ? ` (${recipients.length})` : ""}
              </button>
            </div>
            {recipients.length > 0 && (
              <div className="picked-chips">
                {recipients.map((m) => (
                  <span key={m.id} className="chip chip-removable">
                    {m.name}
                    <button
                      type="button"
                      className="chip-x"
                      aria-label={`${m.name} 제거`}
                      onClick={() =>
                        setRecipients((prev) => prev.filter((x) => x.id !== m.id))
                      }
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            )}
          </label>
          <label className="note-field">
            제목
            <input
              autoFocus
              placeholder="제목"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              maxLength={200}
              disabled={sending}
            />
          </label>
          <label className="note-field">
            내용
            <textarea
              placeholder="내용"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={8}
              disabled={sending}
            />
          </label>
          <div className="note-compose-actions">
            <button
              type="button"
              className="secondary"
              onClick={onClose}
              disabled={sending}
            >
              취소
            </button>
            <button type="button" onClick={send} disabled={sending}>
              {sending ? "보내는 중…" : "보내기"}
            </button>
          </div>
        </div>
      </div>

      <OrgUserPicker
        open={pickerOpen}
        title="직원 선택"
        confirmLabel="수신자 확정"
        excludeIds={excludeIds}
        includeBots={false}
        initialSelectedIds={recipients.map((m) => m.id)}
        onClose={() => setPickerOpen(false)}
        onConfirm={(users) => {
          setRecipients(users);
          setPickerOpen(false);
        }}
      />
    </>
  );
}
