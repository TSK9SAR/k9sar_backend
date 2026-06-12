# app/routes/standard_routes.py
import math
from typing import List, Optional
from datetime import date
from urllib.parse import unquote
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from io import BytesIO
from fastapi.responses import StreamingResponse
from pathlib import Path
from app.database import get_db
from app.schemas.standard_schema import StandardCreate, StandardUpdate, StandardOut
from app.models.standard import Standard as StandardModel
from app.models.standard import Standard
from app.models.discipline import Discipline
from app.models.user import User
from app.models.discipline_group import DisciplineGroup
from app.schemas.standard_schema import StandardOut
from app.utils.auth import get_current_user, require_mfa_verified, require_admin
from pypdf import PdfReader, PdfWriter
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import Image, Spacer
from reportlab.lib.utils import ImageReader

router = APIRouter(prefix="/standards", tags=["Standards"])


@router.post("/", response_model=StandardOut, status_code=status.HTTP_201_CREATED)
def create_standard(
    payload: StandardCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),   # <-- add this
    _mfa=Depends(require_mfa_verified),
):
    # Optional: enforce unique name (global)
    existing = (
        db.query(StandardModel)
        .filter(StandardModel.name == payload.name)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A standard with this name already exists.",
        )

    standard_obj = StandardModel(
        discipline_id=payload.discipline_id,
        name=payload.name,
        url=payload.url,
        summary_md=payload.summary_md,
        effective_date=payload.effective_date,
        incomplete_days=payload.incomplete_days,
        effective_days=payload.effective_days,
    )


    db.add(standard_obj)
    db.commit()
    db.refresh(standard_obj)
    return standard_obj


@router.get("/", response_model=List[StandardOut])
def list_standards(
    discipline_id: int | None = None,
    section: str = "operational",   # operational | generic
    db: Session = Depends(get_db),
):
    rows_query = (
        db.query(
            Standard,
            Discipline.name.label("discipline_name"),
            Discipline.sortorder.label("discipline_sortorder"),
            Discipline.group_id.label("group_id"),
            DisciplineGroup.name.label("discipline_group_name"),
            DisciplineGroup.sortorder.label("discipline_group_sortorder"),
        )
        .outerjoin(Discipline, Discipline.discipline_id == Standard.discipline_id)
        .outerjoin(DisciplineGroup, DisciplineGroup.group_id == Discipline.group_id)
    )

    if discipline_id:
        # ADMIN / EDIT MODE
        # Fetch everything for that discipline, regardless of visibility flags
        rows_query = rows_query.filter(Standard.discipline_id == discipline_id)
    else:
        # PUBLIC MODE
        if section == "generic":
            rows_query = rows_query.filter(Discipline.show_generic.is_(True))
        else:
            rows_query = rows_query.filter(DisciplineGroup.show_operational.is_(True))
            rows_query = rows_query.filter(Discipline.show_operational.is_(True))

    rows = (
        rows_query
        .order_by(
            DisciplineGroup.sortorder.asc(),
            Discipline.sortorder.asc(),
            Standard.effective_date.desc(),
            Standard.name.asc(),
        )
        .all()
    )

    out: List[StandardOut] = []
    for std, disc_name, disc_sortorder, group_id, group_name, group_sortorder in rows:
        try:
            item = StandardOut.model_validate(std)
        except AttributeError:
            item = StandardOut.from_orm(std)

        item.discipline_name = disc_name
        item.discipline_sortorder = disc_sortorder
        item.discipline_group_id = group_id
        item.discipline_group_name = group_name
        item.discipline_group_sortorder = group_sortorder

        out.append(item)

    return out

@router.get("/admin/all", response_model=List[StandardOut])
def list_all_standards_for_admin(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    _mfa=Depends(require_mfa_verified),
):

    rows = (
        db.query(
            Standard,
            Discipline.name.label("discipline_name"),
            Discipline.group_id.label("group_id"),
            DisciplineGroup.name.label("discipline_group_name"),
        )
        .outerjoin(Discipline, Discipline.discipline_id == Standard.discipline_id)
        .outerjoin(DisciplineGroup, DisciplineGroup.group_id == Discipline.group_id)
        .order_by(Standard.standard_id.asc())
        .all()
    )

    out: List[StandardOut] = []
    for std, disc_name, group_id, group_name in rows:
        try:
            item = StandardOut.model_validate(std)
        except AttributeError:
            item = StandardOut.from_orm(std)

        item.discipline_name = disc_name
        item.discipline_group_id = group_id
        item.discipline_group_name = group_name
        out.append(item)

    return out


