import httpx
from mcp.server.mcpserver import MCPServer

# 1. Inicializar MCPServer (clase oficial en MCP 2.x)
mcp = MCPServer("SECOP-Colombia-Server")

SECOP_II_DATASET_ID = "p6dx-8zbt"
BASE_URL = f"https://www.datos.gov.co/resource/{SECOP_II_DATASET_ID}.json"

# 2. Definición de la Herramienta con el decorador nativo
@mcp.tool()
async def buscar_procesos_secop(
    termino: str, 
    departamento: str = None, 
    limite: int = 5
) -> str:
    """
    Busca procesos de contratación en SECOP II de Colombia por palabra clave.
    
    :param termino: Palabra clave a buscar en el objeto del proceso (ej. 'software', 'vigilancia').
    :param departamento: Opcional. Filtrar por departamento (ej. 'Bogotá D.C.', 'Antioquia').
    :param limite: Cantidad máxima de registros a retornar (por defecto 5).
    """
    where_clause = f"(lower(nombre_de_la_entidad) like '%{termino.lower()}%' or lower(descripcion_del_procedimiento) like '%{termino.lower()}%')"
    
    if departamento:
        where_clause += f" and departamento = '{departamento.upper()}'"
        
    params = {
        "$where": where_clause,
        "$limit": limite,
        "$order": "fecha_de_publicacion_del_proceso DESC"
    }
    
    headers = {
        "Accept": "application/json"
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(BASE_URL, params=params, headers=headers, timeout=15.0)
            response.raise_for_status()
            data = response.json()
            
            if not data:
                return f"No se encontraron procesos recientes con el término '{termino}'."
            
            resultado = []
            for proceso in data:
                item = (
                    f"🏢 **Entidad:** {proceso.get('nombre_de_la_entidad', 'N/A')}\n"
                    f"🆔 **ID Proceso:** {proceso.get('id_del_proceso', 'N/A')}\n"
                    f"📝 **Objeto:** {proceso.get('descripcion_del_procedimiento', 'N/A')}\n"
                    f"💰 **Valor Estimado:** ${proceso.get('precio_base', 'No definido')}\n"
                    f"📌 **Fase:** {proceso.get('fase', 'N/A')} | **Estado:** {proceso.get('estado_del_procedimiento', 'N/A')}\n"
                    f"📅 **Publicación:** {proceso.get('fecha_de_publicacion_del_proceso', 'N/A')}\n"
                    f"{'-'*40}"
                )
                resultado.append(item)
                
            return "\n\n".join(resultado)
            
        except httpx.HTTPStatusError as e:
            return f"Error al consultar la API de Datos Abiertos: {e.response.status_code}"
        except Exception as e:
            return f"Ocurrió un error inesperado: {str(e)}"

# 3. Exponer la aplicación web nativa de MCPServer
# Esto configura automáticamente /sse y /messages sin conflictos de ASGI
app = mcp.sse_app()
