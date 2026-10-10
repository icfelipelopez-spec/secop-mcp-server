import os
import httpx
from fastapi import FastAPI
from mcp.server.mcpserver import MCPServer

# Inicializar MCPServer (Sintaxis compatible con mcp 2.x)
mcp = MCPServer("SECOP II Server")

@mcp.tool()
async def buscar_procesos_secop(
    entidad: str = None,
    objeto: str = None,
    modalidad: str = None,
    limite: int = 5
) -> str:
    """Busca procesos de contratación pública en SECOP II según filtros específicos."""
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
            respuesta = await cliente.get(url, params=parametros_de_consulta, timeout=10.0)
            respuesta.raise_for_status()
            datos = respuesta.json()
        except Exception as e:
            return f"Error al consultar la API de SECOP II: {str(e)}"

    if not datos:
        return "No se encontraron procesos de contratación con los criterios especificados."

    resultados = []
    for articulo in datos:
        url_p = articulo.get("urlproceso")
        link = url_p.get("url") if isinstance(url_p, dict) else url_p
        
        item = (
            f"• ID Proceso: {articulo.get('id_del_proceso', 'N/A')}\n"
            f"  Entidad: {articulo.get('nombre_de_la_entidad', 'N/A')}\n"
            f"  Objeto: {articulo.get('objeto_del_contrato', 'N/A')}\n"
            f"  Modalidad: {articulo.get('modalidad_de_contratacion', 'N/A')}\n"
            f"  Cuantía/Precio Base: ${articulo.get('precio_base', 'N/A')}\n"
            f"  Estado/Fase: {articulo.get('fase', 'N/A')}\n"
            f"  Fecha Publicación: {articulo.get('fecha_de_publicacion_del_proceso', 'N/A')}\n"
            f"  Enlace: {link if link else 'N/A'}"
        )
        resultados.append(item)

    return "\n\n".join(resultados)

# Crear aplicación FastAPI
app = FastAPI(title="Servidor SECOP II MCP")

@app.get("/")
async def raiz():
    return {"mensaje": "Servidor SECOP II MCP en vivo", "estado": "OK"}

# Exponer el endpoint de MCP
app.mount("/mcp", mcp.sse_app())
