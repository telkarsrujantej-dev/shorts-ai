
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/gallery", tags=["Gallery"])

CLIPS_DIR = Path(__file__).resolve().parent / "clips"

CLIP_NAME = re.compile(
    r"[a-f0-9]{32}_(?:"
    r"clip_[1-9]\d*(?:_(?:fast|quality))?"
    r"|combined_(?:fast|quality)"
    r")\.mp4"
)


class DeleteRequest(BaseModel):
    filenames: list[str] = Field(
        min_length=1,
        max_length=50
    )


@router.post("/delete")
def delete_selected(request: DeleteRequest):
    filenames = list(dict.fromkeys(request.filenames))

    # Validate ALL filenames before deleting anything.
    for filename in filenames:
        if not CLIP_NAME.fullmatch(filename):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid generated Short: {filename}"
            )

        path = CLIPS_DIR / filename

        if path.is_symlink():
            raise HTTPException(
                status_code=400,
                detail="Symbolic links cannot be deleted."
            )

    deleted = []
    not_found = []

    for filename in filenames:
        path = CLIPS_DIR / filename

        if not path.is_file():
            not_found.append(filename)
            continue

        try:
            path.unlink()
            deleted.append(filename)

        except OSError as error:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Could not delete {filename}. "
                    "Close any video players and retry."
                )
            ) from error

    return {
        "message": f"{len(deleted)} Shorts deleted.",
        "deleted": deleted,
        "not_found": not_found
    }
