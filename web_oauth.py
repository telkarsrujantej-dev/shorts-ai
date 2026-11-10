
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import httpx
from authlib.integrations.starlette_client import OAuth
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / ".env")

CLIENT_ID = os.environ["GOOGLE_OAUTH_CLIENT_ID"]
CLIENT_SECRET = os.environ["GOOGLE_OAUTH_CLIENT_SECRET"]
BASE_URL = os.environ["PUBLIC_BASE_URL"].rstrip("/")
cipher = Fernet(os.environ["OAUTH_FERNET_KEY"].encode())

UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
READ_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
YT_SCOPES = [UPLOAD_SCOPE, READ_SCOPE]

DB_PATH = BASE / "auth_data" / "auth.sqlite3"
DB_PATH.parent.mkdir(exist_ok=True)

router = APIRouter(prefix="/auth", tags=["Authentication"])
oauth = OAuth()

# Google sign-in: identity only
oauth.register(
    name="google_login",
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    server_metadata_url=(
        "https://accounts.google.com/"
        ".well-known/openid-configuration"
    ),
    client_kwargs={"scope": "openid email profile"},
)

# Separate permission request for YouTube
oauth.register(
    name="google_youtube",
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    authorize_url=(
        "https://accounts.google.com/o/oauth2/v2/auth"
    ),
    access_token_url="https://oauth2.googleapis.com/token",
    client_kwargs={"scope": " ".join(YT_SCOPES)},
)


@contextmanager
def database():
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


