from pydantic import BaseModel

class RoleOut(BaseModel):
    role_id: int
    role_name: str

    class Config:
        orm_mode = True
