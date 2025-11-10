#!/usr/bin/env python3
"""
epg_generator.py
Combina M3U local com EPG externo (XMLTV) e gera EPG final corrigido.
Agora normaliza IDs automaticamente (ex.: globospapulo → globosp).
"""

import argparse
import datetime as dt
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET
import sys, os, re, unicodedata
from xml.dom import minidom

try:
    import requests
except ImportError:
    requests = None

TZ = ZoneInfo("America/Recife")

def normalize_id(s):
    """Remove acentos, espaços e caracteres especiais, converte para minúsculo."""
    if not s:
        return ""
    s = s.lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")  # remove acentos
    s = re.sub(r"[^a-z0-9]", "", s)  # só letras e números
    return s

def load_text(path_or_url):
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        if not requests:
            print("Erro: módulo 'requests' ausente.")
            sys.exit(2)
        try:
            r = requests.get(path_or_url, timeout=30)
            r.raise_for_status()
            return r.text
        except Exception as e:
            print(f"Erro ao baixar {path_or_url}: {e}")
            sys.exit(2)
    else:
        with open(path_or_url, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

def parse_m3u(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    channels = []
    i = 0
    while i < len(lines):
        if lines[i].startswith("#EXTINF"):
            m_id = re.search(r'tvg-id="([^"]+)"', lines[i])
            tvg_id = m_id.group(1) if m_id else None
            name = lines[i].split(",")[-1].strip()
            url = lines[i + 1] if i + 1 < len(lines) else ""
            channels.append({
                "tvg_id": tvg_id or normalize_id(name),
                "name": name,
                "url": url,
                "norm": normalize_id(tvg_id or name)
            })
            i += 2
        else:
            i += 1
    return channels

def parse_external_epg(epg_source):
    """Retorna {norm_channel_id: [eventos]} do EPG externo."""
    text = load_text(epg_source)
    root = ET.fromstring(text.encode("utf-8"))
    events_by_norm = {}
    for prog in root.findall("programme"):
        ch = prog.get("channel")
        if not ch:
            continue
        norm_ch = normalize_id(ch)
        title = (prog.findtext("title") or "").strip()
        desc = (prog.findtext("desc") or "").strip()
        start = prog.get("start")
        stop = prog.get("stop")
        events_by_norm.setdefault(norm_ch, []).append({
            "start": start,
            "stop": stop,
            "title": title,
            "desc": desc
        })
    return events_by_norm

def pretty_xml(elem):
    rough = ET.tostring(elem, encoding="utf-8")
    reparsed = minidom.parseString(rough)
    return reparsed.toprettyxml(indent="  ", encoding="utf-8")

def build_epg(m3u_channels, epg_events, out_path):
    tv = ET.Element("tv", {"generator-info-name": "epg-generator"})
    for ch in m3u_channels:
        ch_el = ET.SubElement(tv, "channel", {"id": ch["tvg_id"]})
        disp = ET.SubElement(ch_el, "display-name")
        disp.text = ch["name"]

        events = epg_events.get(ch["norm"])
        if events:
            for ev in events[:48]:  # limitar 48h por segurança
                prog = ET.SubElement(tv, "programme", {
                    "start": ev["start"],
                    "stop": ev["stop"],
                    "channel": ch["tvg_id"]
                })
                ET.SubElement(prog, "title").text = ev["title"]
                ET.SubElement(prog, "desc").text = ev["desc"]
        else:
            # fallback placeholder
            base = dt.datetime.now(TZ).replace(minute=0, second=0, microsecond=0)
            for i in range(48):
                s = base + dt.timedelta(hours=i)
                e = s + dt.timedelta(hours=1)
                prog = ET.SubElement(tv, "programme", {
                    "start": s.strftime("%Y%m%d%H%M%S %z"),
                    "stop": e.strftime("%Y%m%d%H%M%S %z"),
                    "channel": ch["tvg_id"]
                })
                ET.SubElement(prog, "title").text = f"Program {i+1} - {ch['name']}"
                ET.SubElement(prog, "desc").text = f"Gerado automaticamente - {ch['name']} - Bloco {i+1}"
    xml_bytes = pretty_xml(tv)
    with open(out_path, "wb") as f:
        f.write(xml_bytes)
    print(f"✅ EPG mesclado gerado: {out_path}")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("m3u", help="Caminho ou URL da playlist .m3u")
    p.add_argument("--epg-source", help="EPG externo (URL ou arquivo XML)", required=True)
    p.add_argument("--out", default="epg.xml", help="Arquivo de saída")
    args = p.parse_args()

    print("Carregando M3U...")
    m3u_channels = parse_m3u(load_text(args.m3u))
    print(f"Canais detectados: {len(m3u_channels)}")

    print("Carregando EPG externo...")
    epg_events = parse_external_epg(args.epg_source)
    print(f"Canais com eventos no EPG externo: {len(epg_events)}")

    build_epg(m3u_channels, epg_events, args.out)

if __name__ == "__main__":
    main()
