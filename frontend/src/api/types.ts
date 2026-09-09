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
}

export interface Room {
  id: number;
  name: string;
  room_type: string;
  created_at: string;
  members: RoomMember[];
  /** Per-user personal alias; null/undefined → use name */
  display_name?: string | null;
  unread_count?: number;
}

export interface Message {
  id: number;
  room_id: number;
  sender_id: number;
  content: string;
  created_at: string;
  sender?: Employee | null;
}

export interface Note {
  id: number;
  sender_id: number;
  recipient_id: number;
  subject: string;
  content: string;
  is_read: boolean;
  created_at: string;
  sender?: Employee | null;
  recipient?: Employee | null;
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
