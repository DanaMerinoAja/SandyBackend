# app/main.py (snippet mínimo)
import re, uuid
from fastapi import FastAPI, Depends, UploadFile, File, Header, HTTPException
from fastapi.responses import JSONResponse

from services.deps import get_firebase
from services.firebase_service import FirebaseService

app = FastAPI(title="Comprobantes API - Simple Upload")

def sanitize_filename(name: str) -> str:
    name = name or "archivo"
    name = re.sub(r"[^\w.\-]", "_", name)
    return re.sub(r"_+", "_", name).lower()

@app.post("/api/upload")
async def simple_upload(
    file: UploadFile = File(...),
    x_uid: str | None = Header(default=None),
    fb: FirebaseService = Depends(get_firebase),
):
    try:
        if not file:
            raise HTTPException(status_code=400, detail="file requerido")

        uid = x_uid or "demo-uid"
        comp_id = str(uuid.uuid4())
        safe_name = sanitize_filename(file.filename or "archivo")
        object_path = f"uploads/users/{uid}/{comp_id}/{safe_name}"

        contents = await file.read()
        up = fb.upload_bytes_and_url(
            object_path,
            contents,
            content_type=file.content_type or "application/octet-stream"
        )

        # Devuelves SOLO lo esencial
        return {
            "originalFilename":file.filename,
            "url": up["url"],
            "path": up["path"],
            "mime": up["mime"],
            "size": up["size"]
        }

    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "error": "upload_failed",
            "detail": str(e)
        })
