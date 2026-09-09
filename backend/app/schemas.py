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

    class Config:
        from_attributes = True


class RoomDisplayNameUpdate(BaseModel):
    display_name: str | None = Field(
        None, description="나만 보이는 채팅방 이름. null/빈 문자열이면 기본 제목으로 복원"
    )


class RoomInviteRequest(BaseModel):
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

    class Config:
        from_attributes = True


class UnreadUserOut(BaseModel):
    id: int
    employee_id: str
    name: str
    is_bot: bool = False


class NoteCreate(BaseModel):
    recipient_id: int
    subject: str = ""
    content: str


class NoteOut(BaseModel):
    id: int
    sender_id: int
    recipient_id: int
    subject: str
    content: str
    is_read: bool
    created_at: datetime
    sender: EmployeeOut | None = None
    recipient: EmployeeOut | None = None

    class Config:
        from_attributes = True


class InviteBotRequest(BaseModel):
    room_id: int


class FavoriteToggleRequest(BaseModel):
    employee_id: int
