#!/usr/bin/env python3
"""
epg_generator.py
----------------
Gera epg.xml (formato XMLTV) a partir de uma playlist M3U (local ou URL).

Uso:
  python epg_generator.py lista.m3u --out epg.xml
  python epg_generator.py caminho/para/lista.m3u --hours 72
  python epg_generator.py "https://exemplo.com/minha.m3u"

Aceita um arquivo CSV opcional com colunas:
  tvg-id,start,stop,title,desc
para gerar uma grade real de programação.

Por padrão, gera uma grade automática de 48 horas (1h por programa).
"""

import argparse
import csv
import datetime as dt
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET
import sys

try:
    import requests
except ImportError:
    requests = None

# Fuso horário padrão
TZ = ZoneInfo("America/Recife")


def now_tz():
    return dt.datetime.now(TZ)


def load_m3u(path_or_url):
    """Carrega o conteúdo da playlist M3U de um arquivo local ou URL."""
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
        try:
            with open(path_or_url, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except FileNotFoundError:
            print(f"Arquivo não encontrado: {path_or_url}")
            print("Verifique se o arquivo foi comitado no repositório e se o caminho está correto.")
            sys.exit(2)
        except Exception as e:
            print(f"Erro ao ler o arquivo {path_or_url}: {e}")
            sys.exit(2)


def parse_m3u_text(text):
    """Lê o texto M3U e retorna lista de canais com tvg_id, nome e URL."""
    lines = [l.strip() for l in text.splitlines() if l.strip() != ""]
    channels = []
    i = 0
    while i
