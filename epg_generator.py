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
    while i < len(lines):
        line = lines[i]
        if line.startswith("#EXTINF"):
            attrs_part = line.split(" ", 1)[1] if " " in line else ""
            tvg_id = None
            name = None
            import re
            if 'tvg-id=' in line:
                m = re.search(r'tvg-id="([^"]+)"', line)
                if m:
                    tvg_id = m.group(1)
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
    """Lê um CSV opcional de grade (tvg-id,start,stop,title,desc)."""
    events = []
    with open(csv_path, newline='', encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            events.append(row)
    return events


def format_xmltv_datetime(dtobj):
    """Formata datetime para XMLTV (YYYYMMDDHHMMSS ±HHMM)."""
    return dtobj.strftime("%Y%m%d%H%M%S %z")


def build_xmltv(channels, csv_events, hours=48, out_path="epg.xml"):
    """Cria o XMLTV a partir dos canais e eventos (ou gera placeholders)."""
    tv = ET.Element("tv", {"source-info-name": "epg-generator", "generator-info-name": "epg_generator.py"})

    # canais
    for ch in channels:
        ch_el = ET.SubElement(tv, "channel", {"id": ch["tvg_id"]})
        display = ET.SubElement(ch_el, "display-name")
        display.text = ch["name"]

    # programas
    if csv_events:
        for ev in csv_events:
            try:
                start = dt.datetime.fromisoformat(ev["start"])
                stop = dt.datetime.fromisoformat(ev["stop"])
                if start.tzinfo is None:
                    start = start.replace(tzinfo=TZ)
                if stop.tzinfo is None:
                    stop = stop.replace(tzinfo=TZ)
            except Exception:
                continue
            prog = ET.SubElement(tv, "programme", {
                "start": format_xmltv_datetime(start),
                "stop": format_xmltv_datetime(stop),
                "channel": ev.get("tvg-id") or ev.get("tvg_id") or ev.get("channel", "unknown")
            })
            title = ET.SubElement(prog, "title")
            title.text = ev.get("title", "")
            desc = ET.SubElement(prog, "desc")
            desc.text = ev.get("desc", "")
    else:
        start_base = now_tz().replace(minute=0, second=0, microsecond=0)
        total_slots = hours
        for ch in channels:
            for i in range(total_slots):
                s = start_base + dt.timedelta(hours=i)
                e = s + dt.timedelta(hours=1)
                prog = ET.SubElement(tv, "programme", {
                    "start": format_xmltv_datetime(s),
                    "stop": format_xmltv_datetime(e),
                    "channel": ch["tvg_id"]
                })
                title = ET.SubElement(prog, "title")
                title.text = f"Program {i + 1} - {ch['name']}"
                desc = ET.SubElement(prog, "desc")
                desc.text = f"Programa gerado automaticamente para {ch['name']} — bloco {i + 1}"

    tree = ET.ElementTree(tv)
    tree.write(out_path, encoding="utf-8", xml_declaration=True)
    print(f"✅ EPG gerado com sucesso: {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("m3u", help="Caminho ou URL da playlist .m3u")
    parser.add_argument("--csv", help="CSV opcional com colunas tvg-id,start,stop,title,desc", default=None)
    parser.add_argument("--hours", type=int, default=48, help="Horas de programação a gerar (padrão: 48)")
    parser.add_argument("--out", default="epg.xml", help="Arquivo de saída (padrão: epg.xml)")
    args = parser.parse_args()

    text = load_m3u(args.m3u)
    channels = parse_m3u_text(text)
    csv_events = read_csv_schedule(args.csv) if args.csv else None
    build_xmltv(channels, csv_events, hours=args.hours, out_path=args.out)


if __name__ == "__main__":
    main()
