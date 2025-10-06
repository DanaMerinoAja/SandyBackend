import re, uuid
from fastapi import FastAPI, UploadFile, File, Header
from typing import List
from apis.api_sunat import SunatClient
from services.orchestator import Orchestator

app = FastAPI()

@app.post("/procesar_comprobantes")
async def procesar_comprobantes(archivos: List[UploadFile] = File(...), x_uid: str | None = Header(default=None)):
    orch = Orchestator()
    
    comprobantes_datos = await orch.proc_arch(archivos, x_uid)

    comprobantes_ok = []
    comprobantes_not_ok = []
    comprobantes_fail = []

    for comp in comprobantes_datos:

        if(comp['comp_data']['faltantes']):
            if(comp['comp_data']['faltantes'] == 0):
                comprobantes_ok.append(comp)        
            else:
                comprobantes_not_ok.append(comp)
        else:
            comprobantes_fail.append(comp)

    consultorSunat = SunatClient()

    resultados_sunat = consultorSunat.validar_lote(comprobantes_ok)

    return {"total":len(comprobantes_datos), 
            "total_ok":len(comprobantes_ok), 
            "total_not_ok":len(comprobantes_not_ok), 
            "resultados_ok": resultados_sunat, 
            "resultados_not_ok":comprobantes_not_ok,
            "fails":comprobantes_fail}

"""

@app.post("/firebase/upload")
async def simple_upload(
    files: List[UploadFile] = File(...),
    x_uid: str | None = Header(default=None),
    fb: FirebaseService = Depends(get_firebase),
):
    try:

        if not files:
            raise HTTPException(status_code=400, detail="file requerido")
        
        saved: List[Dict[str, Any]] = []
        
        for file in files:
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
            saved.append({
                "originalFilename":file.filename,
                "url": up["url"],
                "path": up["path"],
                "mime": up["mime"],
                "size": up["size"]
            })

        return saved

    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "error": "upload_failed",
            "detail": str(e)
        })
    @app.get("/api/comprobantes/{uid}")
def list_comprobantes(
    uid: str,
    limit: int = Query(20, ge=1, le=100),
    estado: Optional[str] = Query(None, description="SUBIDO|PROCESANDO|VALIDADO|OBSERVADO|RECHAZADO"),
    anio: Optional[int] = Query(None),
    mes: Optional[int] = Query(None),
    pageToken: Optional[str] = Query(None, description="id del último doc de la página previa"),
    fb: FirebaseService = Depends(get_firebase),
):
    try:
        col = fb.db.collection(f"users/{uid}/comprobantes")

        # Filtros
        q = col
        if estado:
            q = q.where("estado", "==", estado)
        if anio is not None:
            q = q.where("indices.anio", "==", anio)
        if mes is not None:
            q = q.where("indices.mes", "==", mes)

        # Orden y paginación
        q = q.order_by("createdAt", direction=gcf.Query.DESCENDING).limit(limit)

        if pageToken:
            # usamos el doc como cursor
            last_doc_ref = col.document(pageToken)
            last_snap = last_doc_ref.get()
            if last_snap.exists:
                q = q.start_after(last_snap)

        snaps = q.stream()

        items = []
        last_id = None
        for s in snaps:
            d = s.to_dict() or {}
            last_id = s.id
            # armamos un resumen útil (ajusta a gusto)
            item = {
                "id": s.id,
                "codComp": d.get("codComp", ""),
                "rucEmisor": d.get("rucEmisor", ""),
                "serie": d.get("serie", ""),
                "numero": d.get("numero", ""),
                "total": d.get("total", 0),
                "estado": d.get("estado", ""),
                "fechaEmision": d.get("fechaEmision", ""),
                "createdAt": ts_to_iso(d.get("createdAt")),
                "archivoURL": (d.get("archivos", [{}])[0] or {}).get("url"),
            }
            items.append(item)

        next_token = last_id if len(items) == limit else None

        return {
            "items": items,
            "nextPageToken": next_token
        }

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "list_failed", "detail": str(e)})
    """
