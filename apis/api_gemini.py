import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
import json
import filetype

load_dotenv()

class ExtractorGemini:
    def __init__(self):
        self.client = genai.Client()

        self.prompt = """
        Extrae de la(s) factura(s)/boleta(s) los siguientes datos y devuélvelos SOLO como JSON válido. Si falta algún dato, deja cadena vacía e indica cuántos datos no encontraste:
        1) 'codComp' SUNAT: 01 Factura, 03 Boleta, 07 Nota de crédito, 08 Nota de débito, R1 Recibo por honorarios, R7 Nota de crédito de R.H.
        2) 'fechaEmision' EXACTO dd/mm/yyyy.
        3) 'numeroSerie' an4, 'numero' numérico hasta 8.
        4) 'numRucE' = RUC del EMISOR (vendedor).
        5) 'numRucR' = RUC del RECEPTOR (comprador).
        6) 'faltantes' = CANTIDAD en NÚMERO que no lograste recuperar.
        Esquema: {"numRucE":"","numRucR":"","codComp":"","numeroSerie":"","numero":"","fechaEmision":"","monto":"","faltantes":}
        El EMISOR es la empresa que genera y envía la factura.
        """
        self.supported_image_mimes = [
            "image/jpeg",
            "image/png",
            "image/webp",
            "image/heic",
            "image/heif",
        ]
        self.supported_document_mimes = ["application/pdf"]

    async def extraer_datos(self, archivos):
        resultados = []
        for archivo in archivos:
            contenido = await archivo.read()

            detected_mime_type = None
            try:
                kind = filetype.guess(contenido)
                if kind:
                    detected_mime_type = kind.mime
            except Exception as e:
                print(f"Error al detectar el tipo de archivo para {archivo.filename}: {e}")
                pass

            mime_type_to_send = None

            if archivo.filename.lower().endswith(".pdf"):
                mime_type_to_send = "application/pdf"
            elif detected_mime_type and detected_mime_type in self.supported_image_mimes:
                mime_type_to_send = detected_mime_type
            elif archivo.filename.lower().endswith((".jpg", ".jpeg")):
                mime_type_to_send = "image/jpeg"
            elif archivo.filename.lower().endswith(".png"):
                mime_type_to_send = "image/png"
            elif archivo.filename.lower().endswith(".webp"):
                mime_type_to_send = "image/webp"

            if mime_type_to_send is None:
                resultados.append({
                    "error": f"Tipo de archivo no soportado o no detectado: {archivo.filename}. Tipo MIME detectado: {detected_mime_type}",
                    "archivo": archivo.filename
                })
                continue

            part = types.Part.from_bytes(data=contenido, mime_type=mime_type_to_send)

            try:
                response = self.client.models.generate_content(
                    model=os.getenv('GEMINI_MODEL'),
                    contents=[part, self.prompt]
                )
                if response.text:
                    raw_text = response.text
                    cleaned_text = raw_text.strip() # Eliminar espacios en blanco al inicio/fin

                    # Detectar y eliminar el bloque de código Markdown
                    if cleaned_text.startswith("```json") and cleaned_text.endswith("```"):
                        # Eliminar "```json\n" (7 caracteres) y "```" (3 caracteres)
                        cleaned_text = cleaned_text[7:-3].strip()

                    try:
                        datos = json.loads(cleaned_text) # Intentar parsear el texto limpio
                        datos['archivo'] = archivo.filename
                        resultados.append(datos)
                    except json.JSONDecodeError as e:
                        resultados.append({"error": f"Error al procesar el JSON (después de limpieza): {e}", "archivo": archivo.filename, "respuesta_bruta": raw_text, "texto_intentado_parsear": cleaned_text})
                    except Exception as e:
                        resultados.append({"error": f"Error inesperado al procesar la respuesta: {e}", "archivo": archivo.filename, "respuesta_bruta": raw_text})
                else:
                    resultados.append({"error": "No se pudo extraer información", "archivo": archivo.filename})
            except Exception as e:
                resultados.append({"error": f"{e}", "archivo": archivo.filename})

        return resultados