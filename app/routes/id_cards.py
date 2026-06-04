from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.handler import Handler
from app.models.user import User
from app.models.id_headshot import HandlerIdHeadshot
import base64
import html as html_lib

from datetime import date
import base64
import html as html_lib
import re
from typing import Optional

from fastapi import HTTPException
from fastapi.responses import HTMLResponse

from app.models.team import Team
from app.models.handler import Handler, Affiliation
from app.models.user import User
from app.models.dog import Dog
from app.models.certification import Certification
from app.models.standard import Standard
from app.models.discipline import Discipline
from app.models.id_headshot import DogIdHeadshot
from app.models.handler_affiliations import HandlerAffiliation

router = APIRouter(prefix="/id-cards", tags=["ID Cards"])

from pathlib import Path

LOGO_B64 = ""
logo_path = Path("/app/static/images/ts_logo_wm.png")

if logo_path.exists():
    LOGO_B64 = base64.b64encode(logo_path.read_bytes()).decode("ascii")

def format_phone(phone: str | None) -> str:
    if not phone:
        return ""

    digits = re.sub(r"\D", "", phone)

    if len(digits) == 10:
        return f"({digits[0:3]}) {digits[3:6]}-{digits[6:10]}"

    if len(digits) == 11 and digits.startswith("1"):
        return f"({digits[1:4]}) {digits[4:7]}-{digits[7:11]}"

    return phone

def affiliation_title(affiliation: Affiliation | None) -> str:
    return (affiliation.name or "").strip() if affiliation else "Tri-State K9 Search and Rescue"


def affiliation_contact_lines(affiliation: Affiliation | None) -> list[str]:
    if not affiliation:
        return []

    lines = []

    if affiliation.phone:
        lines.append(f"Contact: {format_phone(affiliation.phone)}")

    if affiliation.url:
        lines.append(affiliation.url.strip())

    return [x for x in lines if x]

def affiliation_background_data_url(affiliation: Affiliation | None) -> str | None:
    if not affiliation or not affiliation.id_card_background_png:
        return None

    mime = affiliation.id_card_background_mime or "image/png"
    b64 = base64.b64encode(affiliation.id_card_background_png).decode("ascii")
    return f'data:{mime};base64,{b64}'

def slot_position(slot: int):
    slot = max(1, min(10, int(slot or 1)))

    # slots 1-5 left column, 6-10 right column
    col = 0 if slot <= 5 else 1
    row = slot - 1 if slot <= 5 else slot - 6

    return col * 3.5, row * 2.0

