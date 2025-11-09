#!/usr/bin/env python3
"""
epg_generator.py v2
- Usa uma M3U (local ou URL) e opcionalmente um XMLTV (local ou URL) para
  gerar um epg.xml final (XMLTV).
- Se não houver EPG real disponível para um canal, cria programação simulada.

Usage:
  python epg_generator.py --m3u "playlist.m3u" [--epg "https://example.com/epg.xml"] [--out epg.xml] [--hours 48] [--tz-offset -3]
"""

import re
import sys
import argparse
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
import requests
from urllib.parse import urlparse

# ---------------------------
# Helpers
# ---------------------------
def fetch_text(src, timeout=30):
    """Return text from a url or local file."""
    if src is None:
        return None
    if src.startswith("http://") or src.startswith("https://"):
        headers = {"User-Agent": "Mozilla/5.0 (epg-generator/1.0)"}
        r = requests.get(src, timeout=timeout, headers=headers, allow_redirects=True)
        r.raise_for_status()
        return r.text
    else:
        with open(src, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

def parse_m3u(text):
    """Parse M3U content and return list of channel dicts."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    entries = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("#EXTINF:"):
            info = ln
            url = lines[i+1] if (i+1) < len(lines) and not lines[i+1].startswith("#EXTINF:") else ""
            tvg_id = (re.search(r'tvg-id="([^"]+)"', info) or re.search(r"tvg-id=([^ ,]+)", info))
            tvg_name = re.search(r',(.+)$', info)
            tvg_logo = re.search(r'tvg-logo="([^"]+)"', info)
            entries.append({
                "tvg-id": tvg_id.group(1) if tvg_id else None,
                "tvg-name": tvg_name.group(1).strip() if tvg_name else None,
                "tvg-logo": tvg_logo.group(1) if tvg_logo else None,
                "url": url
            })
            i += 2
        else:
            i += 1
    return entries

def normalize_name(s):
    if not s:
        return ""
    # lower, remove punctuation and multiple spaces
    s = s.lower()
    s = re.sub(r'[^0-9a-záàâãéèêíïóôõöúüçñ\s]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def parse_xmltv(text):
    """Return ElementTree root for an XMLTV text. None if text is None."""
    if not text:
        return None
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        # try to clean junk like <?xml ...> before
        # if fails, raise
        raise
    return root

def build_program_map(xml_root):
    """
    Build two maps from XMLTV:
      - by_channel_id: {channel_id: [programme elements]}
      - by_display_name_norm: {normalized_display_name: [programme elements]}
    """
    by_channel_id = {}
    # build map of channel id -> display-name normalized (for fallback)
    name_map = {}
    if xml_root is None:
        return by_channel_id, name_map

    for ch in xml_root.findall("channel"):
        cid = ch.get("id")
        dn = ch.find("display-name")
        dn_text = dn.text if dn is not None else ""
        name_map[cid] = normalize_name(dn_text)

    # collect programmes
    for prog in xml_root.findall("programme"):
        ch = prog.get("channel")
        if ch:
            by_channel_id.setdefault(ch, []).append(prog)
    return by_channel_id, name_map

def dt_to_xmltv(dt, tz_offset_hours):
    """
    dt: naive datetime in UTC + tz_offset_hours (i.e. local time)
    Returns: 'YYYYmmddThhMMss +/-HHMM'
    """
    # offset like -3 -> '-0300'
    sign = '+' if tz_offset_hours >= 0 else '-'
    off = abs(int(tz_offset_hours))
    off_str = f"{off:02d}00"
    return dt.strftime("%Y%m%dT%H%M%S ") + (f"{sign}{off_str}")

# ---------------------------
# Main builder
# ---------------------------
def build_xmltv_output(channels_entries, program_map, name_map, hours=48, tz_offset_hours=-3):
    tv = ET.Element("tv", attrib={"generator-info-name": "epg-generator-v2"})
    # channels first
    for e in channels_entries:
        cid = e.get("tvg-id") or (e.get("tvg-name") or e.get("url"))[:60]
        ch = ET.SubElement(tv, "channel", attrib={"id": cid})
        dn = ET.SubElement(ch, "display-name")
        dn.text = e.get("tvg-name") or cid
        logo = e.get("tvg-logo")
        if logo:
            ET.SubElement(ch, "icon", attrib={"src": logo})

    # prepare a starting point (local time with tz offset)
    now = datetime.utcnow() + timedelta(hours=tz_offset_hours)
    now = now.replace(minute=0, second=0, microsecond=0)

    for idx, e in enumerate(channels_entries):
        cid = e.get("tvg-id") or (e.get("tvg-name") or e.get("url"))[:60]
        # try exact tvg-id matches in program_map
        progs = program_map.get(cid)
        if progs:
            # copy those programme nodes into output (but ensure start/stop formatting preserved)
            for p in progs:
                # Append a deep copy (ET doesn't have copy, so re-create)
                new_p = ET.SubElement(tv, "programme", attrib={
                    "start": p.get("start", ""),
                    "stop": p.get("stop", ""),
                    "channel": cid
                })
                title = p.find("title")
                desc = p.find("desc") or p.find("description")
                if title is not None and title.text:
                    ET.SubElement(new_p, "title").text = title.text
                if desc is not None and desc.text:
                    ET.SubElement(new_p, "desc").text = desc.text
            continue

        # try fuzzy match by normalized display-name
        norm = normalize_name(e.get("tvg-name") or "")
        found = False
        if norm and name_map:
            # search for best matching channel id in name_map
            for chid, chnorm in name_map.items():
                if norm == chnorm or norm in chnorm or chnorm in norm:
                    progs = program_map.get(chid)
                    if progs:
                        for p in progs:
                            new_p = ET.SubElement(tv, "programme", attrib={
                                "start": p.get("start", ""),
                                "stop": p.get("stop", ""),
                                "channel": cid
                            })
                            title = p.find("title")
                            desc = p.find("desc") or p.find("description")
                            if title is not None and title.text:
                                ET.SubElement(new_p, "title").text = title.text
                            if desc is not None and desc.text:
                                ET.SubElement(new_p, "desc").text = desc.text
                        found = True
                        break
        if found:
            continue

        # fallback: generate simulated schedule (1h slots)
        for h in range(hours):
            start = now + timedelta(hours=h + idx)  # small offset per channel for variety
            stop = start + timedelta(hours=1)
            p = ET.SubElement(tv, "programme", attrib={
                "start": dt_to_xmltv(start, tz_offset_hours),
                "stop": dt_to_xmltv(stop, tz_offset_hours),
                "channel": cid
            })
            ET.SubElement(p, "title").text = f"Programa Exemplo {h+1}"
            ET.SubElement(p, "desc").text = f"Programa gerado automaticamente para {cid}."

    return tv

# ---------------------------
# CLI
# ---------------------------
def main():
    parser = argparse.ArgumentParser(description="Generate XMLTV EPG from M3U and optional XMLTV merge.")
    parser.add_argument("--m3u", required=True, help="M3U source (file path or URL).")
    parser.add_argument("--epg", required=False, default=None, help="Optional XMLTV source (file path or URL) to merge from.")
    parser.add_argument("--out", required=False, default="epg.xml", help="Output XMLTV file.")
    parser.add_argument("--hours", required=False, type=int, default=48, help="Hours for fallback simulated schedule.")
    parser.add_argument("--tz-offset", required=False, type=int, default=-3, help="Timezone offset hours for output timestamps (e.g. -3 for BRT).")
    args = parser.parse_args()

    try:
        print("[1/4] Fetching M3U:", args.m3u)
        m3u_text = fetch_text(args.m3u)
        channels = parse_m3u(m3u_text)
        print(f"[2/4] Parsed M3U channels: {len(channels)}")
    except Exception as ex:
        print("ERROR fetching/parsing M3U:", ex)
        sys.exit(2)

    xml_root = None
    program_map = {}
    name_map = {}
    if args.epg:
        try:
            print("[3/4] Fetching EPG source:", args.epg)
            epg_text = fetch_text(args.epg)
            xml_root = parse_xmltv(epg_text)
            program_map, name_map = build_program_map(xml_root)
            print(f"[3/4] Parsed EPG channels: {len(name_map)}; programmes collected: {sum(len(v) for v in program_map.values()):,}")
        except Exception as ex:
            print("WARN: could not fetch/parse EPG, will use simulated schedules as fallback.", ex)
            xml_root = None
            program_map = {}
            name_map = {}

    print("[4/4] Building output XMLTV...")
    out_tree = build_xmltv_output(channels, program_map, name_map, hours=args.hours, tz_offset_hours=args.tz_offset)
    ET.ElementTree(out_tree).write(args.out, encoding="utf-8", xml_declaration=True)
    print("Done. Output saved to", args.out)

if __name__ == "__main__":
    main()
