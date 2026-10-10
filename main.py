import httpx
from fastapi import FastAPI, Request, Response
from mcp.server import Server
from mcp.server.sse import SseServerTransport
import mcp.types as types

app = FastAPI(title="SECOP II MCP Server")

# Inicializar servidor MCP oficial
server = Server("SECOP_FL")

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="buscar_procesos_secop",
            description="Busca procesos de contratación pública en Colombia en la base de datos abierta de SECOP II.",
            inputSchema={
                "type": "object",
                "properties": {
                    "entidad": {"type": "string", "description": "Nombre o parte del nombre de la entidad estatal"},
                    "objeto": {"type": "string", "description": "Palabra clave en el objeto del contrato"},
                    "modalidad": {"type": "string", "description": "Modalidad de contratación"},
                    "limite": {"type": "integer", "description": "Número máximo de resultados", "default": 5}
                }
            }
        )
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name != "buscar_procesos_secop":
        raise ValueError(f"Herramienta desconocida: {name}")

    entidad = arguments.get("entidad")
    objeto = arguments.get("objeto")
    modalidad = arguments.get("modalidad")
    limite = arguments.get("limite", 5)

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
            return [types.TextContent(type="text", text=f"Error al consultar la API de SECOP II: {str(e)}")]

    if not datos:
        return [types.TextContent(type="text", text="No se encontraron procesos de contratación con los criterios especificados.")]

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

    return [types.TextContent(type="text", text="\n\n".join(resultados))]

# Configurar transporte SSE oficial
sse = SseServerTransport("/mcp/messages")

@app.get("/mcp/sse")
async def handle_sse(request: Request):
    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
        await server.run(streams[0], streams[1], server.create_initialization_options())

@app.post("/mcp/messages")
async def handle_messages(request: Request):
    await sse.handle_post_message(request.scope, request.receive, request._send)
    return Response(status_code=200)

@app.get("/")
async def raiz():
    return {"estado": "activo", "servicio": "SECOP II MCP SSE Server"}