def render_id_card_page(
    card_html: str,
    *,
    layout: str = "single",
    slot: str = "1",
    background_data_url: str | None = None,
    text_theme: str = "light",
) -> str:
    layout = (layout or "single").lower().strip()

    logo_background = (
        f'url("data:image/png;base64,{LOGO_B64}")'
        if LOGO_B64
        else "none"
    )

    if background_data_url:
        card_background_css = f'url("{background_data_url}") center / cover no-repeat'
    else:
        card_background_css = """
            radial-gradient(circle at 15% 15%, rgba(16,185,129,0.35), transparent 30%),
            linear-gradient(135deg, #0f172a 0%, #1e293b 55%, #064e3b 100%)
        """

    if text_theme == "dark":
        colors = {
            "body": "#111827",
            "header": "#064e3b",
            "name": "#111827",
            "label": "#374151",
            "info": "#1f2937",
            "footer": "#374151",
            "discipline": "#064e3b",
            "discipline_exp": "#374151",
            "photo_label": "#064e3b",
            "photo_border": "rgba(17,24,39,0.45)",
            "photo_bg": "rgba(255,255,255,0.65)",
        }
    else:
        colors = {
            "body": "#f8fafc",
            "header": "#a7f3d0",
            "name": "white",
            "label": "#94a3b8",
            "info": "#e2e8f0",
            "footer": "#cbd5e1",
            "discipline": "#d1fae5",
            "discipline_exp": "#cbd5e1",
            "photo_label": "#a7f3d0",
            "photo_border": "rgba(255,255,255,0.55)",
            "photo_bg": "rgba(15,23,42,0.8)",
        }

    show_watermark = not background_data_url
    watermark_display = "block" if show_watermark else "none"

    show_decorations = not background_data_url
    decor_display = "block" if show_decorations else "none"

    shared_css = f"""
    body {{
      margin: 0;
      background: #111827;
      font-family: Arial, sans-serif;
      ccolor: {colors["body"]};
    }}

    .card {{
    width: 3.5in;
    height: 2.0in;
    position: relative;
    overflow: hidden;
    border-radius: 0.12in;
    border: 1px solid #334155;

    background: {card_background_css};

    box-shadow: 0 10px 30px rgba(0,0,0,0.35);
    box-sizing: border-box;
    }}

    .card::before {{
    display: {watermark_display};
    content: "";
    position: absolute;

    /* size */
    width: 2.6in;
    height: 2.6in;

    /* position */
    left: 0.45in;
    top: -0.16in;

    /* logo image */
    background-image: {logo_background};
    background-repeat: no-repeat;
    background-position: center;
    background-size: contain;

    /* transparency */
    opacity: 0.2;

    /* keep behind text */
    z-index: 0;

    pointer-events: none;
    }}

    .card > * {{
    position: relative;
    z-index: 1;
    }}

    .affiliation-info {{
    position: absolute;
    bottom: 0.28in;
    left: 0.15in;
    right: 1.08in;
    font-size: 0.075in;
    line-height: 1.18;
    font-weight: 700;
    color: {colors["footer"]};
    }}
    
    .stripe {{
      display: {decor_display};
      position: absolute;
      inset: auto -0.4in -0.55in auto;
      width: 2.3in;
      height: 1.1in;
      background: rgba(16,185,129,0.18);
      transform: rotate(-22deg);
    }}

    .header {{
      position: absolute;
      top: 0.12in;
      left: 0.15in;
      right: 0.20in;
      font-size: 0.1in;
      font-weight: 700;
      letter-spacing: 0.018in;
      color: {colors["header"]};
      text-transform: uppercase;
      white-space: nowrap;
    }}

    .photo {{
      position: absolute;
      top: 0.36in;
      right: 0.15in;
      width: 0.78in;
      height: 1.17in;
      border-radius: 0.08in;
      object-fit: cover;
      border: 2px solid rgba(255,255,255,0.55);
      background: rgba(15,23,42,0.8);
    }}

    .handler-card .name {{
      position: absolute;
      top: 0.45in;
      left: 0.15in;
      right: 1.1in;
      font-size: 0.22in;
      line-height: 1.05;
      font-weight: 800;
      color:  {colors["name"]};
    }}

    .handler-card .label {{
      position: absolute;
      top: 0.8in;
      left: 0.15in;
      font-size: 0.09in;
      letter-spacing: 0.015in;
      color: {colors["label"]};
      text-transform: uppercase;
    }}

    .handler-card .info {{
      position: absolute;
      top: 0.95in;
      left: 0.15in;
      right: 1.12in;
      font-size: 0.105in;
      line-height: 1.35;
      color: {colors["info"]};
    }}

    .handler-card .footer {{
      position: absolute;
      bottom: 0.12in;
      left: 0.15in;
      font-size: 0.085in;
      color: {colors["footer"]};
    }}

    .k9-card .name {{
      position: absolute;
      top: 0.35in;
      left: 0.15in;
      right: 1.1in;
      font-size: 0.28in;
      line-height: 1.05;
      font-weight: 800;
      color: {colors["name"]};
    }}

    .k9-card .dog-details {{
      position: absolute;
      top: 0.69in;
      left: 0.15in;
      right: 1.12in;
      font-size: 0.095in;
      color: {colors["footer"]};
    }}

    .k9-card .handler {{
      position: absolute;
      top: 0.84in;
      left: 0.15in;
      right: 1.12in;
      font-size: 0.105in;
      color: {colors["info"]};
      line-height: 1.3;
    }}

    .affiliation-info {{
        position: absolute;
        top: 1.45in;        /* adjust as needed */
        left: 0.15in;
        right: 1.08in;

        font-size: 0.08in;
        line-height: 1.15;

        font-weight: 700;
        color: {colors["header"]};
    }}

    .k9-card .disciplines {{
      position: absolute;
      top: 1.0in;
      left: 0.22in;
      right: 1.14in;
      font-size: 0.08in;
      line-height: 1.15;
      color: {colors["discipline"]};
    }}

    .k9-card .discipline-row {{
    display: flex;
    gap: 0.10in;
    }}

    .k9-card .discipline-name {{
    width: 1.1in;
    flex-shrink: 0;
    }}

    .k9-card .discipline-exp {{
    color:  {colors["discipline_exp"]};
    }}

    .k9-card .photo-label {{
      position: absolute;
      bottom: 0.14in;
      right: 0.15in;
      width: 0.82in;
      text-align: center;
      font-size: 0.12in;
      font-weight: 800;
      letter-spacing: 0.015in;
      color:  {colors["photo_label"]};
    }}

    .k9-card .footer {{
      position: absolute;
      bottom: 0.14in;
      left: 1.2in;
      font-size: 0.085in;
      color: {colors["footer"]};
    }}
    """

    if layout != "sheet":
        return f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="format-detection" content="telephone=no,email=no,address=no" />
  <style>
    @page {{ size: landscape; margin: 0.25in; }}
    {shared_css}
    .page {{ min-height: 100vh; display: flex; align-items: center; justify-content: center; }}
    .print-button {{ position: fixed; top: 20px; right: 20px; padding: 10px 14px; border-radius: 8px; border: 1px solid #64748b; background: #1e293b; color: white; cursor: pointer; }}
    @media print {{
      body {{ background: white; }}
      .page {{ min-height: auto; }}
      .print-button {{ display: none; }}
      .card {{ box-shadow: none; }}
    }}
  </style>
</head>
<body>
  <button class="print-button" onclick="window.print()">Print</button>
  <div class="page">{card_html}</div>
</body>
</html>
"""

    slot_value = str(slot).lower().strip()

    if slot_value == "all":
        placed_cards_html = "\n".join(
            f"""
            <div class="placed-card" style="left: {slot_position(s)[0]}in; top: {slot_position(s)[1]}in;">
            {card_html}
            </div>
            """
            for s in range(1, 11)
        )
        print_label = "full sheet"
    else:
        try:
            slot_no = int(slot_value)
        except ValueError:
            slot_no = 1

        left, top = slot_position(slot_no)
        placed_cards_html = f"""
        <div class="placed-card" style="left: {left}in; top: {top}in;">
            {card_html}
        </div>
        """
        print_label = f"slot {slot_no}"

    return f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    @page {{ size: letter; margin: 0.5in; }}
    {shared_css}

    body {{
      background: white;
    }}

    .print-button {{
      position: fixed;
      top: 20px;
      right: 20px;
      padding: 10px 14px;
      border-radius: 8px;
      border: 1px solid #64748b;
      background: #1e293b;
      color: white;
      cursor: pointer;
      z-index: 10;
    }}

    .sheet-wrap {{
      width: 7in;
      height: 10in;
      margin: 0.5in auto;
      background: white;
    }}

    .sheet {{
      position: relative;
      width: 7in;
      height: 10in;
      background: white;
    }}

    .placed-card {{
      position: absolute;
      width: 3.5in;
      height: 2in;
    }}

    .placed-card .card {{
      box-shadow: none;
      border-radius: 0;
    }}

    @media print {{
      body {{
        margin: 0;
        background: white;
      }}

      .print-button {{
        display: none;
      }}

      .sheet-wrap {{
        width: 7in;
        height: 10in;
        margin: 0;
      }}

      .sheet {{
        width: 7in;
        height: 10in;
        margin: 0;
      }}
    }}
  </style>
</head>
<body>

<button class="print-button" onclick="window.print()">Print {print_label}</button>

<div class="sheet-wrap">
  <div class="sheet">
    {placed_cards_html}
  </div>
</div>
</body>
</html>
"""

@router.get("/handlers/{handler_id}", response_class=HTMLResponse)
def handler_id_card(
    handler_id: int,
    layout: str = "single",
    slot: str = "1",
    affiliation_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    handler = (
        db.query(Handler)
        .filter(Handler.handler_id == handler_id)
        .first()
    )

    if not handler:
        raise HTTPException(status_code=404, detail="Handler not found")

    affiliation = None
    if affiliation_id is not None:
        affiliation = (
            db.query(Affiliation)
            .filter(Affiliation.affiliation_id == affiliation_id)
            .first()
        )
        if not affiliation:
            raise HTTPException(status_code=404, detail="Affiliation not found")

    card_title = html_lib.escape(affiliation_title(affiliation))
    affiliation_lines = affiliation_contact_lines(affiliation)
    affiliation_info_html = "<br/>".join(
        html_lib.escape(line) for line in affiliation_lines
    )

    affiliation_lines = []

    if affiliation:
        if affiliation.callout_line:
            affiliation_lines.append(affiliation.callout_line.strip())

        if affiliation.url:
            affiliation_lines.append(affiliation.url.strip())

        affiliation_info_html = "<br/>".join(
            html_lib.escape(line)
            for line in affiliation_lines
        )

    user = db.query(User).filter(User.user_id == handler.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Handler user not found")

    headshot = (
        db.query(HandlerIdHeadshot)
        .filter(
            HandlerIdHeadshot.handler_id == handler_id,
            HandlerIdHeadshot.is_active == True,
        )
        .order_by(HandlerIdHeadshot.headshot_id.desc())
        .first()
    )

    email = user.email or ""
    name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    phone = format_phone(user.phone)
    email_parts = email.split("@", 1)
    email_html = ""
    if len(email_parts) == 2:
        email_html = (
            f'<span>{html_lib.escape(email_parts[0])}</span>'
            f'<span>&#64;</span>'
            f'<span>{html_lib.escape(email_parts[1])}</span>'
        )
    else:
        email_html = html_lib.escape(email)

    address_parts = [
        # user.address_line1,
        # user.address_line2,
        user.city,
        user.state_province,
        user.postal_code,
    ]
    address = ", ".join([p for p in address_parts if p])

    name = html_lib.escape(name)
    phone = html_lib.escape(phone)
    address = html_lib.escape(address)

    headshot_src = ""
    if headshot:
        b64 = base64.b64encode(headshot.image_png).decode("ascii")
        headshot_src = f"data:image/png;base64,{b64}"

    card_html = f"""
    <div class="card handler-card">
    <div class="stripe"></div>
    <div class="header">{card_title}</div>

    <div class="name">{name}</div>
    <div class="label">K9 Handler</div>

    <div class="info">
        {address}<br/>
        {phone}<br/>
        {email_html}
    </div>

    {f'<img class="photo" src="{headshot_src}" />' if headshot_src else ''}

    {f'<div class="affiliation-info">{affiliation_info_html}</div>' if affiliation_info_html else ''}
    <div class="footer">Tri-State K9 | tsk9sar.org</div>
    </div>
    """

    return HTMLResponse(
        content=render_id_card_page(
            card_html,
            layout=layout,
            slot=slot,
            background_data_url=affiliation_background_data_url(affiliation),
            text_theme=affiliation.id_card_text_theme if affiliation else "light",
        ),
        headers={"Cache-Control": "no-transform"},
    )

@router.get("/teams/{team_id}", response_class=HTMLResponse)
def team_k9_id_card(
    team_id: int,
    layout: str = "single",
    slot: str = "1",
    affiliation_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    today = date.today()

    team = (
        db.query(Team)
        .filter(Team.team_id == team_id)
        .first()
    )

    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    handler = (
        db.query(Handler)
        .filter(Handler.handler_id == team.handler_id)
        .first()
    )

    if not handler:
        raise HTTPException(status_code=404, detail="Handler not found")

    affiliation = None
    if affiliation_id is not None:
        affiliation = (
            db.query(Affiliation)
            .filter(Affiliation.affiliation_id == affiliation_id)
            .first()
        )
        if not affiliation:
            raise HTTPException(status_code=404, detail="Affiliation not found")
    
    card_title = html_lib.escape(affiliation_title(affiliation))

        
    user = (
        db.query(User)
        .filter(User.user_id == handler.user_id)
        .first()
    )

    if not user:
        raise HTTPException(status_code=404, detail="Handler user not found")

    dog = (
        db.query(Dog)
        .filter(Dog.dog_id == team.dog_id)
        .first()
    )

    if not dog:
        raise HTTPException(status_code=404, detail="Dog not found")

    headshot = (
        db.query(DogIdHeadshot)
        .filter(
            DogIdHeadshot.dog_id == dog.dog_id,
            DogIdHeadshot.is_active == True,
        )
        .order_by(DogIdHeadshot.headshot_id.desc())
        .first()
    )

    cert_rows = (
        db.query(
            Discipline.name,
            Discipline.sortorder,
            Certification.expires_at,
        )
        .join(Standard, Standard.discipline_id == Discipline.discipline_id)
        .join(Certification, Certification.standard_id == Standard.standard_id)
        .filter(Certification.team_id == team_id)
        .filter(Certification.status == "active")
        .filter(Certification.expires_at >= today)
        .distinct()
        .order_by(Discipline.sortorder.asc(), Discipline.name.asc())
        .all()
    )

    disciplines = [
        {
            "name": r[0],
            "expires": r[2],
        }
        for r in cert_rows
        if r[0]
    ]

    dog_name = html_lib.escape((dog.name or "").strip())
    handler_name = html_lib.escape(
        f"{user.first_name or ''} {user.last_name or ''}".strip()
    )
    breed = html_lib.escape((dog.breed or "").strip())
    sex = html_lib.escape((dog.sex or "").strip())

    dog_details = " • ".join([p for p in [breed, sex] if p])

    discipline_html = ""
    if disciplines:
        discipline_html = "".join(
            f"""
            <div class="discipline-row">
            <span class="discipline-name">{html_lib.escape(d["name"])}</span>
            <span class="discipline-exp">exp. {d["expires"].strftime("%b %Y") if d["expires"] else ""}</span>
            </div>
            """
            for d in disciplines
        )
    else:
        discipline_html = "<div>None currently certified</div>"

    headshot_src = ""
    if headshot:
        b64 = base64.b64encode(headshot.image_png).decode("ascii")
        headshot_src = f"data:image/png;base64,{b64}"

    card_html = f"""
    <div class="card k9-card">
    <div class="stripe"></div>
    <div class="header">{card_title}</div>

    <div class="name">{dog_name}</div>
    <div class="dog-details">{dog_details}</div>

    <div class="handler">
        Handler: {handler_name}
    </div>

    <div class="disciplines">
        {discipline_html}
    </div>

    {f'<img class="photo" src="{headshot_src}" />' if headshot_src else ''}
    <div class="photo-label">K9 ID</div>

    <div class="footer">Tri-State K9 | tsk9sar.org</div>
    </div>
    """

    return HTMLResponse(
        content=render_id_card_page(
            card_html,
            layout=layout,
            slot=slot,
            background_data_url=affiliation_background_data_url(affiliation),
            text_theme=affiliation.id_card_text_theme if affiliation else "light",
        ),
        headers={"Cache-Control": "no-transform"},
    )

@router.get("/handlers/{handler_id}/id-card-affiliations")
def handler_id_card_affiliations(
    handler_id: int,
    db: Session = Depends(get_db),
):
    handler = db.query(Handler).filter(Handler.handler_id == handler_id).first()
    if not handler:
        raise HTTPException(status_code=404, detail="Handler not found")

    rows = (
        db.query(Affiliation)
        .join(
            HandlerAffiliation,
            HandlerAffiliation.affiliation_id == Affiliation.affiliation_id,
        )
        .filter(
            HandlerAffiliation.handler_id == handler_id,
            HandlerAffiliation.ended_at.is_(None),
            Affiliation.is_active == True,
        )
        .order_by(Affiliation.sortorder.asc(), Affiliation.name.asc())
        .all()
    )

    return [
        {
            "affiliation_id": None,
            "name": "Tri-State K9 SAR",
            "is_default": True,
        },
        *[
            {
                "affiliation_id": a.affiliation_id,
                "name": a.name,
                "is_default": False,
            }
            for a in rows
        ],
    ]