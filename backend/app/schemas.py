from datetime import datetime
from pydantic import BaseModel, Field


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    employee_id: str = Field(..., description="사번")
    password: str


class DepartmentOut(BaseModel):
    id: int
    name: str
    code: str
    parent_id: int | None = None

    class Config:
        from_attributes = True


class EmployeeOut(BaseModel):
    id: int
    employee_id: str
    name: str
    department_id: int | None = None
    department: DepartmentOut | None = None
    is_bot: bool = False

    class Config:
        from_attributes = True


class OrgTreeEmployee(BaseModel):
    id: int
    employee_id: str
    name: str
    is_bot: bool = False
    is_favorite: bool = False


class OrgTreeNode(BaseModel):
    id: int | None = None  # None for virtual root if needed
    name: str
    code: str | None = None
    node_type: str  # group | department
    employees: list[OrgTreeEmployee] = []
    children: list["OrgTreeNode"] = []


OrgTreeNode.model_rebuild()


class RoomCreate(BaseModel):
    name: str
    room_type: str = "group"  # direct | group
    member_ids: list[int] = []


class RoomMemberOut(BaseModel):
    id: int
    employee_id: int
    employee: EmployeeOut
    last_read_at: datetime | None = None

    class Config:
        from_attributes = True


class RoomOut(BaseModel):
    id: int
    name: str
    room_type: str
    created_at: datetime
    members: list[RoomMemberOut] = []
    # Per-user personal alias; None means fall back to name
    display_name: str | None = None
    unread_count: int = 0
    # Current viewer's membership: active | left | kicked
    membership_status: str = "active"
    left_at: datetime | None = None
    # Latest message time (incl. system); falls back to created_at when empty
    last_message_at: datetime | None = None

    class Config:
        from_attributes = True


class RoomDisplayNameUpdate(BaseModel):
    display_name: str | None = Field(
        None, description="나만 보이는 채팅방 이름. null/빈 문자열이면 기본 제목으로 복원"
    )


class RoomInviteRequest(BaseModel):
    member_ids: list[int]


class RoomKickRequest(BaseModel):
    member_ids: list[int]


class MessageCreate(BaseModel):
    content: str


class MessageOut(BaseModel):
    id: int
    room_id: int
    sender_id: int
    content: str
    created_at: datetime
    sender: EmployeeOut | None = None
    # Members (non-bot, excluding sender) who have not read this message yet
    unread_count: int = 0
    is_system: bool = False
    system_event: str | None = None
    system_actor_id: int | None = None
    system_target_id: int | None = None

    class Config:
        from_attributes = True


class UnreadUserOut(BaseModel):
    id: int
    employee_id: str
    name: str
    is_bot: bool = False


class NoteCreate(BaseModel):
    """Send a note. Prefer recipient_ids for multi-send; recipient_id kept for compat."""
    recipient_id: int | None = None
    recipient_ids: list[int] = []
    subject: str = ""
    title: str | None = None  # alias for subject (제목)
    content: str = ""
    body: str | None = None  # alias for content


class NoteOut(BaseModel):
    id: int
    sender_id: int
    recipient_id: int
    subject: str
    content: str
    is_read: bool
    read_at: datetime | None = None
    created_at: datetime
    sender: EmployeeOut | None = None
    recipient: EmployeeOut | None = None

    class Config:
        from_attributes = True


class NotesUnreadCount(BaseModel):
    count: int


class InviteBotRequest(BaseModel):
    room_id: int


class FavoriteToggleRequest(BaseModel):
    employee_id: int
