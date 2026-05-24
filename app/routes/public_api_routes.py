from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Certification

# Import your existing helpers (adjust these imports to where they really live)
from app.routes.certification_routes import compute_seal_hash, short_code, standing_for  # <-- adjust if needed

router = APIRouter()

@router.get("/verify/cert/{cert_id}", response_class=HTMLResponse)
def public_verify_page(cert_id: int, db: Session = Depends(get_db)):
    cert = (
        db.query(Certification)
        .filter(Certification.certification_id == cert_id)
        .first()
    )
    if not cert:
        return HTMLResponse(
            "<h2 style='font-family:system-ui;margin:40px'>Certificate not found</h2>",
            status_code=404,
        )

    stored = getattr(cert, "seal_hash", None)
    if not stored:
        integrity = "UNSEALED"
    else:
        computed = compute_seal_hash(cert=cert)
        integrity = "VALID" if computed == stored else "TAMPERED"

    standing = standing_for(cert)
    code = short_code(stored) if stored else "—"

    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Certificate Verification #{cert_id}</title>
  <style>
    body {{ font-family: system-ui, -apple-system, sans-serif; background:#f8fafc; margin:0; }}
    .wrap {{ max-width:760px; margin:40px auto; padding:0 16px; }}
    .card {{ background:#fff; border-radius:16px; padding:22px; box-shadow:0 10px 30px rgba(0,0,0,.08); }}
    h1 {{ margin:0 0 8px; font-size:22px; }}
    .muted {{ color:#64748b; font-size:14px; }}
    .badge {{ display:inline-block; color:#fff; padding:8px 12px; border-radius:999px; font-weight:700; font-size:13px; margin-right:8px; margin-top:10px; }}
    hr {{ border:none; border-top:1px solid #e2e8f0; margin:18px 0; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>Certificate Verification #{cert_id}</h1>
      <div class="muted">Validation ID: <strong>{code}</strong></div>

      <div>
        <span class="badge" style="background:{'#16a34a' if integrity=='VALID' else '#dc2626' if integrity=='TAMPERED' else '#ca8a04'}">
          Integrity: {integrity}
        </span>
        <span class="badge" style="background:{'#16a34a' if standing=='ACTIVE' else '#dc2626' if standing=='REVOKED' else '#ca8a04'}">
          Standing: {standing}
        </span>
      </div>

      <hr/>
      <div class="muted">
        This page verifies authenticity (digital seal) and standing (active/suspended/revoked/expired).
      </div>
    </div>
  </div>
</body>
</html>"""
    return HTMLResponse(html)