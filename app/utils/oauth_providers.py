# app/utils/oauth_providers.py
import os
from authlib.integrations.starlette_client import OAuth
from fastapi import Request
from dotenv import load_dotenv

load_dotenv()

oauth = OAuth()

# Google provider
oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

# Microsoft provider
oauth.register(
    name="microsoft",
    client_id=os.getenv("MICROSOFT_CLIENT_ID"),
    client_secret=os.getenv("MICROSOFT_CLIENT_SECRET"),
    server_metadata_url="https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

async def get_provider_auth_url(request: Request, provider: str):
    """Return redirect URL to provider's login page."""
    if provider not in oauth:
        raise ValueError("Unsupported OAuth provider.")
    redirect_uri = os.getenv("OAUTH_REDIRECT_URI")
    return await oauth[provider].authorize_redirect(request, redirect_uri)

async def get_provider_user(request: Request, provider: str):
    """Exchange auth code for token and return user info."""
    token = await oauth[provider].authorize_access_token(request)
    user = token.get("userinfo")
    if not user:
        user = await oauth[provider].parse_id_token(request, token)
    return user
