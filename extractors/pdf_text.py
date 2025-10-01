# extractors/pdf_text.py
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple

import re
import pdfplumber

RUC_RE = re.compile(r"(?<!\d)(1|2)\d{10}(?!\d)")
FECHA_RE = re.compile(r"\b(0[1-9]|[12]\d|3[01])/(0[1-9]|1[0-2])/\d{4}\b")
# Serie-num: F001-00012345 / B1 12345 / etc.
SERIE_NUM_RE = re.compile(r"([A-Z0-9]{1,4})[-\s]?(\d{1,8})")
MONTO_RE = re.compile(r"(?<!\d)(\d{1,7}[.,]\d{2})(?!\d)")

def _find_codcomp_by_keywords(text: str) -> str:
    t = text.upper()
    if "FACTURA" in t:
        return "01"
    if "BOLETA" in t:
        return "03"
    if "NOTA DE CR" in t or "NOTA DE CRÉDITO" in t:
        return "07"
    if "NOTA DE D" in t or "NOTA DE DÉBITO" in t:
        return "08"
    if "RECIBO POR HONORARIOS" in t:
        return "R1"
    return ""

def _norm_monto(s: str) -> str:
    s = s.replace(" ", "")
    # normaliza coma a punto
    s = s.replace(",", ".")
    return s

@dataclass
class PdfItemResult:
    index: int
    pageIndex: int
    estado: bool
    comp: Optional[Dict[str, Any]] = None
    mensaje: Optional[str] = None
    origen: Optional[Dict[str, Any]] = None

def extract_from_pdf_bytes(pdf_bytes: bytes, filename: str = "upload.pdf") -> List[PdfItemResult]:
    """
    Intenta extraer por texto embebido (sin GPT). Si no consigue campos mínimos,
    marca estado:false y deja que el orquestador decida rasterizar esa página.
    Un PDF puede producir varios items (uno por página/comprobante).
    """
    results: List[PdfItemResult] = []
    with pdfplumber.open(fp=pdf_bytes) as pdf:
        for i, page in enumerate(pdf.pages):
            try:
                txt = page.extract_text() or ""
            except Exception:
                txt = ""

            if not txt.strip():
                results.append(PdfItemResult(
                    index=len(results), pageIndex=i, estado=False,
                    mensaje="pdf_sin_texto_embebido",
                    origen={"filename": filename, "pageIndex": i, "mime": "application/pdf"}
                ))
                continue

            numRuc = (RUC_RE.search(txt).group(0) if RUC_RE.search(txt) else "")
            fecha = (FECHA_RE.search(txt).group(0) if FECHA_RE.search(txt) else "")
            codComp = _find_codcomp_by_keywords(txt)

            # serie/numero: toma el primer match razonable que no parezca RUC/fecha
            serie, numero = "", ""
            m = SERIE_NUM_RE.search(txt.replace("\n", " "))
            if m:
                serie, numero = m.group(1), m.group(2)

            monto = ""
            m2 = MONTO_RE.findall(txt)
            if m2:
                # heurística: tomar el último monto del documento suele ser el total
                monto = _norm_monto(m2[-1])

            comp = {
                "numRuc": numRuc,
                "codComp": codComp,
                "numeroSerie": serie,
                "numero": numero,
                "fechaEmision": fecha,
                "monto": monto
            }

            faltantes = [k for k in ["numRuc","codComp","numeroSerie","numero","fechaEmision"] if not comp.get(k)]
            if faltantes:
                results.append(PdfItemResult(
                    index=len(results), pageIndex=i, estado=False,
                    mensaje=f"campos_faltantes:{','.join(faltantes)}",
                    origen={"filename": filename, "pageIndex": i, "mime": "application/pdf"}
                ))
                continue

            results.append(PdfItemResult(
                index=len(results), pageIndex=i, estado=True, comp=comp,
                origen={"filename": filename, "pageIndex": i, "mime": "application/pdf"}
            ))
    return results
