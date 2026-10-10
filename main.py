from fastapi import FastAPI, Request, Response
from mcp.server.fastmcp import FastMCP
from mcp.server.sse import SseServerTransport
import mcp.types as types

# 1. Crear la instancia de FastMCP con el nombre de tu servicio
mcp = FastMCP("SECOP-Colombia-Server")

# 2. Definir las herramientas del servidor (ej. consulta de procesos en SECOP II)
@mcp.tool()
async def buscar_procesos_secop(termino: str) -> str:
    """Busca procesos de contratación en SECOP II."""
    # Aquí puedes integrar la lógica de consulta (Socrata API, scraping o análisis local)
    return f"Resultados estructurados para el proceso o término: {termino}"

# 3. Inicializar la aplicación principal de FastAPI
app = FastAPI(title="SECOP II MCP Server", version="1.0.0")

# 4. Configurar el transporte SSE apuntando explícitamente a la ruta de conexión
sse_transport = SseServerTransport("/mcp/sse")

@app.get("/")
async def raiz():
    """Health check básico para verificar el estado de la aplicación en Render."""
    return {"status": "activo", "servicio": "SECOP II MCP Server - SseServerTransport"}

# 5. Endpoint GET para establecer la conexión inicial por Stream (SSE)
@app.get("/mcp/sse")
async def handle_sse_connect(request: Request):
    """Maneja el flujo de eventos enviados por el servidor (Server-Sent Events)."""
    async with sse_transport.connect_handle(request.scope, request.receive, request._send) as queue:
        await sse_transport.handle_sse_request(request, queue)
    return Response(status_code=200)

# 6. Endpoint POST para recibir los comandos, llamadas a herramientas y mensajes del cliente
@app.post("/mcp/sse")
async def handle_sse_messages(request: Request):
    """Procesa las peticiones POST enviadas por el cliente MCP evitando el error 405."""
    await sse_transport.handle_post_request(request)
    return Response(status_code=200)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
