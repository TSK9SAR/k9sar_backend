# app/schemas/evaluator_matrix_schema.py
from pydantic import BaseModel
from typing import List, Dict, Optional

class EvaluatorGroupOut(BaseModel):
    group_id: int
    name: str
    sortorder: int = 0

class EvaluatorCellOut(BaseModel):
    is_evaluator: bool = False
    is_candidate: bool = False
    candidate_map: dict[int, dict[int, str]] = {}

class EvaluatorUserRowOut(BaseModel):
    user_id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: str
    phone: Optional[str] = None
    distance_mi: Optional[float] = None  # <-- add this
    memberships: Dict[int, EvaluatorCellOut]  # group_id -> True/False
    evaluator_missing_signature: bool = False

class EvaluatorMatrixOut(BaseModel):
    groups: List[EvaluatorGroupOut]
    users: List[EvaluatorUserRowOut]

