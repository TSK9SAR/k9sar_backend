# app/models/__init__.py
from app.database import Base
from app.models.user import User
from app.models.handler import Handler
from app.models.dog import Dog
from app.models.certification import Certification
from app.models.discipline import Discipline
from app.models.standard import Standard
from app.models.user_roles import user_roles  # <-- this is the Table
from app.models.team import Team
from app.models.discipline_group import DisciplineGroup
from app.models.user_discipline_group import user_discipline_groups
from sqlalchemy import Table, Column, Integer, ForeignKey
from sqlalchemy.orm import relationship