@router.get("/current", response_model=StandardOut | None)
def get_applicable_standard(
    discipline_id: int,
    on_date: date | None = None,
    db: Session = Depends(get_db),
) -> StandardOut | None:
    standard_obj = (
        db.query(StandardModel)
        .filter(
            StandardModel.discipline_id == discipline_id,
            StandardModel.effective_date <= (on_date or date.today()),
        )
        .order_by(StandardModel.effective_date.desc())
        .first()
    )
    return standard_obj


@router.get("/{standard_id}", response_model=StandardOut)
def get_standard_by_id(
    standard_id: int,
    db: Session = Depends(get_db),
):
    standard_obj = (
        db.query(StandardModel)
        .filter(StandardModel.standard_id == standard_id)
        .first()
    )
    if not standard_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Standard not found.",
        )
    return standard_obj


@router.put("/{standard_id}", response_model=StandardOut)
def update_standard(
    standard_id: int,
    payload: StandardUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    _mfa=Depends(require_mfa_verified),
):

    standard_obj = (
        db.query(StandardModel)
        .filter(StandardModel.standard_id == standard_id)
        .first()
    )
    if not standard_obj:
        raise HTTPException(status_code=404, detail="Standard not found.")

    try:
        update_data = payload.model_dump(exclude_unset=True)
    except AttributeError:
        update_data = payload.dict(exclude_unset=True)

    for field, value in update_data.items():
        setattr(standard_obj, field, value)

    db.commit()
    db.refresh(standard_obj)
    return standard_obj

from html import escape
import markdown


def render_standards_booklet_html(standards) -> str:
    toc_items = []
    sections = []

    for idx, s in enumerate(standards, start=1):
        anchor = f"standard-{idx}"

        toc_items.append(
            f'<li><a href="#{anchor}">{escape(s.name)}</a></li>'
        )

        body_md = getattr(s, "summary_md", None) or getattr(s, "content_md", None) or ""
        body_html = markdown.markdown(body_md, extensions=["tables", "fenced_code"])

        effective_date = getattr(s, "effective_date", None)
        effective_text = f"<p><strong>Effective date:</strong> {escape(str(effective_date))}</p>" if effective_date else ""

        sections.append(f"""
        <section id="{anchor}" class="standard-section">
          <h1>{escape(s.name)}</h1>
          {effective_text}
          <div class="standard-body">
            {body_html}
          </div>
        </section>
        """)

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Tri-State K9 Standards Summary Booklet</title>
  <style>
    body {{
      font-family: Arial, sans-serif;
      color: #111827;
      background: white;
      margin: 0;
      padding: 0;
      font-size: 11pt;
      line-height: 1.45;
    }}

    .page {{
      padding: 0.65in;
    }}

    .cover-page {{
      height: 9.5in;
      display: flex;
      flex-direction: column;
      justify-content: center;
      text-align: center;
      page-break-after: always;
    }}

    .cover-page h1 {{
      font-size: 28pt;
      margin-bottom: 0.25in;
    }}

    .toc {{
      page-break-after: always;
    }}

    .toc h1 {{
      font-size: 20pt;
    }}

    .toc li {{
      margin: 0.15in 0;
    }}

    .cover-logo-wrap {{
        position: relative;
        height: 250px;
        margin-top: 0.35in;
    }}

    .cover-logo {{
        width: 340px;
        height: 340px;
        object-fit: contain;
        opacity: 1.0;
    }}

    .standard-section {{
      page-break-before: always;
    }}

    .standard-section h1 {{
      font-size: 18pt;
      border-bottom: 1px solid #9ca3af;
      padding-bottom: 0.1in;
      margin-bottom: 0.2in;
    }}

    h2 {{
      font-size: 14pt;
      margin-top: 0.25in;
    }}

    h3 {{
      font-size: 12pt;
      margin-top: 0.2in;
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 0.15in 0;
    }}

    th, td {{
      border: 1px solid #9ca3af;
      padding: 6px 8px;
      vertical-align: top;
    }}

    th {{
      background: #f3f4f6;
    }}

    .no-print {{
      position: sticky;
      top: 0;
      background: #111827;
      color: white;
      padding: 10px;
      text-align: right;
    }}

    .no-print button {{
      padding: 6px 12px;
      border-radius: 6px;
      border: 1px solid #6b7280;
      background: #1f2937;
      color: white;
      cursor: pointer;
    }}

    @media print {{
      .no-print {{
        display: none;
      }}

      .page {{
        padding: 0;
      }}

      @page {{
        size: letter;
        margin: 0.65in;
      }}

      a {{
        color: black;
        text-decoration: none;
      }}
    }}
  </style>
