import os
import httpx
from fastapi import FastAPI, Query

app = FastAPI(
    title="SECOP II Contratación Pública",
    description="API para buscar procesos de contratación pública en Colombia a través de SECOP II.",
    version="1.0.0"
)

@app.get("/", summary="Estado del servidor")
async def raiz():
    return {"estado": "activo", "servicio": "SECOP II API MCP"}

@app.get("/buscar_procesos", summary="Buscar procesos de contratación en SECOP II")
async def buscar_procesos_secop(
    entidad: str = Query(None, description="Nombre o parte del nombre de la entidad estatal"),
    objeto: str = Query(None, description="Palabra clave en el objeto del contrato"),
    modalidad: str = Query(None, description="Modalidad de contratación (ej. Licitación pública, Selección abreviada)"),
    limite: int = Query(5, description="Número máximo de resultados a retornar")
):
    """Busca procesos de contratación pública en Colombia en la base de datos abierta de SECOP II."""
    url = "https://www.datos.gov.co/resource/j22f-26a3.json"
    
    clasulas_donde = []
    if entidad:
        clasulas_donde.append(f"upper(nombre_de_la_entidad) like '%{entidad.upper()}%'")
    if objeto:
        clasulas_donde.append(f"upper(objeto_del_contrato) like '%{objeto.upper()}%'")
    if modalidad:
        clasulas_donde.append(f"upper(modalidad_de_contratacion) like '%{modalidad.upper()}%'")

    parametros_de_consulta = {
        "$limit": limite,
        "$order": "fecha_de_publicacion_del_proceso DESC",
    }

    if clasulas_donde:
        parametros_de_consulta["$where"] = " AND ".join(clasulas_donde)

    async with httpx.AsyncClient() as cliente:
        try:
            respuesta = await cliente.get(url, params=parametros_de_consulta, timeout=15.0)
            respuesta.raise_for_status()
            datos = respuesta.json()
        except Exception as e:
            return {"error": f"Error al consultar la API de SECOP II: {str(e)}"}

    if not datos:
        return {"mensaje": "No se encontraron procesos de contratación con los criterios especificados."}

    resultados = []
    for articulo in datos:
        url_p = articulo.get("urlproceso")
        link = url_p.get("url") if isinstance(url_p, dict) else url_p
        
        resultados.append({
            "id_proceso": articulo.get('id_del_proceso', 'N/A'),
            "entidad": articulo.get('nombre_de_la_entidad', 'N/A'),
            "objeto": articulo.get('objeto_del_contrato', 'N/A'),
            "modalidad": articulo.get('modalidad_de_contratacion', 'N/A'),
            "precio_base": articulo.get('precio_base', 'N/A'),
            "estado": articulo.get('fase', 'N/A'),
            "fecha_publicacion": articulo.get('fecha_de_publicacion_del_proceso', 'N/A'),
            "enlace": link if link else 'N/A'
        })

    return {"total_encontrados": len(resultados), "procesos": resultados}
