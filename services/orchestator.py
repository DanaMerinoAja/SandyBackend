from apis.api_gemini import ExtractorGemini
from services.firebase_service import FirebaseService

from io import BytesIO
import asyncio

class Orchestator:

    
    def __init__(self):
        self.extractor = ExtractorGemini()
        self.firebase = FirebaseService()

    async def proc_arch(self, archivos, x_uid: str):
        comprobantes = []

        for archivo in archivos:
            # Snapshot de metadatos
            content_type = getattr(archivo, "content_type", None) or "application/octet-stream"

            # Leer una sola vez
            data = await archivo.read()

            # Lanzar en paralelo usando los mismos bytes
            comp_task = asyncio.create_task(self.extractor.extraer_datos(data, archivo.filename))
            up_task   = asyncio.create_task(self.firebase.simple_upload(x_uid, data, archivo.filename, content_type))

            comp, url = await asyncio.gather(comp_task, up_task, return_exceptions=True)

            comprobantes.append({
                "nom_archivo": archivo.filename,
                "comp_data": comp,
                "almacenado": url
            })

        return comprobantes

    if __name__ == "__main__":
        asyncio.run(proc_arch())