</head>
<body>
  <div class="no-print">
    <button onclick="window.print()">Print / Save PDF</button>
  </div>

  <main class="page">
    <section class="cover-page">
      <h1>Tri-State K9 Standard Summaries Booklet</h1>
      <p>Combined standard summaries document</p>
        <div class="cover-logo-wrap">
            <img src="/static/images/ts_logo_wm.png?v=2" alt="" class="cover-logo">
        </div>
    </section>

    <section class="toc">
      <h1>Table of Contents</h1>
      <ol>
        {''.join(toc_items)}
      </ol>
    </section>

    {''.join(sections)}
  </main>
</body>
</html>"""

DOCUMENTS_DIR = Path("/app/uploads")

def document_url_to_path(url: str) -> Path | None:
    if not url:
        return None

    prefix = "/api/documents/file/"
    if not url.startswith(prefix):
        return None

    filename = unquote(url.removeprefix(prefix))

    # Prevent path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        return None

    return DOCUMENTS_DIR / filename

def make_cover_page() -> BytesIO:
    buf = BytesIO()

    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter

    # Watermark logo
    try:
        logo = ImageReader("/app/static/images/ts_logo_wm.png")

        logo_size = 280

        c.drawImage(
            logo,
            (width - logo_size) / 2,
            height - 520,
            width=logo_size,
            height=logo_size,
            preserveAspectRatio=True,
            mask="auto",
        )
    except Exception:
        pass

    c.setTitle("Tri-State K9 Standards Booklet")

    c.setFillColorRGB(0.10, 0.25, 0.55)
    c.setFont("Helvetica-Bold", 28)
    c.drawCentredString(
        width / 2,
        height - 180,
        "Tri-State K9 Standards Booklet"
    )

    c.setFillColor(colors.black)
    c.setFont("Helvetica", 14)
    c.drawCentredString(
        width / 2,
        height - 220,
        "Combined Current Standards"
    )

    c.setFont("Helvetica", 10)
    c.drawCentredString(
        width / 2,
        72,
        "Generated from the TSK9SAR Standards Repository"
    )

    c.save()
    buf.seek(0)

    return buf

def make_page_number_overlay(page_num: int, width: float, height: float) -> PdfReader:
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))

    text = str(page_num)

    c.setFont("Helvetica", 9)
    c.drawCentredString(width / 2, 24, text)

    c.save()
    buf.seek(0)
    return PdfReader(buf)

def make_toc_page(standards) -> BytesIO:
    buf = BytesIO()

    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter

    c.setFont("Helvetica-Bold", 22)
    c.drawString(72, height - 72, "Table of Contents")

    y = height - 120

    c.setFont("Helvetica", 11)

    for idx, entry in enumerate(standards, start=1):
        standard = entry["standard"]
        page_num = entry["start_page"]

        c.drawRightString(
            82,
            y,
            f"{idx}."
        )

        c.drawString(
            90,
            y,
            str(standard.name or "")
        )

        c.drawRightString(
            width - 72,
            y,
            str(page_num)
        )

        y -= 18

        if y < 72:
            c.showPage()
            y = height - 72

    c.save()
    buf.seek(0)

    return buf

def page_is_blank(page) -> bool:
    text = (page.extract_text() or "").strip()
    if text:
        return False

    resources = page.get("/Resources") or {}
    xobjects = resources.get("/XObject") or {}

    # If it has images/forms, don't treat it as blank.
    if xobjects:
        return False

    return True

@router.get("/print/standards-summary-booklet", response_class=HTMLResponse)
def print_standards_booklet(
    db: Session = Depends(get_db),
    # current_user: User = Depends(get_current_user),
):
    latest = (
        db.query(
            Standard.discipline_id.label("discipline_id"),
            Standard.name.label("name"),
            func.max(Standard.effective_date).label("latest_effective_date"),
        )
        .group_by(Standard.discipline_id, Standard.name)
        .subquery()
    )
    standards = (
        db.query(Standard)
        .join(
            latest,
            and_(
                Standard.discipline_id == latest.c.discipline_id,
                Standard.name == latest.c.name,
                Standard.effective_date == latest.c.latest_effective_date,
            ),
        )
        .join(Discipline, Discipline.discipline_id == Standard.discipline_id)
        .join(DisciplineGroup, DisciplineGroup.group_id == Discipline.group_id)
        .order_by(
            DisciplineGroup.sortorder.asc(),
            Discipline.sortorder.asc(),
            Standard.name.asc(),
        )
        .all()
    )

    html = render_standards_booklet_html(standards)
    return HTMLResponse(html)


@router.get("/print/standards-booklet")
def standards_booklet_pdf(
    db: Session = Depends(get_db),
    # current_user: User = Depends(get_current_user),
):
    latest = (
        db.query(
            Standard.discipline_id.label("discipline_id"),
            Standard.name.label("name"),
            func.max(Standard.effective_date).label("latest_effective_date"),
        )
        .group_by(Standard.discipline_id, Standard.name)
        .subquery()
    )
    standards = (
        db.query(Standard)
        .join(
            latest,
            and_(
                Standard.discipline_id == latest.c.discipline_id,
                Standard.name == latest.c.name,
                Standard.effective_date == latest.c.latest_effective_date,
            ),
        )
        .join(Discipline, Discipline.discipline_id == Standard.discipline_id)
        .join(DisciplineGroup, DisciplineGroup.group_id == Discipline.group_id)
        .order_by(
            DisciplineGroup.sortorder.asc(),
            Discipline.sortorder.asc(),
            Standard.name.asc(),
        )
        .all()
    )

    writer = PdfWriter()
    skipped = []

    standard_entries = []
    current_page = 1  # cover page

    toc_pages_estimate = 1
    current_page += toc_pages_estimate

    for standard in standards:
        pdf_path = document_url_to_path(standard.url)
        if not pdf_path or not pdf_path.exists():
            continue

        reader = PdfReader(str(pdf_path))
        page_count = sum(
            1 for page in reader.pages if not page_is_blank(page)
        )

        if page_count == 0:
            continue

        standard_entries.append({
            "standard": standard,
            "start_page": current_page + 1,
            "page_count": page_count,
        })

        current_page += page_count

    toc_lines_per_page = 40

    toc_pages = max(
        1,
        math.ceil(len(standard_entries) / toc_lines_per_page)
    )

    current_page = 1 + toc_pages  # cover + toc

    for entry in standard_entries:
        entry["start_page"] = current_page + 1

        current_page += entry["page_count"]

    # 1. Add cover page
    cover_reader = PdfReader(make_cover_page())
    for page in cover_reader.pages:
        writer.add_page(page)

    # 2. Add TOC page(s)
    toc_reader = PdfReader(make_toc_page(standard_entries))
    for page in toc_reader.pages:
        writer.add_page(page)

    # 3. Add the real standards PDFs
    for standard in standards:
        pdf_path = document_url_to_path(standard.url)

        if not pdf_path or not pdf_path.exists():
            skipped.append(standard.name)
            continue

        try:
            start_page_index = len(writer.pages)

            with open(pdf_path, "rb") as f:
                reader = PdfReader(f)

                added_any_page = False

                for page in reader.pages:
                    if page_is_blank(page):
                        continue

                    writer.add_page(page)
                    added_any_page = True

                if added_any_page:
                    writer.add_outline_item(
                        title=standard.name,
                        page_number=start_page_index,
                    )

        except Exception:
            skipped.append(standard.name)

    if len(writer.pages) <= 2:
        raise HTTPException(status_code=404, detail="No standard PDF files found.")

    merged = BytesIO()
    writer.write(merged)
    merged.seek(0)

    reader = PdfReader(merged)
    numbered_writer = PdfWriter()

    for page_num, page in enumerate(reader.pages, start=1):
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)

        overlay_reader = make_page_number_overlay(page_num, width, height)
        page.merge_page(overlay_reader.pages[0])

        numbered_writer.add_page(page)

    out = BytesIO()
    numbered_writer.write(out)
    out.seek(0)

    return StreamingResponse(
        out,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="sark9-standards-booklet.pdf"'
        },
    )