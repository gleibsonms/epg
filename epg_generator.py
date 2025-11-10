#!/usr/bin/env python3
"""
epg_generator.py
Gera epg.xml (XMLTV) a partir de uma playlist M3U (local ou URL).
Melhorias: pretty-print do XML, logs, --max-channels para testar.

OBS: este arquivo evita caracteres "especiais" (usar apenas - ao inves do travessao —)
para não gerar erros por copy/paste em ambientes que interpretam encoding de forma diferente.
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

from xml.dom import minidom

TZ = ZoneInfo("America/Recife")


def now_tz():
    return dt.datetime.now(TZ)


def load_m3u(path_or_url):
    """Carrega playlist M3U (arquivo local ou URL)."""
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        if not requests:
            print("Erro: modulo 'requests' nao disponivel. Instale com: pip install requests")
            sys.exit(2)
        try:
            r = requests.get(path_or_url, timeout=20)
            r.raise_for_status()
            return r.text
        except requests.exceptions.HTTPError as e:
            print(f"Erro HTTP ao baixar a playlist: {e}. URL: {path_or_url}")
            sys.exit(2)
        except requests.exceptions.RequestException as e:
            print(f"Erro de conexao ao baixar a playlist: {e}. URL: {path_or_url}")
            sys.exit(2)
    else:
        if not os.path.exists(path_or_url):
            print(f"Arquivo nao encontrado: {path_or_url}")
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
        print(f"CSV nao encontrado: {csv_path}")
        sys.exit(2)
    with open(csv_path, newline='', encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            events.append(row)
    return events


def format_xmltv_datetime(dtobj):
    """YYYYMMDDHHMMSS +ZZZZ (xmltv style)."""
    return dtobj.strftime("%Y%m%d%H%M%S %z")


def _pretty_xml_from_element(elem):
    """Retorna string bytes com pretty-printed XML (utf-8)."""
    rough_string = ET.tostring(elem, encoding="utf-8")
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ", encoding="utf-8")


def build_xmltv(channels, csv_events, hours=48, out_path="epg.xml", max_channels=None):
    """Constrói e grava XMLTV com pretty printing."""
    if max_channels:
        channels = channels[:max_channels]

    tv = ET.Element("tv", {"source-info-name": "epg-generator", "generator-info-name": "epg_generator.py"})

    for ch in channels:
        ch_el = ET.SubElement(tv, "channel", {"id": ch["tvg_id"]})
        display = ET.SubElement(ch_el, "display-name")
        display.text = ch["name"]

    if csv_events:
        for ev in csv_events:
            start = None
            stop = None
            try:
                start = dt.datetime.fromisoformat(ev["start"])
            except Exception:
                pass
            try:
                stop = dt.datetime.fromisoformat(ev["stop"])
            except Exception:
                pass

            if start is None or stop is None:
                continue
            if start.tzinfo is None:
                start = start.replace(tzinfo=TZ)
            if stop.tzinfo is None:
                stop = stop.replace(tzinfo=TZ)

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
                # usar apenas hyphen (-) e texto ASCII simples
                title.text = f"Program {i + 1} - {ch['name']}"
                desc = ET.SubElement(prog, "desc")
                desc.text = f"Programa gerado automaticamente para {ch['name']} - bloco {i + 1}"

    pretty_bytes = _pretty_xml_from_element(tv)
    try:
        with open(out_path, "wb") as f:
            f.write(pretty_bytes)
        print(f"EPG gerado: {out_path} (canais: {len(channels)})")
    except Exception as e:
        print(f"Erro ao escrever {out_path}: {e}")
        sys.exit(2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("m3u", help="Caminho ou URL da playlist .m3u")
    parser.add_argument("--csv", help="CSV opcional com colunas tvg-id,start,stop,title,desc", default=None)
    parser.add_argument("--hours", type=int, default=48, help="Horas a gerar (padrao 48)")
    parser.add_argument("--out", default="epg.xml", help="Arquivo de saida (padrao epg.xml)")
    parser.add_argument("--max-channels", type=int, default=0, help="Para testes: limite de canais (0 = sem limite)")
    args = parser.parse_args()

    print("Iniciando geracao de EPG...")
    text = load_m3u(args.m3u)
    channels = parse_m3u_text(text)
    if not channels:
        print("Nenhum canal encontrado na playlist. Verifique o arquivo M3U.")
        sys.exit(2)

    print(f"Canais detectados: {len(channels)}")
    max_c = args.max_channels if args.max_channels > 0 else None
    if max_c:
        print(f"Usando --max-channels {max_c} para teste (apenas os primeiros canais serao processados).")

    csv_events = read_csv_schedule(args.csv) if args.csv else None
    build_xmltv(channels, csv_events, hours=args.hours, out_path=args.out, max_channels=max_c)


if __name__ == "__main__":
    main()
