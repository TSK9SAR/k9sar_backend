from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Literal
from datetime import date, datetime

class DashboardPermissions(BaseModel):
    can_manage_members: bool
    can_manage_teams: bool
    can_manage_disciplines: bool
    can_manage_standards: bool
    can_hard_delete: bool

class DashboardKpis(BaseModel):
    teams: int
    handlers: int
    dogs: int
    pending_affiliation_requests: int
    certs_expiring_30: int
    certs_expiring_90: int

class ExpiringCertRow(BaseModel):
    certification_id: int
    team_id: int
    handler_name: str
    dog_name: str
    standard_name: str
    expires_at: Optional[date]
    days_left: Optional[int]

class RecentActivityRow(BaseModel):
    type: str
    when: datetime
    summary: str

class TrendPoint(BaseModel):
    bucket: str
    count: int

class RecentCertActivityRow(BaseModel):
    team_id: int
    handler_name: str
    dog_name: str
    discipline: str
    issuer_name: str
    action: str
    actor_name: str
    when: datetime

class DashboardDues(BaseModel):
    dues_year: int
    status: str | None = None          # for self view: unpaid | paid | waived
    unpaid_count: int = 0              # for admin/supervisor scoped summary
    paid_count: int = 0
    waived_count: int = 0
    total_count: int = 0
    is_self_view: bool = False
    dues_enabled: bool = False


class DashboardQueues(BaseModel):
    expiring_certs: List[ExpiringCertRow] = Field(default_factory=list)
    recent_activity: List[RecentActivityRow] = Field(default_factory=list)
    recent_cert_activity: List[RecentCertActivityRow] = []


class DashboardTrends(BaseModel):
    issued_by_week: List[TrendPoint]

class DashboardSummaryOut(BaseModel):
    permissions: DashboardPermissions
    kpis: DashboardKpis
    queues: DashboardQueues
    trends: DashboardTrends
    dues: Optional[DashboardDues] = None
    dues_enabled: bool

class DashboardSettingsOut(BaseModel):
    dues_enabled: bool
