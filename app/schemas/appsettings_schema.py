from pydantic import BaseModel, Field

class DuesSettingsOut(BaseModel):
    annual_handler_dues_amount: float
    enable_dues_collection: bool = False


class DuesSettingsUpdateIn(BaseModel):
    annual_handler_dues_amount: float = Field(ge=0)
    enable_dues_collection: bool = False