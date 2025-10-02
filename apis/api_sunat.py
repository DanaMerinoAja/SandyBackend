# integrations/sunat.py
from __future__ import annotations
import os, time, re
from typing import Dict, Any, List, Tuple, Optional

import requests

SUNAT_CLIENT_ID = os.getenv("SUNAT_CLIENT_ID")
SUNAT_CLIENT_SECRET = os.getenv("SUNAT_CLIENT_SECRET")
SUNAT_RUC_CONSULTANTE = os.getenv("SUNAT_RUC_CONSULTANTE", "")

BASE_TOKEN_URL = "https://api-seguridad.sunat.gob.pe/v1/clientesextranet/{client_id}/oauth2/token"
VALIDAR_URL_TMPL = "https://api.sunat.gob.pe/v1/contribuyente/contribuyentes/{ruc}/validarcomprobante"

def _is_valid_ruc(ruc: str) -> bool:
    return bool(re.fullmatch(r"\d{11}", ruc or ""))

class SunatTokenManager:
    """ Cachea el access_token y renueva proactivamente. """
    _cached_token: Optional[str] = None
    _expires_at: float = 0.0

    def __init__(self, client_id: Optional[str] = None, client_secret: Optional[str] = None):
        self.client_id = client_id or SUNAT_CLIENT_ID
        self.client_secret = client_secret or SUNAT_CLIENT_SECRET
        if not self.client_id or not self.client_secret:
            raise RuntimeError("Faltan SUNAT_CLIENT_ID/SUNAT_CLIENT_SECRET en el entorno.")

    def _request_token(self) -> Tuple[str, int]:
        url = BASE_TOKEN_URL.format(client_id=self.client_id)
        data = {
            "grant_type": "client_credentials",
            "scope": "https://api.sunat.gob.pe/v1/contribuyente/contribuyentes",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        resp = requests.post(url, data=data, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        return payload["access_token"], int(payload.get("expires_in", 300))

    def get_token(self) -> str:
        now = time.time()
        if self._cached_token and now < (self._expires_at - 60):  # margen 60s
            return self._cached_token
        token, expires_in = self._request_token()
        self._cached_token = token
        self._expires_at = now + expires_in
        return token

    def refresh(self) -> str:
        token, expires_in = self._request_token()
        self._cached_token = token
        self._expires_at = time.time() + expires_in
        return token

class SunatClient:
    """ Valida comprobantes (lote) y maneja el token internamente. """

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        ruc_consultante: Optional[str] = None,
    ):
        self.token_mgr = SunatTokenManager(client_id, client_secret)
        self.ruc = (ruc_consultante or SUNAT_RUC_CONSULTANTE or "").strip()
        if not _is_valid_ruc(self.ruc):
            raise RuntimeError(f"RUC consultante inválido: '{self.ruc}'")
        
    def _build_body(self, comp: Dict[str, Any]) -> Dict[str, Any]:
        body = {
            "numRuc": (comp.get("numRucE") or "").strip(),
            "codComp": (comp.get("codComp") or "").strip(),
            "numeroSerie": (comp.get("numeroSerie") or "").strip(),
            "numero": (comp.get("numero") or "").strip(),
            "fechaEmision": (comp.get("fechaEmision") or "").strip(),
        }
        monto = (comp.get("monto") or "").strip()
        if monto:
            body["monto"] = monto
        return body

    def _post_validar(self, comp: Dict[str, Any], token: str) -> requests.Response:
        url = VALIDAR_URL_TMPL.format(ruc=comp.get("numRucR"))
        body = self._build_body(comp)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        return requests.post(url, headers=headers, json=body, timeout=25)

    def validar_lote(self, comps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """ Retorna lista alineada con comps: { ok:bool, status:int, payload:dict|str, body_enviado:dict } """
        token = self.token_mgr.get_token()
        out: List[Dict[str, Any]] = []

        for comp in comps:
            resp = self._post_validar(comp, token)

            if resp.status_code == 401:
                token = self.token_mgr.refresh()
                resp = self._post_validar(comp, token)

            try:
                payload = resp.json()
            except Exception:
                payload = {"raw": resp.text}

            out.append({
                "ok": 200 <= resp.status_code < 300,
                "status": resp.status_code,
                "payload": payload,
                "data_empleada": comp,
            })

        return out