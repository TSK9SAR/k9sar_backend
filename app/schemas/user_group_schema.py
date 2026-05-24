from pydantic import BaseModel, Field

class UserGroupUpdate(BaseModel):
    group_ids: list[int] = Field(default_factory=list)  # REPLACE user’s evaluator groups
