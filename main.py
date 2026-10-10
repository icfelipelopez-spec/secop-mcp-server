from fastapi import FastAPI, HTTPException
import httpx

app = FastAPI(title="SECOP II MCP Server", version="1.0")

SECOP_API_URL = "https://www.datos.gov.co/resource/j22f-26a3.json"

@app.get("/tools/buscar_procesos")
async def buscar_procesos_secop(
    entidad: str = None,
    objeto: str = None,
    modalidad: str = None,
    limite: int = 5,
):
    """Busca procesos de contratación en SECOP II según filtros específicos."""
    where_clauses = []

    if entidad:
        where_clauses.append(f"upper(nombre_de_la_entidad) like '%{entidad.upper()}%'")
    if objeto:
        where_clauses.append(f"upper(objeto_del_contrato) like '%{objeto.upper()}%'")
    if modalidad:
        where_clauses.append(f"upper(modalidad_de_contratacion) like '%{modalidad.upper()}%'")

    query_params = {
        "$limit": limite,
        "$order": "fecha_de_publicacion_del_proceso DESC",
    }

    if where_clauses:
        query_params["$where"] = " AND ".join(where_clauses)

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(SECOP_API_URL, params=query_params, timeout=10.0)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    resultados = []
    for item in data:
        resultados.append(
            {
                "id_proceso": item.get("id_del_proceso"),
                "referencia": item.get("referencia_del_proceso"),
                "entidad": item.get("nombre_de_la_entidad"),
                "objeto": item.get("objeto_del_contrato"),
                "fase": item.get("fase"),
                "precio_base": item.get("precio_base"),
                "modalidad": item.get("modalidad_de_contratacion"),
                "fecha_publicacion": item.get("fecha_de_publicacion_del_proceso"),
                "url_proceso": item.get("urlproceso", {}).get("url") if isinstance(item.get("urlproceso"), dict) else item.get("urlproceso"),
            }
        )

    return {"status": "success", "data": resultados}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
