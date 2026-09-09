/** Shared note compose draft helpers + postMessage protocol for popup detail. */

import type { Employee, Note } from "./api/types";
import type { PickedUser } from "./components/OrgUserPicker";

export const NOTE_COMPOSE_MSG = "messenger:note-compose";
export const NOTE_COMPOSE_STORAGE_KEY = "messenger_note_compose_draft";

export type NoteComposeDraft = {
  subject: string;
  body: string;
  recipients: PickedUser[];
};

export function employeeToPicked(e: Pick<Employee, "id" | "employee_id" | "name" | "is_bot">): PickedUser {
  return {
    id: e.id,
    employee_id: e.employee_id,
    name: e.name,
    is_bot: !!e.is_bot,
  };
}

/** Original body as a clearly separated quoted block (blank line + section). */
export function buildQuotedNoteBody(note: Note): string {
  const senderLabel = note.sender?.name || String(note.sender_id);
  const when = new Date(note.created_at).toLocaleString();
  const subject = note.subject || "(제목 없음)";
  const lines = [
    "",
    "",
    "----- 원본 쪽지 -----",
    `제목: ${subject}`,
    `보낸 사람: ${senderLabel}`,
    `날짜: ${when}`,
    "",
    note.content || "",
  ];
  return lines.join("\n");
}

export function withRePrefix(subject: string): string {
  const s = (subject || "").trim() || "(제목 없음)";
  if (/^(re|RE|Re|답장)\s*:/i.test(s)) return s;
  return `RE: ${s}`;
}

export function withFwPrefix(subject: string): string {
  const s = (subject || "").trim() || "(제목 없음)";
  if (/^(fw|FW|Fw|fwd|FWD|전달)\s*:/i.test(s)) return s;
  return `FW: ${s}`;
}

function uniquePicked(users: PickedUser[]): PickedUser[] {
  const seen = new Set<number>();
  const out: PickedUser[] = [];
  for (const u of users) {
    if (seen.has(u.id)) continue;
    seen.add(u.id);
    out.push(u);
  }
  return out;
}

function batchRecipients(note: Note): PickedUser[] {
  if (note.recipients && note.recipients.length) {
    return note.recipients.map(employeeToPicked);
  }
  if (note.recipient) return [employeeToPicked(note.recipient)];
  return [];
}

/** Reply: to original sender (if self is sender, fall back to recipient). */
export function buildReplyDraft(note: Note, selfId: number): NoteComposeDraft {
  let recipients: PickedUser[] = [];
  if (note.sender_id !== selfId && note.sender) {
    recipients = [employeeToPicked(note.sender)];
  } else {
    recipients = batchRecipients(note).filter((r) => r.id !== selfId);
  }
  return {
    subject: withRePrefix(note.subject),
    body: buildQuotedNoteBody(note),
    recipients: uniquePicked(recipients),
  };
}

/** Reply all: sender + all other recipients, exclude self. */
export function buildReplyAllDraft(note: Note, selfId: number): NoteComposeDraft {
  const recipients: PickedUser[] = [];
  if (note.sender_id !== selfId && note.sender) {
    recipients.push(employeeToPicked(note.sender));
  }
  for (const r of batchRecipients(note)) {
    if (r.id !== selfId) recipients.push(r);
  }
  return {
    subject: withRePrefix(note.subject),
    body: buildQuotedNoteBody(note),
    recipients: uniquePicked(recipients),
  };
}

/** Forward: body unchanged; subject FW: ... */
export function buildForwardDraft(note: Note): NoteComposeDraft {
  return {
    subject: withFwPrefix(note.subject),
    body: note.content || "",
    recipients: [],
  };
}

export function postComposeToOpener(draft: NoteComposeDraft): boolean {
  const payload = { source: NOTE_COMPOSE_MSG, draft };
  if (window.opener && !window.opener.closed) {
    window.opener.postMessage(payload, window.location.origin);
    try {
      window.opener.focus();
    } catch {
      /* ignore */
    }
    return true;
  }
  try {
    sessionStorage.setItem(NOTE_COMPOSE_STORAGE_KEY, JSON.stringify(draft));
  } catch {
    /* ignore */
  }
  return false;
}

export function readStoredComposeDraft(): NoteComposeDraft | null {
  try {
    const raw = sessionStorage.getItem(NOTE_COMPOSE_STORAGE_KEY);
    if (!raw) return null;
    sessionStorage.removeItem(NOTE_COMPOSE_STORAGE_KEY);
    return JSON.parse(raw) as NoteComposeDraft;
  } catch {
    return null;
  }
}