with database() as db:
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            google_sub TEXT PRIMARY KEY,
            email TEXT,
            name TEXT
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS youtube_connections (
            google_sub TEXT PRIMARY KEY,
            channel_id TEXT NOT NULL,
            channel_name TEXT NOT NULL,
            refresh_token_enc TEXT NOT NULL
        )
    """)


def require_user(request: Request):
    sub = request.session.get("google_sub")
    if not isinstance(sub, str) or not sub:
        raise HTTPException(401, "Sign in with Google first.")
    return sub


def get_connection(sub):
    with database() as db:
        row = db.execute(
            "SELECT * FROM youtube_connections "
            "WHERE google_sub = ?",
            (sub,)
        ).fetchone()
    return dict(row) if row else None


def require_same_origin(request: Request):
    if request.headers.get("origin") != BASE_URL:
        raise HTTPException(403, "Invalid request origin.")


@router.get("/google/login")
async def google_login(request: Request):
    return await oauth.google_login.authorize_redirect(
        request,
        BASE_URL + "/auth/google/callback"
    )


@router.get("/google/callback")
async def google_callback(request: Request):
    token = await oauth.google_login.authorize_access_token(
        request
    )

    # Authlib validates the OpenID Connect ID token.
    profile = token.get("userinfo")

    if not profile or not profile.get("sub"):
        raise HTTPException(401, "Google sign-in failed.")

    if not profile.get("email_verified"):
        raise HTTPException(403, "Email is not verified.")

    sub = profile["sub"]

    with database() as db:
        db.execute(
            """
            INSERT INTO users (google_sub, email, name)
            VALUES (?, ?, ?)
            ON CONFLICT(google_sub) DO UPDATE SET
                email=excluded.email,
                name=excluded.name
            """,
            (
                sub,
                profile.get("email", ""),
                profile.get("name", "")
            )
        )

    # Store only the Google account identifier in
    # the signed session cookie, not OAuth tokens.
    request.session.clear()
    request.session["google_sub"] = sub

    return RedirectResponse("/dashboard", status_code=303)


@router.get("/status")
def auth_status(request: Request):
    sub = request.session.get("google_sub")

    if not sub:
        return {"logged_in": False, "youtube_connected": False}

    with database() as db:
        user = db.execute(
            "SELECT email, name FROM users WHERE google_sub=?",
            (sub,)
        ).fetchone()

    if not user:
        return {"logged_in": False, "youtube_connected": False}

    connection = get_connection(sub)

    return {
        "logged_in": True,
        "name": user["name"],
        "email": user["email"],
        "youtube_connected": connection is not None,
        "channel_id": (
            connection["channel_id"] if connection else None
        ),
        "channel_name": (
            connection["channel_name"] if connection else None
        ),
    }


@router.get("/youtube/connect")
async def youtube_connect(request: Request):
    sub = require_user(request)

    # Bind this authorization attempt to this user.
    request.session["connecting_sub"] = sub

    return await oauth.google_youtube.authorize_redirect(
        request,
        BASE_URL + "/auth/youtube/callback",
        access_type="offline",
        prompt="consent select_account"
    )


@router.get("/youtube/callback")
async def youtube_callback(request: Request):
    sub = require_user(request)

    if request.session.pop("connecting_sub", None) != sub:
        raise HTTPException(403, "Connection session mismatch.")

    token = await oauth.google_youtube.authorize_access_token(
        request
    )

    granted = set((token.get("scope") or "").split())

    if not set(YT_SCOPES).issubset(granted):
        raise HTTPException(
            403, "Required YouTube permissions were not granted."
        )

    # Find the channel actually authorized by Google.
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={"part": "snippet", "mine": "true"},
            headers={
                "Authorization": "Bearer " + token["access_token"]
            }
        )

    if response.status_code != 200:
        raise HTTPException(
            502, "Could not verify the authorized YouTube channel."
        )

    items = response.json().get("items", [])

    if not items:
        raise HTTPException(
            400, "This Google account has no accessible YouTube channel."
        )

    channel = items[0]
    channel_id = channel["id"]
    channel_name = channel["snippet"]["title"]

    refresh_token = token.get("refresh_token")
    previous = get_connection(sub)

    # An existing refresh token may only be reused
    # when reconnecting the SAME YouTube channel.
    if (
        not refresh_token
        and previous
        and previous["channel_id"] == channel_id
    ):
        refresh_token = cipher.decrypt(
            previous["refresh_token_enc"].encode()
        ).decode()

    if not refresh_token:
        raise HTTPException(
            400, "Google did not issue offline access. Reconnect."
        )

    encrypted = cipher.encrypt(
        refresh_token.encode()
    ).decode()

    with database() as db:
        db.execute(
            """
            INSERT INTO youtube_connections
                (google_sub, channel_id, channel_name,
                 refresh_token_enc)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(google_sub) DO UPDATE SET
                channel_id=excluded.channel_id,
                channel_name=excluded.channel_name,
                refresh_token_enc=excluded.refresh_token_enc
            """,
            (sub, channel_id, channel_name, encrypted)
        )

    return RedirectResponse("/", status_code=303)


def youtube_credentials_for(request: Request):
    """Use these credentials in the publishing backend."""
    sub = require_user(request)
    connection = get_connection(sub)

    if not connection:
        raise HTTPException(401, "Connect YouTube first.")

    refresh_token = cipher.decrypt(
        connection["refresh_token_enc"].encode()
    ).decode()

    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        scopes=YT_SCOPES,
    )

    try:
        credentials.refresh(GoogleRequest())
    except Exception:
        raise HTTPException(
            401, "YouTube access expired. Please reconnect."
        )

    return credentials


@router.post("/youtube/disconnect")
async def youtube_disconnect(request: Request):
    require_same_origin(request)
    sub = require_user(request)
    connection = get_connection(sub)

    if connection:
        refresh_token = cipher.decrypt(
            connection["refresh_token_enc"].encode()
        ).decode()

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                "https://oauth2.googleapis.com/revoke",
                data={"token": refresh_token}
            )

        if response.status_code not in (200, 400):
            raise HTTPException(502, "Google revocation failed.")

        with database() as db:
            db.execute(
                "DELETE FROM youtube_connections WHERE google_sub=?",
                (sub,)
            )

    return {"disconnected": True}


@router.post("/logout")
def logout(request: Request):
    require_same_origin(request)
    request.session.clear()
    return {"logged_out": True}
