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
