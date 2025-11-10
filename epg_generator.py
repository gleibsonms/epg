#!/usr/bin/env python3
"""
epg_generator.py
Gera epg.xml (XMLTV) a partir de uma playlist M3U (local ou URL).
Opcional: CSV com colunas tvg-id,start,stop,title,desc para uma grade real.
Uso:
  python epg_generator.py /caminho/para/playlist.m3u [--csv minha_grade.csv] [--hours 48] [--out epg.xml]
"""
import argparse
import csv
import datetime as dt
import sys
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

try:
    import requests
except Exception:
    requests = None

TZ = ZoneInfo("America/Recife")

def now_tz():
    return dt.datetime.now(TZ)

def parse_m3u_text(text):
    # Retorna lista de dicts: {tvg_id, name, url}
    lines = [l.strip() for l in text.splitlines() if l.strip() != ""]
    channels = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#EXTINF"):
            # Exemplo: #EXTINF:-1 tvg-id="canal1" tvg-name="Canal 1",Canal 1
            attrs_part = line.split(" ", 1)[1] if " " in line else ""
            tvg_id = None
            name = None
            # tenta extrair tvg-id e nome
            if 'tvg-id=' in line:
                import re
                m = re.search(r'tvg-id="([^"]+)"', line)
                if m: tvg_id = m.group(1)
            if ',' in line:
                name = line.split(",", 1)[1].strip()
            # url é a próxima linha (se existir)
            url = lines[i+1] if i+1 < len(lines) and not lines[i+1].startswith("#") else ""
            channels.append({"tvg_id": tvg_id or name or f"chan{i}", "name": name or tvg_id or f"chan{i}", "url": url})
            i += 2
        else:
            i += 1
    return channels

def load_m3u(path_or_url):
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        if not requests:
            raise RuntimeError("requests não está disponível. Instale com: pip install requests")
        r = requests.get(path_or_url, timeout=20)
        r.raise_for_status()
        return r.text
    else:
        with open(path_or_url, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

def read_csv_schedule(csv_path):
    events = []
    with open(csv_path, newline='', encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # expects tvg-id,start,stop,title,desc
            events.append(row)
    return events

def format_xmltv_datetime(dtobj):
    # formato: YYYYMMDDHHMMSS +0000 (offset)
    # datetime is tz-aware
    return dtobj.strftime("%Y%m%d%H%M%S %z")

def build_xmltv(channels, csv_events, hours=48, out_path="epg.xml"):
    tv = ET.Element("tv", {"source-info-name": "epg-generator", "generator-info-name": "epg_generator.py"})
    # channels
    for ch in channels:
        ch_el = ET.SubElement(tv, "channel", {"id": ch["tvg_id"]})
        display = ET.SubElement(ch_el, "display-name")
        display.text = ch["name"]

    # programmes
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
                # tenta parse básico dd/mm/YYYY HH:MM ou similar
                # fallback: pular evento inválido
                continue
            prog = ET.SubElement(tv, "programme", {
                "start": format_xmltv_datetime(start),
                "stop": format_xmltv_datetime(stop),
                "channel": ev.get("tvg-id") or ev.get("tvg_id") or ev.get("channel","unknown")
            })
            title = ET.SubElement(prog, "title")
            title.text = ev.get("title","")
            desc = ET.SubElement(prog, "desc")
            desc.text = ev.get("desc","")
    else:
        # gera placeholders hora-a-hora para cada canal
        start_base = now_tz().replace(minute=0,second=0,microsecond=0)
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
                title.text = f"Program {i+1} - {ch['name']}"
                desc = ET.SubElement(prog, "desc")
                desc.text = f"Programa gerado automaticamente para {ch['name']} — bloco {i+1}"
    # escrever com declaração XML
    tree = ET.ElementTree(tv)
    tree.write(out_path, encoding="utf-8", xml_declaration=True)
    print(f"EPG escrito em: {out_path}")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("m3u", help="Caminho ou URL da playlist .m3u")
    p.add_argument("--csv", help="CSV opcional com colunas tvg-id,start,stop,title,desc", default=None)
    p.add_argument("--hours", type=int, default=48, help="Quantas horas gerar (padrao 48)")
    p.add_argument("--out", default="epg.xml", help="Arquivo de saída (padrao epg.xml)")
    args = p.parse_args()

    text = load_m3u(args.m3u)
    channels = parse_m3u_text(text)
    csv_events = read_csv_schedule(args.csv) if args.csv else None
    build_xmltv(channels, csv_events, hours=args.hours, out_path=args.out)

if __name__ == "__main__":
    main()
