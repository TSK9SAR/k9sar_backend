from datetime import date
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
from collections import defaultdict

from app.database import get_db
from app.models.handler import Affiliation
from app.models.handler_affiliations import HandlerAffiliation
from app.models import (
    Handler,
    Team,
    Dog,
    Certification,
    Standard,
    Discipline,
    User,
)

router = APIRouter(prefix="/embed", tags=["Public Embeds"])


def render_directory_html(title: str, rows) -> str:
    grouped = defaultdict(lambda: defaultdict(list))

    for r in rows:
        handler_name = f"{r.first_name or ''} {r.last_name or ''}".strip()
        dog_name = r.dog_name or ""
        grouped[handler_name][dog_name].append(r)

    cards = ""

    today = date.today()

    for handler_name in sorted(grouped.keys()):
        dogs_html = ""

        for dog_name in sorted(grouped[handler_name].keys()):
            certs_html = ""

            cert_rows = ""

            for cert in grouped[handler_name][dog_name]:
                expires = cert.expires_at.isoformat() if cert.expires_at else ""

                raw_status = (cert.status or "no active certs").lower()
                status = raw_status

                expires_value = getattr(cert, "expires_at", None)
                expires = expires_value.isoformat() if expires_value else ""

                if raw_status == "active" and expires_value:
                    exp_date = expires_value.date() if hasattr(expires_value, "date") else expires_value
                    days = (exp_date - today).days

                    if days < 0:
                        status = "expired"
                    elif days <= 60:
                        status = "expiring"

                cert_rows += f"""
                <tr>
                <td class="cert-name">{escape(cert.discipline_name or '')}</td>
                <td class="cert-status">
                <span class="status-badge status-{escape(status)}">
                    {escape(status)}
                </span>
                </td>
                <td class="cert-expires">{escape(expires)}</td>
                </tr>
                """

            dogs_html += f"""
            <div class="dog-card">
            <div class="dog-name">{escape(dog_name)}</div>

            <table class="cert-table">
                <thead>
                <tr>
                    <th>Certification</th>
                    <th>Status</th>
                    <th>Expires</th>
                </tr>
                </thead>
                <tbody>
                {cert_rows}
                </tbody>
            </table>
            </div>
            """

        cards += f"""
        <section class="handler-card">
          <h3>{escape(handler_name)}</h3>
          {dogs_html}
        </section>
        """

    if not cards:
        cards = """
        <div class="empty">No active public certifications found.</div>
        """

    return f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <base target="_blank">
  <style>
    body {{
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 0;
      padding: 12px;
      color: white;
      background: black;
      font-size: 14px;
    }}

    h2 {{
        margin: 0 0 14px;
        padding: 0 0 10px;
        border-bottom: 2px solid #4b5563;
        font-size: 21px;
        font-weight: 700;
        color: #e2e8f0;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        text-align: center;
        }}

    .directory {{
      display: grid;
      gap: 12px;
    }}

    .handler-card {{
      border: 2px solid #3f3f3f;
      border-radius: 12px;
      padding: 12px;
      background: #1f1f1f;
    }}

    .handler-card h3 {{
      margin: 0 0 10px;
      font-size: 17px;
      color: white;
    }}

    .dog-card {{
      border-top: 1px solid #3f3f3f;
      padding-top: 10px;
      margin-top: 10px;
    }}

    .dog-name {{
      font-weight: 700;
      margin-bottom: 6px;
      font-size: 15px;
      color: #aaaaff;
    }}

    .cert-table {{
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
    }}

    .cert-table th,
    .cert-table td {{
    padding: 7px 9px;
    border-bottom: 1px solid #555;
    vertical-align: middle;
    }}
    
    .cert-table th:nth-child(1),
    .cert-table td:nth-child(1) {{
    width: auto;
    text-align: left;
    color: #94a3b8;
    }}

    .cert-table th:nth-child(2),
    .cert-table td:nth-child(2) {{
    width: 90px;
    text-align: center;
    color: #94a3b8;
    }}

    .cert-table th:nth-child(3),
    .cert-table td:nth-child(3) {{
    width: 110px;
    text-align: center;
    color: #94a3b8;
    }}

    .empty {{
      color: #94a3b8;
      font-style: italic;
      text-align: center;
      padding: 20px;
    }}

    .status-badge {{
      display: inline-block;
      min-width: 72px;
      text-align: center;
      padding: 2px 7px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 600;
      line-height: 1.15;
      text-transform: capitalize;
    }}

    .status-active {{
      background: #33691E;
      color: #ffffff;
    }}

    .status-expired {{
      background: #7A2910;
      color: #ffffff;
    }}

    .status-pending {{
      background: #BD763C;
      color: #ffffff;
    }}

    .status-revoked {{
      background: #616161;
      color: #ffffff;
    }}

    .status-incomplete {{
      background: #0288D1;
      color: #ffffff;
    }}

    .status-expiring {{
      background: #E65100;
      color: #ffffff;
    }}

    .status-no-active-certs {{
      background: #f1f5f9;
      color: #475569;
    }}

    .footer {{
      margin-top: 12px;
      font-size: 12px;
      color: #94a3b8;
    }}
  </style>
