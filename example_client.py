"""
Ejemplo de cliente para la API REST de Discord Exporter Pro
"""

import requests
import json
from typing import Dict, Optional

class DiscordExporterClient:
    """Cliente para interactuar con la API de Discord Exporter Pro"""
    
    def __init__(self, base_url: str = "http://localhost:5000"):
        self.base_url = base_url
        self.session = requests.Session()
    
    def health_check(self) -> bool:
        """Verifica si la API está activa"""
        try:
            response = self.session.get(f"{self.base_url}/api/health")
            return response.status_code == 200
        except:
            return False
    
    def get_info(self) -> Dict:
        """Obtiene información sobre los endpoints"""
        response = self.session.get(f"{self.base_url}/api/info")
        response.raise_for_status()
        return response.json()
    
    def export_channel(
        self,
        token: str,
        channel_id: str,
        output_dir: str = "exports",
        limit: int = 100,
        save_frequency: int = 1000,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        format_discord_kit: bool = False,
        custom_filename: Optional[str] = None,
        export_json_raw: bool = True,
        export_jsonl: bool = True,
        export_txt: bool = True,
        export_csv: bool = True,
        export_html: bool = True
    ) -> Dict:
        """
        Exporta mensajes de un canal de Discord
        
        Args:
            token: Token de Discord
            channel_id: ID del canal
            output_dir: Carpeta de salida
            limit: Mensajes por request (1-100)
            save_frequency: Frecuencia de guardado
            start_date: Fecha inicial (ej: "2024-01-15")
            end_date: Fecha final (ej: "2024-01-20")
            format_discord_kit: Exportar en formato Discord Kit
            custom_filename: Nombre personalizado
            export_json_raw: Exportar JSON raw
            export_jsonl: Exportar JSONL
            export_txt: Exportar TXT
            export_csv: Exportar CSV
            export_html: Exportar HTML
        
        Returns:
            Respuesta de la API con información de los archivos generados
        """
        payload = {
            "token": token,
            "channel_id": channel_id,
            "output_dir": output_dir,
            "limit": limit,
            "save_frequency": save_frequency,
            "start_date": start_date,
            "end_date": end_date,
            "format_discord_kit": format_discord_kit,
            "custom_filename": custom_filename,
            "export_json_raw": export_json_raw,
            "export_jsonl": export_jsonl,
            "export_txt": export_txt,
            "export_csv": export_csv,
            "export_html": export_html
        }
        
        # Remover None values
        payload = {k: v for k, v in payload.items() if v is not None}
        
        response = self.session.post(
            f"{self.base_url}/api/export",
            json=payload
        )
        
        response.raise_for_status()
        return response.json()


# Ejemplos de uso
if __name__ == "__main__":
    print("=" * 70)
    print("🎯 Discord Exporter Pro - Cliente API")
    print("=" * 70)
    print()
    
    # Crear cliente
    client = DiscordExporterClient()
    
    # Verificar salud de la API
    print("📡 Verificando conexión con la API...")
    if client.health_check():
        print("✅ API activa y funcionando\n")
    else:
        print("❌ No se puede conectar a la API")
        print("   Asegúrate de que el servidor está ejecutándose")
        print("   Ejecuta: python discord_exporter_pro_CLI.py\n")
        exit(1)
    
    # Obtener información de endpoints
    print("📚 Endpoints disponibles:")
    try:
        info = client.get_info()
        print(f"   Servicio: {info['service']}")
        print(f"   Versión: {info['version']}")
        print()
    except Exception as e:
        print(f"❌ Error: {e}\n")
        exit(1)
    
    # Ejemplo 1: Exportación simple
    print("=" * 70)
    print("📝 EJEMPLO 1: Exportación simple con todos los formatos")
    print("=" * 70)
    print()
    
    try:
        print('Enviando solicitud: {"token": "...", "channel_id": "123456789"}')
        print()
        
        result = client.export_channel(
            token="tu_token_de_discord_aqui",
            channel_id="123456789",
        )
        
        print(f"✅ {result['status'].upper()}")
        print(f"📊 Total de mensajes: {result['total_messages']}")
        print(f"📁 Carpeta de salida: {result['output_dir']}/")
        print(f"📄 Archivos generados:")
        for file in result['exported_files']:
            print(f"   • {file}")
            
    except requests.exceptions.ConnectionError:
        print("❌ No se puede conectar a la API")
        print("   Asegúrate de que el servidor está ejecutándose\n")
    except requests.exceptions.HTTPError as e:
        error = e.response.json()
        print(f"❌ Error: {error['error']}\n")
    
    # Ejemplo 2: Exportación con filtrado de fechas
    print("\n" + "=" * 70)
    print("📝 EJEMPLO 2: Exportación con filtrado de fechas")
    print("=" * 70)
    print()
    print("Solicitud con parámetros opcionales:")
    print('''
{
    "token": "...",
    "channel_id": "123456789",
    "start_date": "2024-01-01",
    "end_date": "2024-01-31",
    "custom_filename": "enero_2024",
    "export_json_raw": false,
    "export_jsonl": false
}
    ''')
    
    # Ejemplo 3: Exportación con formatos específicos
    print("=" * 70)
    print("📝 EJEMPLO 3: Exportación con formatos específicos")
    print("=" * 70)
    print()
    print("Solicitud solo CSV y HTML:")
    print('''
{
    "token": "...",
    "channel_id": "123456789",
    "export_json_raw": false,
    "export_jsonl": false,
    "export_txt": false,
    "export_csv": true,
    "export_html": true
}
    ''')
    
    print("=" * 70)
    print("\n💡 Para usar este cliente:")
    print("   1. Asegúrate de que el servidor está ejecutándose")
    print("   2. Reemplaza 'tu_token_de_discord_aqui' con un token real")
    print("   3. Reemplaza '123456789' con un ID de canal válido")
    print("   4. Ejecuta: python example_client.py")
    print()
    print("📚 Para más información, revisa API_DOCUMENTATION.md")
    print()
