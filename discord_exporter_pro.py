import requests
import time
import json
import csv
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
import re
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os

class DiscordExporter:
    """
    Extractor profesional de mensajes de Discord.
    Sin límites. Tu herramienta. Tu infraestructura.
    
    Versión: 2.0 (Producción)
    """
    
    def __init__(self, token: str):
        self.token = token
        self.headers = {"Authorization": token}
        self.base_url = "https://discord.com/api/v9"
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        
        # Configuración de reintentos
        self.max_retries = 5
        self.retry_delay = 3
    
    def get_channel_info(self, channel_id: str) -> Dict:
        """Obtiene información del canal con reintentos"""
        for attempt in range(self.max_retries):
            try:
                r = self.session.get(
                    f"{self.base_url}/channels/{channel_id}",
                    timeout=10
                )
                
                if r.status_code == 200:
                    return r.json()
                elif r.status_code in (500, 502, 503, 504):
                    print(f"⚠️  Servidor lento. Reintento {attempt + 1}/{self.max_retries}...")
                    time.sleep(self.retry_delay)
                    continue
                else:
                    raise Exception(f"Error {r.status_code}: {r.text}")
                    
            except requests.exceptions.RequestException as e:
                print(f"⚠️  Error de red. Reintento {attempt + 1}/{self.max_retries}...")
                time.sleep(self.retry_delay)
                
        raise Exception("No se pudo conectar después de varios intentos")
    
    def fetch_messages(
        self, 
        channel_id: str, 
        limit: int = 100, 
        before: Optional[str] = None
    ) -> List[Dict]:
        """
        Descarga un batch de mensajes con manejo robusto de errores.
        """
        params = {"limit": limit}
        if before:
            params["before"] = before
        
        for attempt in range(self.max_retries):
            try:
                r = self.session.get(
                    f"{self.base_url}/channels/{channel_id}/messages",
                    params=params,
                    timeout=15
                )
                
                # Rate limit: esperar y reintentar
                if r.status_code == 429:
                    retry_after = r.json().get("retry_after", 5)
                    print(f"⏸️  Rate limit. Esperando {retry_after:.1f}s...")
                    time.sleep(retry_after + 0.5)  # +0.5s de margen
                    continue
                
                # Errores de servidor: reintentar
                if r.status_code in (500, 502, 503, 504):
                    print(f"⚠️  Error {r.status_code}. Reintento {attempt + 1}/{self.max_retries}...")
                    time.sleep(self.retry_delay)
                    continue
                
                # Otros errores: lanzar excepción
                if r.status_code != 200:
                    raise Exception(f"Error {r.status_code}: {r.text}")
                
                return r.json()
                
            except requests.exceptions.RequestException as e:
                print(f"⚠️  Error de conexión. Reintento {attempt + 1}/{self.max_retries}...")
                time.sleep(self.retry_delay)
        
        raise Exception("No se pudieron descargar mensajes después de varios intentos")
    
    def _normalize_datetime(self, date_input: Optional[str], is_end_date: bool = False) -> Optional[str]:
        """
        Normaliza múltiples formatos de fecha/hora a ISO 8601 con timezone.
        
        Formatos soportados:
        1. "YYYY-MM-DD" → "YYYY-MM-DDTHH:MM:SS+00:00" (00:00:00 o 23:59:59 si es end_date)
        2. "YYYY-MM-DD HH:MM" → "YYYY-MM-DDTHH:MM:00+00:00"
        3. "YYYY-MM-DD HH:MM:SS" → "YYYY-MM-DDTHH:MM:SS+00:00"
        4. "YYYY-MM-DDTHH:MM" → "YYYY-MM-DDTHH:MM:00+00:00"
        5. "YYYY-MM-DDTHH:MM:SS" → "YYYY-MM-DDTHH:MM:SS+00:00"
        6. "YYYY-MM-DDTHH:MM:SS+00:00" (ya completo)
        
        Args:
            date_input: String con la fecha en cualquier formato soportado
            is_end_date: Si es True, usa 23:59:59 para fechas sin hora. Si es False, usa 00:00:00
        
        Returns:
            String en formato ISO 8601 "YYYY-MM-DDTHH:MM:SS+00:00" o None si es inválido
        """
        if not date_input:
            return None
        
        date_input = date_input.strip()
        
        # Si ya está en formato ISO 8601 completo, retornar directo
        if re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$', date_input):
            return date_input
        
        try:
            # Intentar parsear diferentes formatos
            formats = [
                "%Y-%m-%dT%H:%M:%S",      # 2024-01-15T14:30:45
                "%Y-%m-%dT%H:%M",         # 2024-01-15T14:30
                "%Y-%m-%d %H:%M:%S",      # 2024-01-15 14:30:45
                "%Y-%m-%d %H:%M",         # 2024-01-15 14:30
                "%Y-%m-%d",               # 2024-01-15
            ]
            
            parsed_date = None
            for fmt in formats:
                try:
                    parsed_date = datetime.strptime(date_input, fmt)
                    break
                except ValueError:
                    continue
            
            if not parsed_date:
                return None
            
            # Si solo se ingresó la fecha (sin hora), aplicar lógica especial
            if re.match(r'^\d{4}-\d{2}-\d{2}$', date_input):
                if is_end_date:
                    # Para fecha final, usar 23:59:59
                    parsed_date = parsed_date.replace(hour=23, minute=59, second=59)
                else:
                    # Para fecha inicial, usar 00:00:00
                    parsed_date = parsed_date.replace(hour=0, minute=0, second=0)
            else:
                # Si se ingresó hora pero no segundos, poner segundos en 0
                if parsed_date.second == 0 and ':' in date_input and date_input.count(':') == 1:
                    parsed_date = parsed_date.replace(second=0)
            
            # Convertir a ISO 8601 con timezone +00:00
            iso_string = parsed_date.strftime("%Y-%m-%dT%H:%M:%S") + "+00:00"
            return iso_string
            
        except Exception as e:
            return None
    
    def export_channel(
        self, 
        channel_id: str, 
        output_dir: str = "exports",
        limit: int = 100,
        save_batches: bool = True,
        batch_size: int = 1000,
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
    ) -> List[Dict]:
        """
        Exporta TODOS los mensajes de un canal con filtrado por rango de fechas.
        
        Args:
            channel_id: ID del canal
            output_dir: Carpeta de salida (default: "exports")
            limit: Número de mensajes por request a Discord (default: 100, max: 100)
            save_batches: Guardar batches intermedios (default: True)
            batch_size: Tamaño de cada batch para guardar (default: 1000)
            save_frequency: Cada cuántos mensajes guardar JSON (default: 1000)
            start_date: Fecha/hora mínima. Formatos soportados:
                - "2024-01-15"
                - "2024-01-15 14:30"
                - "2024-01-15 14:30:45"
                - "2024-01-15T14:30:45"
                - "2024-01-15T14:30:45+00:00"
            end_date: Fecha/hora máxima (mismos formatos que start_date)
            format_discord_kit: Exportar en formato compatible con Discord Kit
            custom_filename: Nombre personalizado para los archivos (sin extensión)
            export_json_raw: Exportar JSON raw (default: True)
            export_jsonl: Exportar JSONL (default: True)
            export_txt: Exportar TXT legible (default: True)
            export_csv: Exportar CSV (default: True)
            export_html: Exportar HTML (default: True)
        
        Returns:
            Lista completa de mensajes
        """
        # Crear carpeta
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)
        
        # Validar y ajustar limit
        if limit > 100:
            limit = 100
        elif limit < 1:
            limit = 1
        
        # Info del canal
        channel_info = self.get_channel_info(channel_id)
        channel_name = channel_info.get("name", channel_id)
        channel_type = channel_info.get("type", "unknown")
        
        # Usar custom_filename si se proporciona
        file_prefix = custom_filename if custom_filename else channel_name
        
        # Normalizar fechas
        start_timestamp = self._normalize_datetime(start_date, is_end_date=False)
        end_timestamp = self._normalize_datetime(end_date, is_end_date=True)
        
        # Variables
        all_messages = []
        last_id = None
        batch_count = 0
        stop_at_date = False
        
        while True:
            try:
                # Descargar batch
                batch = self.fetch_messages(channel_id, limit=limit, before=last_id)
                
                # Si no hay más mensajes, terminar
                if not batch:
                    break
                
                # Filtrar por fecha si es necesario
                filtered_batch = []
                for msg in batch:
                    msg_timestamp = msg.get("timestamp", "")
                    
                    # Validar que esté dentro del rango
                    if start_timestamp and msg_timestamp < start_timestamp:
                        stop_at_date = True
                        break
                    
                    if end_timestamp and msg_timestamp > end_timestamp:
                        # Si está fuera del rango final, saltar pero continuar
                        continue
                    
                    filtered_batch.append(msg)
                
                all_messages.extend(filtered_batch)
                
                if stop_at_date:
                    break
                
                if not batch or not filtered_batch:
                    break
                
                last_id = batch[-1]["id"]
                
                # Guardar batch intermedio cada save_frequency mensajes
                if save_batches and len(all_messages) % save_frequency == 0 and len(all_messages) > 0:
                    batch_count += 1
                    batch_file = output_path / f"{file_prefix}_batch_{batch_count}_{len(all_messages)}msg.json"
                    with open(batch_file, "w", encoding="utf-8") as f:
                        json.dump(
                            all_messages[-save_frequency:], 
                            f, 
                            ensure_ascii=False, 
                            indent=2
                        )
                
                # Pausa entre requests
                time.sleep(0.3)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                break
        
        # Guardar exports finales
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        if format_discord_kit:
            # Formato compatible con Discord Kit
            self._save_discord_kit_format(
                all_messages,
                channel_info,
                output_path,
                file_prefix,
                timestamp
            )
        
        # JSON completo (formato raw)
        if export_json_raw:
            json_file = output_path / f"{file_prefix}_raw_{timestamp}.json"
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(all_messages, f, ensure_ascii=False, indent=2)
        
        # JSONL (para LMs)
        if export_jsonl:
            jsonl_file = output_path / f"{file_prefix}_dataset_{timestamp}.jsonl"
            with open(jsonl_file, "w", encoding="utf-8") as f:
                for msg in all_messages:
                    f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        
        # TXT legible
        if export_txt:
            txt_file = output_path / f"{file_prefix}_readable_{timestamp}.txt"
            with open(txt_file, "w", encoding="utf-8") as f:
                for msg in all_messages:
                    author = msg.get("author", {}).get("username", "Unknown")
                    content = msg.get("content", "")
                    timestamp_msg = msg.get("timestamp", "")
                    
                    if content:
                        f.write(f"[{timestamp_msg}] {author}: {content}\n")
        
        # CSV
        if export_csv:
            self._save_csv_format(
                all_messages,
                output_path,
                file_prefix,
                timestamp
            )
        
        # HTML
        if export_html:
            self._save_html_format(
                all_messages,
                channel_info,
                output_path,
                file_prefix,
                timestamp
            )
        
        return all_messages
    def _save_discord_kit_format(
        self, 
        messages: List[Dict],
        channel_info: Dict,
        output_path: Path,
        channel_name: str,
        timestamp: str
    ):
        """Guarda en formato compatible con Discord Kit"""
        
        # Calcular rango de fechas
        if messages:
            dates = [msg.get("timestamp", "") for msg in messages if msg.get("timestamp")]
            min_date = min(dates) if dates else datetime.now().isoformat()
            max_date = max(dates) if dates else datetime.now().isoformat()
        else:
            min_date = max_date = datetime.now().isoformat()
        
        discord_kit_data = {
            "guild": {
                "id": "0",
                "name": "Direct Messages",
                "iconUrl": "https://cdn.discordapp.com/embed/avatars/0.png"
            },
            "channel": {
                "id": channel_info.get("id"),
                "type": self._get_channel_type_name(channel_info.get("type")),
                "categoryId": None,
                "category": None,
                "name": channel_info.get("name", "Unknown"),
                "topic": channel_info.get("topic")
            },
            "dateRange": {
                "after": min_date,
                "before": max_date
            },
            "exportedAt": datetime.now().isoformat(),
            "messages": messages,
            "messageCount": len(messages)
        }
        
        dk_file = output_path / f"{channel_name}_discord_kit_{timestamp}.json"
        with open(dk_file, "w", encoding="utf-8") as f:
            json.dump(discord_kit_data, f, ensure_ascii=False, indent=2)
    
    def _save_csv_format(
        self,
        messages: List[Dict],
        output_path: Path,
        channel_name: str,
        timestamp: str
    ):
        """Guarda los mensajes en formato CSV"""
        csv_file = output_path / f"{channel_name}_export_{timestamp}.csv"
        
        try:
            with open(csv_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                # Encabezados
                writer.writerow([
                    "Timestamp",
                    "Autor",
                    "ID Autor",
                    "Mensaje",
                    "ID Mensaje",
                    "Attachments",
                    "Embeds",
                    "Reacciones"
                ])
                
                # Datos
                for msg in messages:
                    author = msg.get("author", {})
                    author_name = author.get("username", "Unknown")
                    author_id = author.get("id", "")
                    content = msg.get("content", "")
                    msg_id = msg.get("id", "")
                    timestamp_msg = msg.get("timestamp", "")
                    
                    # Attachments
                    attachments = msg.get("attachments", [])
                    attachments_str = "; ".join([f"{att.get('filename', '')} ({att.get('url', '')})" for att in attachments]) if attachments else ""
                    
                    # Embeds
                    embeds = msg.get("embeds", [])
                    embeds_count = len(embeds) if embeds else 0
                    
                    # Reacciones
                    reactions = msg.get("reactions", [])
                    reactions_str = "; ".join([f"{r.get('emoji', {}).get('name', '')} (x{r.get('count', 1)})" for r in reactions]) if reactions else ""
                    
                    writer.writerow([
                        timestamp_msg,
                        author_name,
                        author_id,
                        content,
                        msg_id,
                        attachments_str,
                        embeds_count,
                        reactions_str
                    ])
        except Exception as e:
            pass
    
    def _save_html_format(
        self,
        messages: List[Dict],
        channel_info: Dict,
        output_path: Path,
        channel_name: str,
        timestamp: str
    ):
        """Guarda los mensajes en formato HTML con estilos"""
        html_file = output_path / f"{channel_name}_export_{timestamp}.html"
        
        try:
            channel_display_name = channel_info.get("name", "Unknown")
            
            html_content = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Exportación Discord - {channel_display_name}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #2c3e50;
            padding: 20px;
        }}
        
        .container {{
            max-width: 900px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.3);
            overflow: hidden;
        }}
        
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px 20px;
            border-bottom: 4px solid #f39c12;
        }}
        
        .header h1 {{
            font-size: 28px;
            margin-bottom: 10px;
        }}
        
        .header p {{
            font-size: 14px;
            opacity: 0.9;
        }}
        
        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            padding: 20px;
            background: #f8f9fa;
            border-bottom: 1px solid #e0e0e0;
        }}
        
        .stat-box {{
            background: white;
            padding: 15px;
            border-radius: 8px;
            border-left: 4px solid #667eea;
        }}
        
        .stat-label {{
            font-size: 12px;
            color: #7f8c8d;
            text-transform: uppercase;
            font-weight: bold;
        }}
        
        .stat-value {{
            font-size: 24px;
            color: #2c3e50;
            font-weight: bold;
            margin-top: 5px;
        }}
        
        .messages {{
            padding: 20px;
            max-height: 800px;
            overflow-y: auto;
        }}
        
        .message {{
            margin-bottom: 20px;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 8px;
            border-left: 4px solid #667eea;
            transition: all 0.3s ease;
        }}
        
        .message:hover {{
            background: #ecf0f1;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        }}
        
        .message-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
            flex-wrap: wrap;
        }}
        
        .message-author {{
            font-weight: bold;
            color: #667eea;
            font-size: 14px;
        }}
        
        .message-timestamp {{
            font-size: 12px;
            color: #95a5a6;
        }}
        
        .message-content {{
            color: #2c3e50;
            word-wrap: break-word;
            white-space: pre-wrap;
            line-height: 1.6;
        }}
        
        .message-meta {{
            margin-top: 10px;
            font-size: 11px;
            color: #7f8c8d;
            padding-top: 10px;
            border-top: 1px solid #ddd;
        }}
        
        .attachment {{
            display: inline-block;
            background: #e8f4f8;
            padding: 5px 10px;
            border-radius: 4px;
            margin-right: 8px;
            margin-top: 5px;
            font-size: 11px;
            color: #2980b9;
        }}
        
        .footer {{
            background: #f8f9fa;
            padding: 20px;
            text-align: center;
            color: #7f8c8d;
            font-size: 12px;
            border-top: 1px solid #e0e0e0;
        }}
        
        @media (max-width: 600px) {{
            .header h1 {{
                font-size: 20px;
            }}
            
            .stat-box {{
                padding: 10px;
            }}
            
            .stat-value {{
                font-size: 18px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 Exportación Discord</h1>
            <p>Canal: <strong>{channel_display_name}</strong></p>
        </div>
        
        <div class="stats">
            <div class="stat-box">
                <div class="stat-label">Total de Mensajes</div>
                <div class="stat-value">{len(messages)}</div>
            </div>
"""
            
            # Contar autores únicos
            authors = set(msg.get("author", {}).get("username", "Unknown") for msg in messages)
            html_content += f"""            <div class="stat-box">
                <div class="stat-label">Autores Únicos</div>
                <div class="stat-value">{len(authors)}</div>
            </div>
"""
            
            # Fecha de primer y último mensaje
            if messages:
                dates = [msg.get("timestamp", "") for msg in messages if msg.get("timestamp")]
                if dates:
                    first_date = min(dates)
                    last_date = max(dates)
                    html_content += f"""            <div class="stat-box">
                <div class="stat-label">Período</div>
                <div class="stat-value" style="font-size: 14px;">{first_date[:10]} a {last_date[:10]}</div>
            </div>
"""
            
            html_content += """        </div>
        
        <div class="messages">
"""
            
            # Agregar mensajes
            for msg in messages:
                author = msg.get("author", {})
                author_name = author.get("username", "Unknown")
                content = msg.get("content", "(sin contenido)")
                timestamp_msg = msg.get("timestamp", "Sin fecha")
                msg_id = msg.get("id", "")
                
                # Escapar caracteres HTML
                content = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                author_name = author_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                
                html_content += f"""            <div class="message">
                <div class="message-header">
                    <span class="message-author">@{author_name}</span>
                    <span class="message-timestamp">{timestamp_msg}</span>
                </div>
                <div class="message-content">{content}</div>
"""
                
                # Attachments
                attachments = msg.get("attachments", [])
                if attachments:
                    html_content += '                <div class="message-meta">'
                    for att in attachments:
                        filename = att.get("filename", "archivo")
                        url = att.get("url", "#")
                        html_content += f'<a href="{url}" class="attachment" target="_blank">📎 {filename}</a>'
                    html_content += '</div>'
                
                # Reacciones
                reactions = msg.get("reactions", [])
                if reactions:
                    html_content += '                <div class="message-meta">'
                    for r in reactions:
                        emoji = r.get("emoji", {}).get("name", "?")
                        count = r.get("count", 1)
                        html_content += f'<span class="attachment">😊 {emoji} x{count}</span>'
                    html_content += '</div>'
                
                html_content += "                </div>\n"
            
            html_content += f"""        </div>
        
        <div class="footer">
            <p>Exportado el {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Total: {len(messages)} mensajes</p>
        </div>
    </div>
</body>
</html>
"""
            
            with open(html_file, "w", encoding="utf-8") as f:
                f.write(html_content)
        except Exception as e:
            pass
    
    def _get_channel_type_name(self, channel_type: int) -> str:
        """Convierte tipo de canal a nombre legible"""
        types = {
            0: "GuildTextChat",
            1: "DirectTextChat",
            2: "GuildVoiceChat",
            3: "GroupDM",
            4: "GuildCategory",
            5: "GuildNewsChannel",
            10: "NewsThread",
            11: "PublicThread",
            12: "PrivateThread",
            13: "GuildStageVoice",
            15: "GuildForum"
        }
        return types.get(channel_type, f"Type{channel_type}")


def create_api():
    """Crea la aplicación Flask con los endpoints"""
    app = Flask(__name__)
    CORS(app)
    
    # Obtener la ruta del archivo HTML
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Variable global para mantener el exporter
    exporter_instance = None
    
    @app.route('/')
    def index():
        """Sirve la página principal"""
        html_path = os.path.join(base_dir, 'index.html')
        if os.path.exists(html_path):
            return send_from_directory(base_dir, 'index.html')
        return jsonify({'error': 'index.html not found'}), 404
    
    @app.route('/api/export', methods=['POST'])
    def export_messages():
        """
        Endpoint para exportar mensajes de un canal de Discord
        
        Parámetros JSON:
        {
            "token": "token_de_discord",
            "channel_id": "123456789",
            "output_dir": "exports" (optional),
            "limit": 100 (optional),
            "save_frequency": 1000 (optional),
            "start_date": "2024-01-15" (optional),
            "end_date": "2024-01-20" (optional),
            "format_discord_kit": true (optional),
            "custom_filename": "mi_canal" (optional),
            "export_json_raw": true (optional),
            "export_jsonl": true (optional),
            "export_txt": true (optional),
            "export_csv": true (optional),
            "export_html": true (optional)
        }
        """
        try:
            data = request.get_json()
            
            # Validar parámetros obligatorios
            if not data.get('token'):
                return jsonify({"error": "Token es requerido"}), 400
            if not data.get('channel_id'):
                return jsonify({"error": "Channel ID es requerido"}), 400
            
            # Crear exporter
            nonlocal exporter_instance
            exporter_instance = DiscordExporter(data['token'])
            
            # Parámetros opcionales
            output_dir = data.get('output_dir', 'exports')
            limit = data.get('limit', 100)
            save_frequency = data.get('save_frequency', 1000)
            start_date = data.get('start_date')
            end_date = data.get('end_date')
            format_discord_kit = data.get('format_discord_kit', False)
            custom_filename = data.get('custom_filename')
            export_json_raw = data.get('export_json_raw', True)
            export_jsonl = data.get('export_jsonl', True)
            export_txt = data.get('export_txt', True)
            export_csv = data.get('export_csv', True)
            export_html = data.get('export_html', True)
            
            # Si no hay formatos seleccionados, usar todos
            if not any([export_json_raw, export_jsonl, export_txt, export_csv, export_html]):
                export_json_raw = export_jsonl = export_txt = export_csv = export_html = True
            
            # Exportar mensajes
            messages = exporter_instance.export_channel(
                data['channel_id'],
                output_dir=output_dir,
                limit=limit,
                save_frequency=save_frequency,
                start_date=start_date,
                end_date=end_date,
                format_discord_kit=format_discord_kit,
                custom_filename=custom_filename,
                export_json_raw=export_json_raw,
                export_jsonl=export_jsonl,
                export_txt=export_txt,
                export_csv=export_csv,
                export_html=export_html
            )
            
            # Preparar respuesta
            exported_files = []
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_prefix = custom_filename if custom_filename else data['channel_id']
            
            if export_json_raw:
                exported_files.append(f"{file_prefix}_raw_{timestamp}.json")
            if export_jsonl:
                exported_files.append(f"{file_prefix}_dataset_{timestamp}.jsonl")
            if export_txt:
                exported_files.append(f"{file_prefix}_readable_{timestamp}.txt")
            if export_csv:
                exported_files.append(f"{file_prefix}_export_{timestamp}.csv")
            if export_html:
                exported_files.append(f"{file_prefix}_export_{timestamp}.html")
            if format_discord_kit:
                exported_files.append(f"{file_prefix}_discord_kit_{timestamp}.json")
            
            return jsonify({
                "status": "success",
                "total_messages": len(messages),
                "output_dir": output_dir,
                "exported_files": exported_files
            }), 200
            
        except Exception as e:
            return jsonify({
                "status": "error",
                "error": str(e)
            }), 500
    
    @app.route('/api/health', methods=['GET'])
    def health():
        """Endpoint de salud para verificar que la API está activa"""
        return jsonify({
            "status": "healthy",
            "version": "2.0",
            "service": "Discord Exporter Pro"
        }), 200
    
    @app.route('/api/info', methods=['GET'])
    def info():
        """Información sobre los endpoints disponibles"""
        return jsonify({
            "service": "Discord Exporter Pro API",
            "version": "2.0",
            "endpoints": {
                "POST /api/export": {
                    "description": "Exporta mensajes de un canal de Discord",
                    "required_params": ["token", "channel_id"],
                    "optional_params": [
                        "output_dir",
                        "limit",
                        "save_frequency",
                        "start_date",
                        "end_date",
                        "format_discord_kit",
                        "custom_filename",
                        "export_json_raw",
                        "export_jsonl",
                        "export_txt",
                        "export_csv",
                        "export_html"
                    ]
                },
                "GET /api/health": {
                    "description": "Verifica el estado de la API"
                },
                "GET /api/info": {
                    "description": "Información sobre los endpoints"
                }
            }
        }), 200
    
    return app


if __name__ == "__main__":
    app = create_api()
    print("=" * 60)
    print("🎯 DISCORD EXPORTER PRO v2.0 - API REST")
    print("=" * 60)
    print()
    print("🚀 Iniciando servidor...")
    print("📍 URL: http://localhost:5000")
    print()
    print("📚 Endpoints disponibles:")
    print("   • GET  /api/health  - Estado de la API")
    print("   • GET  /api/info    - Información de endpoints")
    print("   • POST /api/export  - Exportar mensajes")
    print()
    print("=" * 60)
    app.run(debug=True, host='0.0.0.0', port=5000)