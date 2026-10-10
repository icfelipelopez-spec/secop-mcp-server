import requests
import sseclient
import pandas as pd

class MCPAgent:
    def __init__(self, base_url):
        self.base_url = base_url

    def listen_events(self):
        """
        Conecta al servidor MCP vía SSE y escucha eventos en tiempo real.
        """
        try:
            response = requests.get(self.base_url, stream=True)
            client = sseclient.SSEClient(response)
            for event in client.events():
                print(f"Evento recibido: {event.data}")
                # Aquí puedes procesar cada evento según tu lógica
        except Exception as e:
            print(f"Error al conectar con MCP: {e}")

    def process_event(self, event_data):
        """
        Procesa un evento recibido y lo convierte en DataFrame para análisis.
        """
        try:
            df = pd.DataFrame([event_data])
            # Ejemplo de auditoría: verificar si existe campo 'valor'
            if 'valor' in df.columns:
                df['valor_valido'] = df['valor'].apply(lambda x: x > 0)
            return df
        except Exception as e:
            print(f"Error procesando evento: {e}")
            return None

if __name__ == "__main__":
    agent = MCPAgent("https://secop-mcp-server-sxyq.onrender.com/mcp/sse")
    agent.listen_events()