</head>
<body>
<h2>{escape(title)}</h2>
  <main class="directory">
    {cards}
  </main>

  <div class="footer">
    Certification data provided by TSK9SAR | Tri-State K9 Search and Rescue.
  </div>
</body>
</html>
"""

@router.get(
    "/affiliations/{slug}/directory",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def affiliation_directory_embed(
    slug: str,
    include_all: bool = Query(False, alias="all"),
    db: Session = Depends(get_db),
):
    affiliation = (
        db.query(Affiliation)
        .filter(
            Affiliation.public_slug == slug,
            Affiliation.allow_public_embed == True,
        )
        .first()
    )

    if not affiliation:
        raise HTTPException(status_code=404, detail="Embed not found")
    
    ranked_cert_ids = (
        db.query(
            Certification.certification_id.label("certification_id"),
            Certification.team_id.label("team_id"),
            Standard.discipline_id.label("discipline_id"),
            func.row_number()
            .over(
                partition_by=(
                    Certification.team_id,
                    Standard.discipline_id,
                ),
                order_by=(
                    Certification.date_awarded.desc(),
                    Certification.expires_at.desc(),
                    Certification.certification_id.desc(),
                ),
            )
            .label("row_num"),
        )
        .join(
            Standard,
            Standard.standard_id == Certification.standard_id,
        )
        .filter(Certification.status != "revoked")
        .subquery()
    )

    latest_cert_ids = (
        db.query(
            ranked_cert_ids.c.certification_id.label(
                "latest_certification_id"
            ),
            ranked_cert_ids.c.team_id,
            ranked_cert_ids.c.discipline_id,
        )
        .filter(ranked_cert_ids.c.row_num == 1)
        .subquery()
    )

    base_query = (
        db.query(
            User.first_name,
            User.last_name,
            Dog.name.label("dog_name"),
            Standard.discipline_id,
            Discipline.name.label("discipline_name"),
            Certification.date_awarded,
            Certification.expires_at,
            Certification.status,
        )
        .join(Handler, Handler.user_id == User.user_id)
        .join(
            HandlerAffiliation,
            HandlerAffiliation.handler_id == Handler.handler_id,
        )
        .join(Team, Team.handler_id == Handler.handler_id)
        .join(Dog, Dog.dog_id == Team.dog_id)
    )

    if include_all:
        query = (
            base_query
            .outerjoin(
                latest_cert_ids,
                latest_cert_ids.c.team_id == Team.team_id,
            )
            .outerjoin(
                Certification,
                Certification.certification_id
                == latest_cert_ids.c.latest_certification_id,
            )
            .outerjoin(
                Standard,
                (
                    Standard.standard_id
                    == Certification.standard_id
                )
                & (
                    Standard.discipline_id
                    == latest_cert_ids.c.discipline_id
                ),
            )
            .outerjoin(
                Discipline,
                Discipline.discipline_id
                == Standard.discipline_id,
            )
        )
    else:
        query = (
            base_query
            .join(
                latest_cert_ids,
                latest_cert_ids.c.team_id == Team.team_id,
            )
            .join(
                Certification,
                Certification.certification_id
                == latest_cert_ids.c.latest_certification_id,
            )
            .join(
                Standard,
                (
                    Standard.standard_id
                    == Certification.standard_id
                )
                & (
                    Standard.discipline_id
                    == latest_cert_ids.c.discipline_id
                ),
            )
            .join(
                Discipline,
                Discipline.discipline_id
                == Standard.discipline_id,
            )
            .filter(
                Certification.status.in_(
                    [
                        "active",
                        "pending",
                        "expiring",
                        "expired",
                        "incomplete",
                    ]
                )
            )
        )

    rows = (
        query        
        .filter(
            User.is_active == True,
            HandlerAffiliation.affiliation_id == affiliation.affiliation_id,
            HandlerAffiliation.ended_at.is_(None),
            func.coalesce(Team.status, "active") != "inactive",
        )
        .order_by(User.last_name, User.first_name, Dog.name, Discipline.name)
        .all()
    )

    title = affiliation.embed_title or f"{affiliation.name} Public Directory"

    return HTMLResponse(
        content=render_directory_html(title, rows),
        headers={"Cache-Control": "public, max-age=300"},
    )

