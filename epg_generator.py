#!/usr/bin/env python3
# epg_generator.py - adapted to read a local M3U or a URL and generate epg.xml (48h)
# Usage: python epg_generator.py <m3u_source_or_url>
import re, sys, time
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

try:
    import requests
except ImportError:
    requests = None

SRC = sys.argv[1] if len(sys.argv)>1 else "playlist.m3u"
OUT = "epg.xml"
TZ_OFFSET_HOURS = -3  # Recife / America/Recife

def fetch(src):
    if src.startswith("http://") or src.startswith("https://"):
        if requests is None:
            raise RuntimeError("requests is required to fetch URLs. Install with: pip install requests")
        headers = {
            "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept":"*/*"
        }
        r = requests.get(src, headers=headers, timeout=30)
        r.raise_for_status()
        return r.text
    else:
        with open(src, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

def parse_m3u(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    entries=[]
    i=0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("#EXTINF:"):
            info = ln
            url = lines[i+1] if i+1 < len(lines) and not lines[i+1].startswith("#EXTINF:") else ""
            tvg_id = re.search(r'tvg-id="([^"]+)"', info)
            tvg_name = re.search(r',(.+)$', info)
            tvg_logo = re.search(r'tvg-logo="([^"]+)"', info)
            entries.append({
                'tvg-id': tvg_id.group(1) if tvg_id else None,
                'tvg-name': tvg_name.group(1).strip() if tvg_name else None,
                'tvg-logo': tvg_logo.group(1) if tvg_logo else None,
                'url': url
            })
            i += 2
        else:
            i += 1
    return entries

def dt_to_xmltv(dt):
    return dt.strftime("%Y%m%dT%H%M%S ") + ("{:+03d}00".format(TZ_OFFSET_HOURS))

def build_xml(entries, hours=48):
    tv = ET.Element('tv', attrib={'generator-info-name':'epg-generator-from-m3u'})
    for e in entries:
        cid = e['tvg-id'] or (e.get('tvg-name') or e.get('url'))[:60]
        c = ET.SubElement(tv,'channel',attrib={'id':cid})
        ET.SubElement(c,'display-name').text = e.get('tvg-name') or cid
        if e.get('tvg-logo'):
            ET.SubElement(c,'icon', attrib={'src': e.get('tvg-logo')})

    now = datetime.utcnow() + timedelta(hours=TZ_OFFSET_HOURS)
    now = now.replace(minute=0, second=0, microsecond=0)
    for idx,e in enumerate(entries):
        cid = e['tvg-id'] or (e.get('tvg-name') or e.get('url'))[:60]
        for h in range(hours):
            start = now + timedelta(hours=h + idx)
            stop = start + timedelta(hours=1)
            p = ET.SubElement(tv,'programme', attrib={
                'start': dt_to_xmltv(start),
                'stop': dt_to_xmltv(stop),
                'channel': cid
            })
            ET.SubElement(p,'title').text = f"Programa Exemplo {h+1}"
            ET.SubElement(p,'desc').text = f"Descrição automática para {cid}."
    return tv

def save(tv, out=OUT):
    tree = ET.ElementTree(tv)
    tree.write(out, encoding='utf-8', xml_declaration=True)
    print("EPG salvo em", out)

def main():
    text = fetch(SRC)
    entries = parse_m3u(text)
    print("Canais detectados:", len(entries))
    if not entries:
        print("Nenhum canal encontrado na M3U.")
        return
    tv = build_xml(entries, hours=48)
    save(tv)

if __name__ == "__main__":
    main()
