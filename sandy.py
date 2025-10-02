from fastapi import FastAPI, File, UploadFile
from typing import List
from apis.api_gemini import ExtractorGemini
from apis.api_sunat import SunatClient

app = FastAPI()

@app.post("/procesar_comprobantes")
async def procesar_comprobantes(archivos: List[UploadFile] = File(...)):
    extractor = ExtractorGemini()
    
    comprobantes_datos = await extractor.extraer_datos(archivos)

    comprobantes_ok = [comps_ok for comps_ok in comprobantes_datos if comps_ok['faltantes'] == 0]
    comprobantes_not_ok = [comps_ok for comps_ok in comprobantes_datos if comps_ok['faltantes'] != 0]

    consultorSunat = SunatClient()

    resultados_sunat = consultorSunat.validar_lote(comprobantes_ok)

    return {"total":len(comprobantes_datos), 
            "total_ok":len(comprobantes_ok), 
            "total_not_ok":len(comprobantes_not_ok), 
            "resultados_ok": resultados_sunat, 
            "resultados_not_ok":comprobantes_not_ok}
