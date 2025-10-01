# dispatcher.py
from __future__ import annotations
import hashlib, imghdr, mimetypes, asyncio
from typing import List, Dict, Any, Tuple
from io import BytesIO

from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from pydantic import BaseModel, Field

# Pipelines
from preprocess.image_ops import process_image, PreprocessMeta, rotate_by_angle
from extractors.gpt_vision import GptVision
from extractors.pdf_text import extract_from_pdf_bytes
from apis.api_sunat import SunatClient

# PDF raster
from pdf2image import convert_from_bytes
from PIL import Image

app = FastAPI(title="Validación de comprobantes (MVP)")

# ---------- utilidades ----------
def sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()

def guess_mime(filename: str, sample: bytes) -> str:
    # primero por extension
    mime = mimetypes.guess_type(filename)[0]
    if mime:
        return mime
    # fallback para imagen
    kind = imghdr.what(None, sample)
    if kind:
        return f"image/{kind}"
    return "application/octet-stream"

# ---------- modelos de respuesta ----------
class ItemOK(BaseModel):
    index: int
    estado: bool = True
    origen: Dict[str, Any]
    quality: Dict[str, Any] = Field(default_factory=dict)
    comp: Dict[str, Any]
    sunat: Dict[str, Any] | None = None

class ItemFail(BaseModel):
    index: int
    estado: bool = False
    origen: Dict[str, Any]
    mensaje: str

class LoteResult(BaseModel):
    data: List[ItemOK | ItemFail]

# ---------- pipelines de archivo ----------
async def _pipeline_image(index: int, filename: str, raw: bytes, gpt: GptVision) -> Dict[str, Any]:
    # Prepro
    img_bytes, meta = process_image(raw)
    # Si OSD conf baja, puedes opcionalmente preguntar orientación a GPT (omito por simplicidad; activable si lo deseas)
    # Extrae
    comp = gpt.extract(img_bytes)
    item: Dict[str, Any] = {
        "index": index,
        "estado": True,
        "origen": {"filename": filename, "mime": "image/*", "sha256": sha256_bytes(raw)},
        "quality": {
            "osd_angle": meta.osd_angle, "osd_conf": meta.osd_conf,
            "steps": meta.steps, "w": meta.width, "h": meta.height
        },
        "comp": comp
    }
    # Validación mínima local (si falta algo, lo marcamos como no procesado)
    faltantes = [k for k in ["numRuc","codComp","numeroSerie","numero","fechaEmision"] if not comp.get(k)]
    if faltantes:
        return {
            "index": index,
            "estado": False,
            "origen": item["origen"],
            "mensaje": f"campos_faltantes:{','.join(faltantes)}"
        }
    return item

async def _pipeline_pdf(index: int, filename: str, raw: bytes, gpt: GptVision) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    # 1) Intento por texto embebido (sin GPT)
    try:
        emb = extract_from_pdf_bytes(raw, filename=filename)
    except Exception:
        emb = []

    # 2) Para los que fallaron por texto, rasteriza y procesa como imagen
    to_fix = [e for e in emb if not e.estado]
    
    ok_text = [e for e in emb if e.estado]

    print("to_fix: ", len(to_fix))
    print("ok_text: ", len(ok_text))
    # Convertimos resultados ok_text a contrato final
    for e in ok_text:
        items.append({
            "index": len(items),
            "estado": True,
            "origen": {"filename": filename, "mime": "application/pdf", "pageIndex": e.pageIndex},
            "quality": {},
            "comp": e.comp
        })

    if to_fix:
        try:
            pages: List[Image.Image] = convert_from_bytes(raw, dpi=200, fmt="png")
        except Exception:
            # Si ni siquiera rasteriza, marca fallo de todo
            items.append({
                "index": len(items),
                "estado": False,
                "origen": {"filename": filename, "mime": "application/pdf"},
                "mensaje": "pdf_no_rasterizable"
            })
            return items

        for e in to_fix:
            pidx = e.pageIndex
            if pidx >= len(pages):
                items.append({
                    "index": len(items),
                    "estado": False,
                    "origen": {"filename": filename, "mime": "application/pdf", "pageIndex": pidx},
                    "mensaje": e.mensaje or "pdf_pagina_no_disponible"
                })
                continue
            # convierte PIL a bytes PNG
            buf = BytesIO()
            pages[pidx].save(buf, format="PNG")
            page_bytes = buf.getvalue()
            # reutiliza pipeline de imagen
            item = await _pipeline_image(len(items), f"{filename}#p{pidx}", page_bytes, gpt)
            # ajusta origen
            if item.get("estado", False):
                item["origen"]["mime"] = "application/pdf"
                item["origen"]["pageIndex"] = pidx
            items.append(item)

    # Si el PDF tenía texto y todos salieron fallidos, al menos devolvemos esos fallos claros
    if not emb and not items:
        items.append({
            "index": 0,
            "estado": False,
            "origen": {"filename": filename, "mime": "application/pdf"},
            "mensaje": "pdf_lectura_fallida"
        })

    return items

