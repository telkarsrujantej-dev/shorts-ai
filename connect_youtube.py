
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

BASE_DIR = Path(__file__).resolve().parent

CLIENT_FILE = BASE_DIR / "youtube_client_secret.json"
TOKEN_FILE = BASE_DIR / "secrets" / "youtube_token.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
if not CLIENT_FILE.is_file():
    raise SystemExit(
        "youtube_client_secret.json was not found "
        "in the project folder."
    )

TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)

flow = InstalledAppFlow.from_client_secrets_file(
    str(CLIENT_FILE),
    scopes=SCOPES,
)

credentials = flow.run_local_server(
    host="localhost",
    port=0,
    open_browser=True,
    access_type="offline",
    prompt="consent",
)

TOKEN_FILE.write_text(
    credentials.to_json(),
    encoding="utf-8"
)

print("YouTube authorization completed successfully!")
