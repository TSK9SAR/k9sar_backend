from pydantic import BaseModel, ConfigDict
from typing import Optional, List


class HelpVideoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    video_id: int
    video_key: str
    label: Optional[str] = None
    sort_order: int
    is_active: bool


class HelpItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    help_id: int
    section_id: int
    slug: str
    title: str
    description: Optional[str] = None
    markdown_md: Optional[str] = None
    sort_order: int
    is_active: bool
    videos: List[HelpVideoOut] = []


class HelpSectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    section_id: int
    title: str
    sort_order: int
    is_active: bool
    items: List[HelpItemOut] = []


class HelpSectionIn(BaseModel):
    title: str
    sort_order: int = 0
    is_active: bool = True


class HelpItemIn(BaseModel):
    section_id: int
    slug: str
    title: str
    description: Optional[str] = None
    markdown_md: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True


class HelpVideoIn(BaseModel):
    video_key: str
    label: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True