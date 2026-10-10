import httpx
from fastapi import FastAPI
from mcp.server.mcpserver import MCPServer

# Inicializar MCPServer con la versión estándar compatible
mcp = MCPServer("SECOP_FL")

@mcp.tool()
async def buscar_procesos_secop(
    entidad: str | None = None,
    objeto: str | None = None,
    modalidad: str | None = None,
    limite: int = 5
) -> str:
    """Busca procesos de contratación pública en Colombia en la base de datos abierta de SECOP II."""
    url = "https://www.datos.gov.co/resource/p6dx-8zbt.json"
    
    filtros = []
    if entidad and entidad.strip():
        val = entidad.strip().upper().replace("'", "''")
        filtros.append(f"upper(entidad) like '%{val}%'")
    if objeto and objeto.strip():
        val = objeto.strip().upper().replace("'", "''")
        filtros.append(f"upper(descripci_n_del_procedimiento) like '%{val}%'")
    if modalidad and modalidad.strip():
        val = modalidad.strip().upper().replace("'", "''")
        filtros.append(f"upper(modalidad_de_contratacion) like '%{val}%'")

    limite = max(1, min(limite, 100))
    parametros = {
        "$limit": limite,
        "$order": "fecha_de_publicacion_del DESC",
    }
    if filtros:
        parametros["$where"] = " AND ".join(filtros)

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as cliente:
        try:
            respuesta = await cliente.get(url, params=parametros)
            respuesta.raise_for_status()
            datos = respuesta.json()
        except Exception as e:
            return f"Error al consultar la API de SECOP II: {str(e)}"

    if not datos or not isinstance(datos, list):
        return "No se encontraron procesos de contratación con los criterios especificados."

    resultados = []
    for articulo in datos:
        url_proceso = articulo.get("urlproceso")
        if isinstance(url_proceso, dict):
            enlace = url_proceso.get("url") or url_proceso.get("value")
        else:
            enlace = url_proceso

        item = (
            f"ID del proceso: {articulo.get('id_del_proceso', 'N/A')}\n"
            f"Entidad: {articulo.get('entidad', 'N/A')}\n"
            f"Procedimiento: {articulo.get('nombre_del_procedimiento', 'N/A')}\n"
            f"Objeto: {articulo.get('descripci_n_del_procedimiento', 'N/A')}\n"
            f"Modalidad: {articulo.get('modalidad_de_contratacion', 'N/A')}\n"
            f"Precio base: ${articulo.get('precio_base', 'N/A')}\n"
            f"Fase: {articulo.get('fase', 'N/A')}\n"
            f"Fecha de publicación: {articulo.get('fecha_de_publicacion_del', 'N/A')}\n"
            f"Enlace: {enlace or 'N/A'}"
        )
        resultados.append(item)

    return "\n\n".join(resultados)

# Crear aplicación FastAPI y montar el SSE de MCPServer
app = FastAPI(title="SECOP II MCP Server", version="1.0.0")

@app.get("/")
async def raiz():
    return {"estado": "activo", "servicio": "SECOP II MCP Server"}

# Montar la aplicación SSE nativa
app.mount("/mcp", mcp.sse_app())
