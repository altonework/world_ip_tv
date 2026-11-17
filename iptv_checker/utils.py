import asyncio
import os
import re

import aiohttp
import logging

logger = logging.getLogger(__name__)


def _playlist_code(url):
    """'.../countries/ar.m3u' -> 'ar', '.../subdivisions/ar-b.m3u' -> 'ar-b'."""
    return os.path.splitext(os.path.basename(url))[0].lower()


def read_playlist_urls(filepath):
    """Return a list of (group_title, url).

    Regional (subdivision) playlists are grouped under their parent country,
    so e.g. 'Buenos Aires' (ar-b) channels appear in the 'Argentina' group.
    """
    entries = []
    with open(filepath, 'r', encoding='utf-8') as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith('#') or ':' not in line:
                continue
            name, url = line.split(':', 1)
            name, url = name.strip(), url.strip()
            if not url.startswith(('http://', 'https://')):
                logger.warning(f"Invalid URL for {name}: {url}")
                continue
            entries.append((name, url))

    # Map country code -> country name from the national playlists.
    country_names = {
        _playlist_code(url): name
        for name, url in entries
        if '/subdivisions/' not in url
    }

    playlist_urls = []
    for name, url in entries:
        if '/subdivisions/' in url:
            parent = _playlist_code(url).split('-', 1)[0]
            parent = {'gb': 'uk'}.get(parent, parent)  # iptv-org uses uk.m3u but gb-*.m3u
            name = country_names.get(parent, name)
        playlist_urls.append((name, url))
    return playlist_urls


async def download_playlist(url):
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    return await response.text()
                logger.error(f"Failed to download playlist from {url}: HTTP {response.status}")
                if response.status in (404, 410):
                    return ""  # source is gone: treat as an empty playlist
        except aiohttp.ClientError as e:
            logger.error(f"Client error while downloading playlist from {url}: {e}")
        except asyncio.TimeoutError:
            logger.error(f"Timeout while downloading playlist from {url}")

    return None  # temporary failure


def create_index_m3u():
    index_content = "#EXTM3U\n"
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = os.path.join(base_dir, 'output')

    # Словарь для хранения каналов по группам
    grouped_channels = {}
    seen_urls = set()

    for root, _, files in os.walk(output_dir):
        # Sorted so national lists (e.g. ar.m3u) come before regional ones (ar-b.m3u).
        for file in sorted(files):
            if file.endswith('.m3u') and file != 'index.m3u':
                file_path = os.path.join(root, file)
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    lines = content.splitlines()[1:]
                    for i in range(0, len(lines) - 1, 2):
                        group_title = re.search(r'group-title="([^"]+)"', lines[i]).group(1)
                        url = lines[i + 1].strip()
                        # The same channel is often listed both nationally and regionally.
                        if url in seen_urls:
                            continue
                        seen_urls.add(url)
                        channel_info = f'{lines[i]}\n{lines[i + 1]}\n'
                        if group_title not in grouped_channels:
                            grouped_channels[group_title] = []
                        grouped_channels[group_title].append(channel_info)

    # Сортируем группы по алфавиту
    for group_title in sorted(grouped_channels):
        for channel_info in grouped_channels[group_title]:
            index_content += channel_info

    index_path = os.path.join(output_dir, 'index.m3u')
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(index_content)

    print(f"Index file created at {index_path}")
