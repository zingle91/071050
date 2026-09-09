export interface Department {
  id: number;
  name: string;
  code: string;
  parent_id?: number | null;
}

export interface Employee {
  id: number;
  employee_id: string;
  name: string;
  department_id?: number | null;
  department?: Department | null;
  is_bot: boolean;
}

export interface OrgTreeEmployee {
  id: number;
  employee_id: string;
  name: string;
  is_bot: boolean;
  is_favorite: boolean;
}

export interface OrgTreeNode {
  id: number | null;
  name: string;
  code: string | null;
  node_type: "group" | "department" | string;
  employees: OrgTreeEmployee[];
  children: OrgTreeNode[];
}

export interface RoomMember {
  id: number;
  employee_id: number;
  employee: Employee;
  last_read_at?: string | null;
}

export interface Room {
  id: number;
  /** Stable UUID identity; display names may collide */
  public_id: string;
  name: string;
  room_type: string;
  created_at: string;
  members: RoomMember[];
  /** Per-user personal alias; null/undefined → use name */
  display_name?: string | null;
  unread_count?: number;
  /** Viewer membership: active | left | kicked */
  membership_status?: "active" | "left" | "kicked" | string;
  left_at?: string | null;
  /** Latest message time incl. system; fallback created_at */
  last_message_at?: string | null;
}

export interface Message {
  id: number;
  room_id: number;
  sender_id: number;
  content: string;
  created_at: string;
  sender?: Employee | null;
  /** Non-bot members (excluding sender) who have not read yet */
  unread_count?: number;
  is_system?: boolean;
  system_event?: string | null;
  system_actor_id?: number | null;
  system_target_id?: number | null;
}

export interface UnreadUser {
  id: number;
  employee_id: string;
  name: string;
  is_bot?: boolean;
}

export interface Note {
  id: number;
  sender_id: number;
  recipient_id: number;
  /** Title (제목) */
  subject: string;
  content: string;
  is_read: boolean;
  read_at?: string | null;
  created_at: string;
  sender?: Employee | null;
  recipient?: Employee | null;
  /** Co-recipients from multi-send batch (detail GET) */
  recipients?: Employee[];
}

export interface NotesUnreadCount {
  count: number;
}

/** Effective title for sidebar / header for the current user */
export function roomTitle(room: Room): string {
  const alias = room.display_name?.trim();
  return alias || room.name;
}

export function formatUnread(count: number | undefined | null): string {
  const n = count || 0;
  if (n <= 0) return "";
  if (n > 99) return "99+";
  return String(n);
}

/** Recompute per-message unread from member last_read_at snapshots. */
export function computeMessageUnreadCount(
  msg: Message,
  members: RoomMember[]
): number {
  return members.filter((m) => {
    if (m.employee_id === msg.sender_id) return false;
    if (m.employee?.is_bot) return false;
    if (m.last_read_at == null) return true;
    return new Date(m.last_read_at).getTime() < new Date(msg.created_at).getTime();
  }).length;
}

export function isLeftRoom(room: Room | null | undefined): boolean {
  const s = room?.membership_status || "active";
  return s === "left" || s === "kicked";
}
