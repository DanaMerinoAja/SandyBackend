# extractors/gpt_vision.py
from __future__ import annotations
import base64, json, os
from typing import Dict, Any, Literal, Optional

from openai import OpenAI

GPT_MODEL_ORIENT = os.getenv("OPENAI_GPT_MODEL_ORIENT", "gpt-4o-mini")
GPT_MODEL_EXTRACT = os.getenv("OPENAI_GPT_MODEL_EXTRACT", "gpt-4o-mini")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

def _to_data_url(image_bytes: bytes) -> str:
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:image/png;base64,{b64}"

class GptVision:
    """
    2 funciones:
      - detect_orientation(): consulta rápida (opcional) si OSD no es concluyente.
      - extract(): extracción final de campos en JSON SUNAT.
    """

    def __init__(self, api_key: Optional[str] = None):
        api_key = api_key or OPENAI_API_KEY
        if not api_key:
            raise RuntimeError("Falta OPENAI_API_KEY.")
        self.client = OpenAI(api_key=api_key)

    def detect_orientation(self, image_bytes: bytes) -> Literal["ok","left","right","upside-down"]:
        """
        Retorna una de: "ok" | "left" | "right" | "upside-down".
        No extrae datos, solo orientación.
        """
        data_url = _to_data_url(image_bytes)
        prompt = (
            "Tell me ONLY one token: ok | left | right | upside-down. "
            "Interpret the orientation that makes the invoice readable."
        )
        resp = self.client.chat.completions.create(
            model=GPT_MODEL_ORIENT,
            messages=[{
                "role":"user",
                "content":[
                    {"type":"text","text":prompt},
                    {"type":"image_url","image_url":{"url":data_url}}
                ]
            }],
            temperature=0
        )
        txt = (resp.choices[0].message.content or "").strip().lower()
        if "left" in txt:
            return "left"
        if "right" in txt:
            return "right"
        if "upside" in txt or "down" in txt:
            return "upside-down"
        return "ok"

    def extract(self, image_bytes: bytes) -> Dict[str, Any]:
        """
        Retorna:
        {
          "numRuc": "", "codComp": "", "numeroSerie": "",
          "numero": "", "fechaEmision": "", "monto": ""
        }
        """
        data_url = _to_data_url(image_bytes)
        prompt = (
            "Extrae de la(s) factura(s)/boleta(s) los siguientes datos y devuélvelos SOLO como JSON válido. "
            "Si falta algún dato, deja cadena vacía. "
            "1) 'codComp' SUNAT: 01 Factura, 03 Boleta, 07 Nota de crédito, 08 Nota de débito, R1 Recibo por honorarios, R7 Nota de crédito de R.H. "
            "2) 'fechaEmision' EXACTO dd/mm/yyyy. "
            "3) 'numeroSerie' an4, 'numero' numérico hasta 8. "
            "4) 'numRuc' = RUC del EMISOR (vendedor). "
            "Esquema: {\"numRuc\":\"\",\"codComp\":\"\",\"numeroSerie\":\"\",\"numero\":\"\",\"fechaEmision\":\"\",\"monto\":\"\"}"
        )
        resp = self.client.chat.completions.create(
            model=GPT_MODEL_EXTRACT,
            messages=[{
                "role":"user",
                "content":[
                    {"type":"text","text":prompt},
                    {"type":"image_url","image_url":{"url":data_url}}
                ]
            }],
            temperature=0
        )
        content = (resp.choices[0].message.content or "").strip()
        if content.startswith("```"):
            content = content.strip("`")
            if content.startswith("json"):
                content = content[4:].strip()
        data = json.loads(content)

        # normaliza
        out = {}
        for k in ["numRuc","codComp","numeroSerie","numero","fechaEmision","monto"]:
            out[k] = (str(data.get(k,"")).strip() if data.get(k) is not None else "")
        return out
