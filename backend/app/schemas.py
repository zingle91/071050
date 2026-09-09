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


class RoomCreate(BaseModel):
    name: str
    room_type: str = "group"  # direct | group
    member_ids: list[int] = []


class RoomMemberOut(BaseModel):
    id: int
    employee_id: int
    employee: EmployeeOut

    class Config:
        from_attributes = True


class RoomOut(BaseModel):
    id: int
    name: str
    room_type: str
    created_at: datetime
    members: list[RoomMemberOut] = []

    class Config:
        from_attributes = True


class MessageCreate(BaseModel):
    content: str


class MessageOut(BaseModel):
    id: int
    room_id: int
    sender_id: int
    content: str
    created_at: datetime
    sender: EmployeeOut | None = None

    class Config:
        from_attributes = True


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
