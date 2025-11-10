#!/usr/bin/env python3
"""
epg_generator.py
Gera epg.xml (XMLTV) a partir de uma playlist M3U (local ou URL).
Melhorias: pretty-print do XML, logs, --max-channels para testar.
"""

import argparse
import csv
import datetime as dt
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET
import sys
import os

try:
    import requests
except ImportError:
    requests = None

# pretty print
from xml.dom import minidom

TZ = ZoneInfo("America/Recife")


def now_tz():
    return dt.datetime.now(TZ)


def load_m3u(path_or_url):
    """Carrega playlist M3U (arquivo local ou URL)."""
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        if not requests:
            print("Erro: módulo 'requests' não disponível. Instale com: pip install requests")
            sys.exit(2)
        try:
            r = requests.get(path_or_url, timeout=20)
            r.raise_for_status()
            return r.text
        except requests.exceptions.HTTPError as e:
            print(f"Erro HTTP ao baixar a playlist: {e}. URL: {path_or_url}")
            sys.exit(2)
        except requests.exceptions.RequestException as e:
            print(f"Erro de conexão ao baixar a playlist: {e}. URL: {path_or_url}")
            sys.exit(2)
    else:
        if not os.path.exists(path_or_url):
            print(f"Arquivo não encontrado: {path_or_url}")
            sys.exit(2)
        try:
            with open(path_or_url, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception as e:
            print(f"Erro ao ler o arquivo {path_or_url}: {e}")
            sys.exit(2)


def parse_m3u_text(text):
    """Retorna lista de canais: dicts com tvg_id, name, url."""
    lines = [l.strip() for l in text.splitlines() if l.strip() != ""]
    channels = []
    i = 0
    import re
    while i < len(lines):
        line = lines[i]
        if line.startswith("#EXTINF"):
            # captura tvg-id e nome do display
            tvg_id = None
            name = None
            m_id = re.search(r'tvg-id="([^"]+)"', line)
            if m_id:
                tvg_id = m_id.group(1).strip()
            if ',' in line:
                name = line.split(",", 1)[1].strip()
            url = lines[i + 1] if i + 1 < len(lines) and not lines[i + 1].startswith("#") else ""
            channels.append({
                "tvg_id": tvg_id or name or f"chan{i}",
                "name": name or tvg_id or f"chan{i}",
                "url": url
            })
            i += 2
        else:
            i += 1
    return channels


def read_csv_schedule(csv_path):
    """Lê CSV com colunas tvg-id,start,stop,title,desc."""
    events = []
    if not os.path.exists(csv_path):
        print(f"CSV não en