# ---------- ENDPOINTS ----------
@app.post("/validar-comprobante", response_model=LoteResult)
async def validar_comprobante(
    archivo: UploadFile = File(...),
    ruc_consultante: str = Form(default=None, description="Opcional: si no, usa SUNAT_RUC_CONSULTANTE"),
):
    raw = await archivo.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Archivo vacío.")
    mime = guess_mime(archivo.filename, raw)
    gpt = GptVision()

    # ruta por tipo
    if mime.startswith("image/"):
        item = await _pipeline_image(0, archivo.filename, raw, gpt)
        items = [item]
    elif mime == "application/pdf":
        items = await _pipeline_pdf(0, archivo.filename, raw, gpt)
    else:
        items = [{
            "index": 0, "estado": False,
            "origen": {"filename": archivo.filename, "mime": mime, "sha256": sha256_bytes(raw)},
            "mensaje": "tipo_no_soportado"
        }]

    # Consulta SUNAT solo para los OK
    ok_items = [i for i in items if i.get("estado") is True]
    if ok_items:
        sc = SunatClient(ruc_consultante=ruc_consultante)
        comps = [i["comp"] for i in ok_items]
        results = sc.validar_lote(comps)
        # injerta respuesta
        j = 0
        for i in items:
            if i.get("estado") is True:
                i["sunat"] = results[j]
                j += 1

    return {"data": items}

@app.post("/validar-lote", response_model=LoteResult)
async def validar_lote(
    archivos: List[UploadFile] = File(...),
    ruc_consultante: str = Form(default=None),
):
    if not archivos:
        raise HTTPException(status_code=400, detail="Sin archivos.")
    gpt = GptVision()

    # Procesamiento concurrente (limitado)
    sem = asyncio.Semaphore(6)

    async def handle_file(idx: int, up: UploadFile) -> List[Dict[str, Any]]:
        async with sem:
            raw = await up.read()
            if not raw:
                return [{"index": 0, "estado": False,
                         "origen": {"filename": up.filename},
                         "mensaje": "archivo_vacio"}]
            mime = guess_mime(up.filename, raw)
            if mime.startswith("image/"):
                it = await _pipeline_image(0, up.filename, raw, gpt)
                return [it]
            elif mime == "application/pdf":
                return await _pipeline_pdf(0, up.filename, raw, gpt)
            else:
                return [{"index": 0, "estado": False,
                         "origen": {"filename": up.filename, "mime": mime},
                         "mensaje": "tipo_no_soportado"}]

    # Ejecuta
    per_file_items = await asyncio.gather(*[handle_file(i, f) for i, f in enumerate(archivos)])
    items: List[Dict[str, Any]] = []
    for lf in per_file_items:
        for it in lf:
            # reindex global simple
            it["index"] = len(items)
            items.append(it)

    # Consulta SUNAT para los OK
    ok_items = [i for i in items if i.get("estado") is True]
    if ok_items:
        sc = SunatClient(ruc_consultante=ruc_consultante)
        comps = [i["comp"] for i in ok_items]
        results = sc.validar_lote(comps)
        j = 0
        for i in items:
            if i.get("estado") is True:
                i["sunat"] = results[j]
                j += 1

    return {"data": items}