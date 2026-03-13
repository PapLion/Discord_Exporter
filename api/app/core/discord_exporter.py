"""
Discord Exporter - Core module for exporting Discord channel messages.

This module provides the DiscordExporter class with robust error handling,
retries, rate limiting, and multiple export formats.

Features:
- Fetch channel information and messages from Discord API
- Export to multiple formats: JSON, JSONL, TXT, CSV, HTML
- Date-based filtering of messages
- Progress saving for large exports
- Comprehensive error handling
"""

import os
import json
import time
import requests
from datetime import datetime
from typing import List, Dict, Optional, Union, Any
from pathlib import Path
import logging
import re
import uuid

# Optional import for typed Discord client
try:
    from app.infrastructure.discord_client import DiscordClient, Channel, Message
    HAS_TYPED_CLIENT = True
except ImportError:
    HAS_TYPED_CLIENT = False
    DiscordClient = None
    Channel = None
    Message = None

logger = logging.getLogger(__name__)


class DiscordExporter:
    """
    Core class for exporting Discord channel messages with robust error handling and retries.
    
    This class provides a synchronous interface for interacting with Discord's API
    and exporting messages to various file formats.
    
    Attributes:
        token: Discord bot or user token for authentication
        max_retries: Maximum number of retry attempts for failed requests
        retry_delay: Base delay between retries in seconds
        timeout: Request timeout in seconds
        use_typed_client: Whether to use the typed DiscordClient (if available)
    
    Example:
        exporter = DiscordExporter(token="your-discord-token")
        result = exporter.export_channel(
            channel_id="123456789",
            output_dir="exports",
            limit=1000
        )
    """
    
    BASE_URL = "https://discord.com/api/v9"
    
    def __init__(
        self,
        token: str,
        max_retries: int = 5,
        retry_delay: float = 3.0,
        timeout: float = 15.0,
        use_typed_client: bool = False
    ):
        """
        Initialize the DiscordExporter with a Discord token.
        
        Args:
            token: Discord bot or user token
            max_retries: Maximum number of retry attempts (default: 5)
            retry_delay: Base delay between retries in seconds (default: 3.0)
            timeout: Request timeout in seconds (default: 15.0)
            use_typed_client: Whether to use typed DiscordClient (default: False)
        """
        self.token = token
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.timeout = timeout
        self.use_typed_client = use_typed_client and HAS_TYPED_CLIENT
        
        # Headers for all requests
        self.headers = {"Authorization": token, "User-Agent": "DiscordExporter/1.0"}
        self.base_url = self.BASE_URL
        
        # Create sync session
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        
        # Typed client (optional, for async operations)
        self._discord_client: Optional[DiscordClient] = None
        
        logger.info(
            "DiscordExporter initialized",
            extra={
                "use_typed_client": self.use_typed_client,
                "max_retries": max_retries,
                "timeout": timeout
            }
        )
    
    @property
    def discord_client(self) -> Optional[DiscordClient]:
        """Get or create the typed DiscordClient instance."""
        if self.use_typed_client and self._discord_client is None:
            self._discord_client = DiscordClient(
                token=self.token,
                timeout=self.timeout,
                max_retries=self.max_retries,
                retry_delay=self.retry_delay,
                correlation_id=str(uuid.uuid4())
            )
        return self._discord_client
    
    def close(self) -> None:
        """Close the exporter and release resources."""
        if self._discord_client is not None:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self._discord_client.close())
                else:
                    loop.run_until_complete(self._discord_client.close())
            except RuntimeError:
                asyncio.run(self._discord_client.close())
            self._discord_client = None
    
    def get_channel_info(self, channel_id: str) -> Dict[str, Any]:
        """
        Fetch channel information with retries.
        
        Args:
            channel_id: The Discord channel ID
            
        Returns:
            Dict containing channel information
            
        Raises:
            Exception: If the request fails after max retries
        """
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(
                    f"{self.base_url}/channels/{channel_id}",
                    timeout=self.timeout
                )
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code in (500, 502, 503, 504):
                    logger.warning(f"Server error. Retry {attempt + 1}/{self.max_retries}...")
                    time.sleep(self.retry_delay)
                    continue
                else:
                    response.raise_for_status()
                    
            except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
                logger.warning(f"Request failed (attempt {attempt + 1}/{self.max_retries}): {str(e)}")
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(self.retry_delay)
        
        raise Exception("Failed to fetch channel information after multiple attempts")
    
    def get_channel(self, channel_id: str) -> Channel:
        """
        Fetch channel information using typed client.
        
        Args:
            channel_id: The Discord channel ID
            
        Returns:
            Channel object with typed fields
            
        Raises:
            RuntimeError: If typed client is not enabled
        """
        if not self.use_typed_client or not self.discord_client:
            raise RuntimeError("Typed client is not enabled. Set use_typed_client=True")
        
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            self.discord_client.get_channel(channel_id)
        )
    
    def fetch_messages(
        self, 
        channel_id: str, 
        limit: int = 100, 
        before: Optional[str] = None,
        after: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch a batch of messages from a channel with retries and rate limit handling.
        
        Args:
            channel_id: The Discord channel ID
            limit: Number of messages to fetch (max 100)
            before: Message ID to get messages before this ID
            after: Message ID to get messages after this ID
            
        Returns:
            List of message dictionaries
            
        Raises:
            Exception: If the request fails after max retries
        """
        params: Dict[str, Any] = {"limit": min(limit, 100)}  # Discord's max limit is 100
        if before:
            params["before"] = before
        if after:
            params["after"] = after
        
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(
                    f"{self.base_url}/channels/{channel_id}/messages",
                    params=params,
                    timeout=self.timeout
                )
                
                # Handle rate limiting
                if response.status_code == 429:
                    retry_after = response.json().get("retry_after", 5)
                    logger.warning(f"Rate limited. Waiting {retry_after:.1f}s...")
                    time.sleep(retry_after + 0.5)  # Add small buffer
                    continue
                
                # Handle server errors with retry
                if response.status_code in (500, 502, 503, 504):
                    logger.warning(f"Server error {response.status_code}. Retry {attempt + 1}/{self.max_retries}...")
                    time.sleep(self.retry_delay)
                    continue
                
                # Handle other errors
                response.raise_for_status()
                
                return response.json()
                
            except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
                logger.warning(f"Request failed (attempt {attempt + 1}/{self.max_retries}): {str(e)}")
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(self.retry_delay)
        
        raise Exception("Failed to fetch messages after multiple attempts")
    
    def get_messages(
        self,
        channel_id: str,
        limit: int = 100,
        before: Optional[str] = None,
        after: Optional[str] = None
    ) -> List[Message]:
        """
        Fetch messages using typed client.
        
        Args:
            channel_id: The Discord channel ID
            limit: Number of messages to fetch (max 100)
            before: Message ID to get messages before this ID
            after: Message ID to get messages after this ID
            
        Returns:
            List of Message objects
            
        Raises:
            RuntimeError: If typed client is not enabled
        """
        if not self.use_typed_client or not self.discord_client:
            raise RuntimeError("Typed client is not enabled. Set use_typed_client=True")
        
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            self.discord_client.get_messages(channel_id, limit, before, after)
        )
        
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(
                    f"{self.base_url}/channels/{channel_id}/messages",
                    params=params,
                    timeout=self.timeout
                )
                
                # Handle rate limiting
                if response.status_code == 429:
                    retry_after = response.json().get("retry_after", 5)
                    logger.warning(f"Rate limited. Waiting {retry_after:.1f}s...")
                    time.sleep(retry_after + 0.5)  # Add small buffer
                    continue
                
                # Handle server errors with retry
                if response.status_code in (500, 502, 503, 504):
                    logger.warning(f"Server error {response.status_code}. Retry {attempt + 1}/{self.max_retries}...")
                    time.sleep(self.retry_delay)
                    continue
                
                # Handle other errors
                response.raise_for_status()
                
                return response.json()
                
            except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
                logger.warning(f"Request failed (attempt {attempt + 1}/{self.max_retries}): {str(e)}")
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(self.retry_delay)
        
        raise Exception("Failed to fetch messages after multiple attempts")
    
    def _normalize_datetime(self, date_input: Optional[str], is_end_date: bool = False) -> Optional[str]:
        """
        Normalize various datetime formats to ISO 8601 with timezone.
        
        Supported formats:
        1. "YYYY-MM-DD" → "YYYY-MM-DDTHH:MM:SS+00:00" (00:00:00 or 23:59:59 for end_date)
        2. "YYYY-MM-DD HH:MM" → "YYYY-MM-DDTHH:MM:00+00:00"
        3. "YYYY-MM-DD HH:MM:SS" → "YYYY-MM-DDTHH:MM:SS+00:00"
        4. "YYYY-MM-DDTHH:MM" → "YYYY-MM-DDTHH:MM:00+00:00"
        5. "YYYY-MM-DDTHH:MM:SS" → "YYYY-MM-DDTHH:MM:SS+00:00"
        6. "YYYY-MM-DDTHH:MM:SS+00:00" (already complete)
        
        Args:
            date_input: String with date in any supported format
            is_end_date: If True, uses 23:59:59 for dates without time
            
        Returns:
            String in ISO 8601 format or None if invalid
        """
        if not date_input:
            return None
            
        date_input = date_input.strip()
        
        # Already in full ISO 8601 format
        if re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$', date_input):
            return date_input
        
        try:
            # Try to parse different formats
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
            
            # Handle date-only input
            if re.match(r'^\d{4}-\d{2}-\d{2}$', date_input):
                if is_end_date:
                    # For end date, use 23:59:59
                    parsed_date = parsed_date.replace(hour=23, minute=59, second=59)
                else:
                    # For start date, use 00:00:00
                    parsed_date = parsed_date.replace(hour=0, minute=0, second=0)
            else:
                # If time was provided but not seconds, set seconds to 0
                if parsed_date.second == 0 and ':' in date_input and date_input.count(':') == 1:
                    parsed_date = parsed_date.replace(second=0)
            
            # Convert to ISO 8601 with timezone
            return parsed_date.strftime("%Y-%m-%dT%H:%M:%S") + "+00:00"
            
        except Exception as e:
            logger.error(f"Failed to parse date '{date_input}': {str(e)}")
            return None
    
    def export_channel(
        self,
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
    ) -> Dict[str, Union[str, int]]:
        """
        Export messages from a Discord channel with various export options.
        
        Args:
            channel_id: The Discord channel ID to export
            output_dir: Directory to save exported files
            limit: Maximum number of messages to export (0 for no limit)
            save_frequency: Save progress every N messages
            start_date: Only include messages after this date
            end_date: Only include messages before this date
            format_discord_kit: Format output for DiscordKit
            custom_filename: Custom base filename for exports
            export_json_raw: Export raw JSON data
            export_jsonl: Export as JSON Lines format
            export_txt: Export as plain text
            export_csv: Export as CSV
            export_html: Export as HTML
            
        Returns:
            Dictionary with export results and file paths
        """
        # Normalize dates
        start_ts = self._normalize_datetime(start_date) if start_date else None
        end_ts = self._normalize_datetime(end_date, is_end_date=True) if end_date else None
        
        # Create output directory
        os.makedirs(output_dir, exist_ok=True)
        
        # Initialize variables
        all_messages = []
        message_count = 0
        last_message_id = None
        has_more = True
        
        # Base filename
        base_filename = custom_filename or f"discord_export_{channel_id}"
        
        try:
            # Fetch channel info for better filenames
            try:
                channel_info = self.get_channel_info(channel_id)
                channel_name = channel_info.get('name', channel_id)
                base_filename = custom_filename or f"discord_export_{channel_name}"
            except Exception as e:
                logger.warning(f"Could not fetch channel info: {str(e)}")
                channel_info = {}
            
            # Main export loop
            while has_more and (limit <= 0 or message_count < limit):
                # Fetch a batch of messages
                messages = self.fetch_messages(
                    channel_id=channel_id,
                    limit=min(100, limit - message_count) if limit > 0 else 100,
                    before=last_message_id
                )
                
                if not messages:
                    break
                
                # Process messages
                for message in messages:
                    # Check date filters
                    message_ts = message.get('timestamp')
                    if start_ts and message_ts < start_ts:
                        has_more = False
                        break
                    if end_ts and message_ts > end_ts:
                        continue
                    
                    all_messages.append(message)
                    message_count += 1
                    last_message_id = message['id']
                    
                    # Save progress periodically
                    if message_count % save_frequency == 0:
                        self._save_export_files(
                            messages=all_messages,
                            output_dir=output_dir,
                            base_filename=f"{base_filename}_partial_{message_count}",
                            channel_info=channel_info,
                            export_json_raw=export_json_raw,
                            export_jsonl=export_jsonl,
                            export_txt=export_txt,
                            export_csv=export_csv,
                            export_html=export_html,
                            format_discord_kit=format_discord_kit
                        )
                
                # Break if we've reached the limit
                if limit > 0 and message_count >= limit:
                    break
                
                # Small delay to avoid rate limiting
                time.sleep(0.5)
            
            # Save final export
            result = self._save_export_files(
                messages=all_messages,
                output_dir=output_dir,
                base_filename=base_filename,
                channel_info=channel_info,
                export_json_raw=export_json_raw,
                export_jsonl=export_jsonl,
                export_txt=export_txt,
                export_csv=export_csv,
                export_html=export_html,
                format_discord_kit=format_discord_kit
            )
            
            result["message_count"] = message_count
            result["status"] = "completed"
            return result
            
        except Exception as e:
            logger.error(f"Export failed: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "message_count": message_count,
                "exported_files": []
            }
    
    def _save_export_files(
        self,
        messages: List[Dict],
        output_dir: str,
        base_filename: str,
        channel_info: Dict,
        export_json_raw: bool,
        export_jsonl: bool,
        export_txt: bool,
        export_csv: bool,
        export_html: bool,
        format_discord_kit: bool
    ) -> Dict[str, Union[str, List[str]]]:
        """Helper method to save messages in various formats."""
        if not messages:
            return {"status": "no_messages", "exported_files": []}
        
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        exported_files = []
        
        try:
            # Save raw JSON
            if export_json_raw:
                json_path = os.path.join(output_dir, f"{base_filename}_{timestamp}.json")
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(messages, f, ensure_ascii=False, indent=2)
                exported_files.append(json_path)
            
            # Save JSONL (one JSON object per line)
            if export_jsonl:
                jsonl_path = os.path.join(output_dir, f"{base_filename}_{timestamp}.jsonl")
                with open(jsonl_path, 'w', encoding='utf-8') as f:
                    for msg in messages:
                        f.write(json.dumps(msg, ensure_ascii=False) + '\n')
                exported_files.append(jsonl_path)
            
            # Save as plain text
            if export_txt:
                txt_path = os.path.join(output_dir, f"{base_filename}_{timestamp}.txt")
                self._export_as_txt(messages, txt_path, channel_info)
                exported_files.append(txt_path)
            
            # Save as CSV
            if export_csv:
                csv_path = os.path.join(output_dir, f"{base_filename}_{timestamp}.csv")
                self._export_as_csv(messages, csv_path)
                exported_files.append(csv_path)
            
            # Save as HTML
            if export_html:
                html_path = os.path.join(output_dir, f"{base_filename}_{timestamp}.html")
                self._export_as_html(messages, html_path, channel_info)
                exported_files.append(html_path)
            
            return {
                "status": "success",
                "exported_files": exported_files,
                "message_count": len(messages)
            }
            
        except Exception as e:
            logger.error(f"Failed to save export files: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "exported_files": exported_files
            }
    
    def _export_as_txt(self, messages: List[Dict], output_path: str, channel_info: Dict) -> None:
        """Export messages as plain text."""
        with open(output_path, 'w', encoding='utf-8') as f:
            # Write header
            channel_name = channel_info.get('name', 'Unknown Channel')
            f.write(f"=== Discord Export: {channel_name} ===\n")
            f.write(f"Exported at: {datetime.utcnow().isoformat()}\n")
            f.write("=" * 50 + "\n\n")
            
            # Write messages
            for msg in messages:
                timestamp = msg.get('timestamp', '')
                author = msg.get('author', {}).get('username', 'Unknown')
                content = msg.get('content', '')
                
                f.write(f"[{timestamp}] {author}: {content}\n")
                
                # Handle attachments
                for att in msg.get('attachments', []):
                    f.write(f"    [Attachment: {att.get('filename', 'file')}] {att.get('url', '')}\n")
                
                # Handle embeds
                for embed in msg.get('embeds', []):
                    title = embed.get('title', 'Embed')
                    f.write(f"    [Embed: {title}]\n")
    
    def _export_as_csv(self, messages: List[Dict], output_path: str) -> None:
        """Export messages as CSV."""
        import csv
        
        # Define CSV fields
        fieldnames = [
            'id', 'timestamp', 'author_id', 'author_username', 'author_discriminator',
            'content', 'attachments', 'embeds', 'reactions', 'pinned', 'mention_everyone',
            'mention_roles', 'mentions', 'type', 'tts', 'edited_timestamp'
        ]
        
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for msg in messages:
                row = {
                    'id': msg.get('id'),
                    'timestamp': msg.get('timestamp'),
                    'author_id': msg.get('author', {}).get('id'),
                    'author_username': msg.get('author', {}).get('username'),
                    'author_discriminator': msg.get('author', {}).get('discriminator'),
                    'content': msg.get('content', '').replace('\n', ' ').replace('\r', ''),
                    'attachments': len(msg.get('attachments', [])),
                    'embeds': len(msg.get('embeds', [])),
                    'reactions': len(msg.get('reactions', [])),
                    'pinned': msg.get('pinned', False),
                    'mention_everyone': msg.get('mention_everyone', False),
                    'mention_roles': ','.join(msg.get('mention_roles', [])),
                    'mentions': ','.join([m.get('id', '') for m in msg.get('mentions', [])]),
                    'type': msg.get('type', 0),
                    'tts': msg.get('tts', False),
                    'edited_timestamp': msg.get('edited_timestamp')
                }
                writer.writerow(row)
    
    def _export_as_html(self, messages: List[Dict], output_path: str, channel_info: Dict) -> None:
        """Export messages as a styled HTML page."""
        channel_name = channel_info.get('name', 'Unknown Channel')
        
        # Start HTML document
        html = f"""<!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Discord Export: {channel_name}</title>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; max-width: 1200px; margin: 0 auto; padding: 20px; }}
                .message {{ margin-bottom: 15px; padding: 10px; border-bottom: 1px solid #eee; }}
                .message-header {{ display: flex; align-items: center; margin-bottom: 5px; }}
                .author {{ font-weight: bold; margin-right: 10px; }}
                .timestamp {{ color: #666; font-size: 0.9em; }}
                .content {{ margin: 5px 0; white-space: pre-wrap; }}
                .attachment {{ margin: 5px 0; padding: 5px; background: #f5f5f5; border-radius: 3px; }}
                .embed {{ margin: 10px 0; padding: 10px; background: #f0f0f0; border-left: 3px solid #7289da; }}
                .embed-title {{ font-weight: bold; margin-bottom: 5px; }}
                .embed-description {{ margin: 5px 0; }}
                .embed-fields {{ margin: 5px 0; }}
                .embed-field {{ margin-bottom: 5px; }}
                .embed-field-name {{ font-weight: bold; }}
                .reaction {{ display: inline-block; margin: 2px; padding: 2px 5px; background: #e3e5e8; border-radius: 10px; font-size: 0.9em; }}
            </style>
        </head>
        <body>
            <h1>Discord Export: {channel_name}</h1>
            <p>Exported at: {datetime.utcnow().isoformat()}</p>
            <div class="messages">
        """
        
        # Add messages
        for msg in messages:
            timestamp = msg.get('timestamp', '')
            author = msg.get('author', {})
            author_name = f"{author.get('username', 'Unknown')}#{author.get('discriminator', '0000')}"
            content = msg.get('content', '')
            
            html += f"""
            <div class="message">
                <div class="message-header">
                    <span class="author">{author_name}</span>
                    <span class="timestamp">{timestamp}</span>
                </div>
                <div class="content">{content}</div>
            """
            
            # Add attachments
            for att in msg.get('attachments', []):
                html += f"""
                <div class="attachment">
                    <strong>Attachment:</strong> <a href="{att.get('url', '#')}" target="_blank">{att.get('filename', 'file')}</a>
                    {f'<br><small>{att.get("content_type", "")} - {self._format_size(att.get("size", 0))}</small>' if att.get('size') else ''}
                </div>
                """
            
            # Add embeds
            for embed in msg.get('embeds', []):
                html += """
                <div class="embed">
                    {title}
                    {description}
                    {fields}
                    {footer}
                </div>
                """.format(
                    title=f'<div class="embed-title">{embed.get("title", "")}</div>' if embed.get('title') else '',
                    description=f'<div class="embed-description">{embed.get("description", "")}</div>' if embed.get('description') else '',
                    fields=self._format_embed_fields(embed.get('fields', [])),
                    footer=f'<div class="embed-footer">{embed.get("footer", {}).get("text", "")}</div>' if embed.get('footer', {}).get('text') else ''
                )
            
            # Add reactions
            reactions = msg.get('reactions', [])
            if reactions:
                html += '<div class="reactions">'
                for r in reactions:
                    emoji = r.get('emoji', {})
                    emoji_text = emoji.get('name', '❓')
                    if emoji.get('id'):
                        emoji_text = f'<img src="https://cdn.discordapp.com/emojis/{emoji["id"]}.png" alt="{emoji_text}" height="20">'
                    html += f'<span class="reaction">{emoji_text} {r.get("count", 0)}</span>'
                html += '</div>'
            
            html += "</div>"  # Close message div
        
        # Close HTML document
        html += """
            </div>
        </body>
        </html>
        """
        
        # Write to file
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
    
    def _format_embed_fields(self, fields: List[Dict]) -> str:
        """Format embed fields as HTML."""
        if not fields:
            return ''
        
        html = '<div class="embed-fields">'
        for field in fields:
            html += f"""
            <div class="embed-field">
                <div class="embed-field-name">{field.get('name', '')}</div>
                <div class="embed-field-value">{field.get('value', '')}</div>
            </div>
            """
        html += '</div>'
        return html
    
    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Convert size in bytes to human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} TB"
