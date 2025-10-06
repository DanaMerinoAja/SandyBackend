
# app/services/firebase_service.py
from __future__ import annotations
import re, uuid
from typing import Any, Dict, Optional
from urllib.parse import quote
import os
from dotenv import load_dotenv

import firebase_admin
from firebase_admin import credentials, firestore, storage as fb_storage

load_dotenv()

FB_STORAGE_BUCKET = os.getenv("FB_STORAGE_BUCKET", "")
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")

class FirebaseService:
    """
    Servicio encapsulado de Firebase (Firestore + Storage).
    Se inicializa UNA sola vez por proceso.
    """
    _instance: Optional["FirebaseService"] = None

    def __init__(self) -> None:
        if not firebase_admin._apps:
            # Si tienes Application Default Credentials, bastaría credential=ApplicationDefault()
            cred = credentials.ApplicationDefault() if not GOOGLE_APPLICATION_CREDENTIALS else credentials.Certificate(GOOGLE_APPLICATION_CREDENTIALS)
            firebase_admin.initialize_app(cred, {"storageBucket": FB_STORAGE_BUCKET})
        self.db = firestore.client()
        self.bucket = fb_storage.bucket()

    @classmethod
    def instance(cls) -> "FirebaseService":
        if cls._instance is None:
            cls._instance = FirebaseService()
        return cls._instance

    # -------- Helpers Storage --------
    @staticmethod
    def _download_url(bucket_name: str, object_path: str, token: str) -> str:
        return f"https://firebasestorage.googleapis.com/v0/b/{bucket_name}/o/{quote(object_path, safe='')}?alt=media&token={token}"

    def upload_bytes_and_url(self, object_path: str, data: bytes, content_type: str = "application/octet-stream") -> Dict[str, Any]:
        """
        Sube bytes a Storage y retorna metadatos + URL estable (tokenizada).
        """
        blob = self.bucket.blob(object_path)
        blob.upload_from_string(data, content_type=content_type)

        token = str(uuid.uuid4())
        md = blob.metadata or {}
        md["firebaseStorageDownloadTokens"] = token
        blob.metadata = md
        blob.patch()

        blob.reload()
        return {
            "bucket": self.bucket.name,
            "path": object_path,
            "size": blob.size,
            "mime": blob.content_type,
            "url": self._download_url(self.bucket.name, object_path, token),
        }

    # -------- Firestore: Comprobantes --------
    def save_comprobante(self, uid: str, comp_id: str, payload: Dict[str, Any]) -> str:
        ref = self.db.document(f"users/{uid}/comprobantes/{comp_id}")
        ref.set(payload, merge=True)
        return ref.path

    def get_comprobante(self, uid: str, comp_id: str) -> Optional[Dict[str, Any]]:
        snap = self.db.document(f"users/{uid}/comprobantes/{comp_id}").get()
        return snap.to_dict() if snap.exists else None
    

    async def simple_upload(self, x_uid:str, content:bytes, filename:str, content_type:str):
        print("El problemas es \"filename\"")
        try:
            print("ejecutando simple upload para: ", filename)
            uid = x_uid or "demo-uid"
            comp_id = str(uuid.uuid4())
            safe_name = self.sanitize_filename(filename or "archivo")
            object_path = f"uploads/users/{uid}/{comp_id}/{safe_name}"

            print("alosihola1")

            up = self.upload_bytes_and_url(
                object_path,
                content,
                content_type or "application/octet-stream"
            )

            print(up)

            print("alosihola")

            return {
                        "originalFilename":filename,
                        "url": up["url"],
                        "obs": "OK"
                    }

        except Exception as e:
            return {
                        "originalFilename":filename,
                        "obs": e
                    }
   
    def sanitize_filename(name: str) -> str:
        name = name or "archivo"
        name = re.sub(r"[^\w.\-]", "_", name)
        return re.sub(r"_+", "_", name).lower()
