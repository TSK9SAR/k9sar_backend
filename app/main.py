from fastapi import FastAPI, Request
import logging
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.routes import (
    auth_routes,
    user_routes,
    certification_routes,
    discipline_routes,
    standard_routes,
    search_routes,
    team_routes,
    handler_routes,
    dog_routes,
    public_routes,
    dashboard, admin_delete,
)

from app.routes.discipline_group_routes import router as discipline_group_router
from app.routes.evaluator_group_routes import router as evaluator_group_router
from app.routes.evaluator_matrix_routes import router as evaluator_matrix_router 
from app.routes.profile_routes import router as profile_router
from app.routes.team_routes import router as team_router
from app.routes.dog_routes import router as dog_router
from app.routes.invite_routes import router as invites_router
from app.routes.admin_roles_routes import router as admin_roles_router
from app.routes.password_reset_routes import router as password_reset_router
from app.routes.admin_users import router as admin_users_router
from app.routes.admin_handlers import router as admin_handlers_router
from app.routes.admin_teams import router as admin_teams_router
from app.routes.admin_dogs import router as admin_dogs_router
from app.routes.documents import router as documents_router
from app.routes.handler_routes import router as handler_router
from app.routes.twofa_routes import router as twofa_router
from app.routes.public_api_routes import router as public_verify_router
from app.routes.signature_routes import router as signature_router
from app.routes.admin_affiliations import router as admin_affiliations_router
from app.routes.handler_affiliations_me import router as handler_affiliations_me_router
from app.routes.affiliations_public_routes import router as affiliations_public_router
from app.routes.affiliation_requests_supervisor import router as affiliation_requests_supervisor_router
from app.routes.admin_handler_affiliations import router as admin_handler_affiliations_router
from app.routes.affiliation_member_routes import router as affiliation_member_router
from app.routes.webauthn_routes import router as webauthn_router
from app.routes import oauth_routes
from app.routes import help_videos
from app.routes import forum
from app.routes import admin_email_campaigns
from app.routes.help import router as help_router, admin_router as admin_help_router
from app.routes import admin_forum_surveys
from app.routes import public_embeds
from app.routes import id_headshots
from app.routes import id_cards

#============================================================
# FastAPI app initialization
# ============================================================

app = FastAPI(
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

logger = logging.getLogger("k9sar")

@app.middleware("http")
async def log_auth_header(request: Request, call_next):
    auth = request.headers.get("authorization")
    logger.warning(
        "REQ %s %s auth=%s",
        request.method,
        request.url.path,
        ("none" if not auth else auth.split(" ", 1)[0] + " <present>")
    )
    return await call_next(request)

from fastapi.middleware.cors import CORSMiddleware

origins=[
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://54.218.142.97"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
)


#app = FastAPI(
#    title="K9SAR Certification Management API",
#    description="Backend service for K9 Search and Rescue member management, certifications, and standards.",
#    version="1.0.0",
#)

# ============================================================
# Database initialization
# ============================================================
Base.metadata.create_all(bind=engine)

# ============================================================
# CORS (Cross-Origin Resource Sharing) setup
# ============================================================
# origins = [
#     "http://localhost:5173",   # React dev server
#     "http://127.0.0.1:5173",
#     "http://35.88.171.10",     # Backend public IP (FastAPI on Lightsail)
#     "http://35.88.171.10:80",  # Explicit port form
# ]


# ============================================================
# Route registration
# ============================================================
# ============================================================
# Route registration
# ============================================================
 # ============================================================
# Route registration
# ============================================================

app.include_router(auth_routes.router, prefix="/api")
app.include_router(oauth_routes.router, prefix="/api")
app.include_router(user_routes.router, prefix="/api")
app.include_router(dog_routes.router, prefix="/api")
app.include_router(certification_routes.router, prefix="/api")
app.include_router(discipline_routes.router, prefix="/api")
app.include_router(standard_routes.router, prefix="/api")
app.include_router(search_routes.router, prefix="/api")
app.include_router(public_verify_router)  # <-- NO /api prefix

# ✅ Keep exactly ONE "Teams" router:
app.include_router(team_routes.router, prefix="/api") 

app.include_router(public_routes.router, prefix="/api")

# Keep these ONLY if they are genuinely different from the above:
app.include_router(dashboard.router, prefix="/api")
app.include_router(admin_delete.router, prefix="/api")

app.include_router(discipline_group_router, prefix="/api")
app.include_router(evaluator_group_router, prefix="/api")
app.include_router(evaluator_matrix_router, prefix="/api")
app.include_router(profile_router, prefix="/api", tags=["Profile"])
# app.include_router(invite_router, prefix="/api")
app.include_router(admin_roles_router, prefix="/api")
# app.include_router(password_reset_router, prefix="/api")
app.include_router(admin_users_router, prefix="/api")
app.include_router(admin_handlers_router, prefix="/api")
app.include_router(admin_teams_router, prefix="/api")
app.include_router(admin_dogs_router, prefix="/api")
app.include_router(invites_router, prefix="/api")
app.include_router(password_reset_router)
app.include_router(documents_router, prefix="/api")
app.include_router(handler_router, prefix="/api")
app.include_router(twofa_router, prefix="/api")
app.include_router(signature_router)

app.include_router(affiliation_member_router)  # <-- from affiliation_member_routes.py
app.include_router(admin_affiliations_router, prefix="/api")
app.include_router(handler_affiliations_me_router)  # <-- from handler_affiliations_me.py
app.include_router(affiliation_requests_supervisor_router)  # <-- from affiliation_requests_supervisor.py
app.include_router(affiliations_public_router)  # <-- from affiliations_public_routes.py
app.include_router(admin_handler_affiliations_router, prefix="/api")  # <-- from admin_handler_affiliations.py
app.include_router(webauthn_router, prefix="/api")  # <-- from webauthn_routes.py
app.include_router(help_videos.router, prefix="/api")  # <-- from help_videois.py
app.include_router(forum.router)
app.include_router(admin_email_campaigns.router, prefix="/api")
app.include_router(help_router, prefix="/api")
app.include_router(admin_help_router, prefix="/api")
app.include_router(admin_forum_surveys.router, prefix="/api")
app.include_router(public_embeds.router, prefix="/api")  # <-- from public_embeds.py
app.include_router(id_headshots.router, prefix="/api")
app.include_router(id_cards.router, prefix="/api")



import inspect

# print("\n=== REGISTERED /api/dogs ROUTES ===")
# for r in app.routes:
#     p = getattr(r, "path", "")
#     if p.startswith("/api/dogs"):
#         endpoint = getattr(r, "endpoint", None)
#         src = "?"
#         if endpoint:
#             try:
#                 src = f"{inspect.getsourcefile(endpoint)} :: {endpoint.__name__}"
#             except Exception:
#                 src = f"{getattr(endpoint, '__module__', '?')} :: {getattr(endpoint, '__name__', '?')}"
#         print(getattr(r, "methods", None), p, "->", src)
# print("=== END ROUTES ===\n")


# ============================================================
# Health check route
# ============================================================
@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "K9SAR backend is running."}


# ============================================================
# Root endpoint
# ============================================================
@app.get("/")
async def root():
    return {"message": "Welcome to the K9SAR Certification Management API."}
