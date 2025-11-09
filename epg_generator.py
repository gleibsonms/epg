#!/usr/bin/env python3
"""
EPG generator com normalização e fuzzy matching entre M3U e EPG.

Funcionalidades principais:
- Lê lista M3U local ou por URL (--m3u)
- Tenta carregar EPG XMLTV (--epg opcional)
- Normaliza nomes/ids (remove pontos, underlines, hífens e espaços, deixa lowercase)
- Faz match exato normalizado; se falhar, usa fuzzy matching (difflib)
- Reescreve o atributo 'channel' nos <programme> para o ID vindo da M3U
- Salva epg.xml pronto para uso no player (IDs coerentes com a M3U)
- Permite arquivo opcional channel_map.json para mapeamentos manuais
"""
import argparse
import requests
import gzip
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from difflib import SequenceMatcher, get_close_matches
import json
import os
import sys
from io import BytesIO

# ---------------------------
# Configurações
# ---------------------------
FUZZY_THRESHOLD = 0.72  # similaridade mínima para aceitar correspondência fuzzy
MANUAL_MAP_FILE = "channel_map.json"  # opcional: {"epg_id_or_name": "m3u_id"}
# ---------------------------

def normalize(s: str) -> str:
    if not s:
        return ""
    s = s.lower()
    # remove acentos (opcional: descomente se quiser normalizar acentos)
    # import unicodedata
    # s = ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))
    # remove caracteres comuns que geram mismatch (ponto, underline, hífen, espaços)
    for ch in ['.', '_', '-', ' ' , ':', '/', '\\']:
        s = s.replace(ch, '')
    # strip
    return s.strip()

def download_bytes(url, timeout=60):
    print(f"🔽 Downloading: {url}")
    r = requests.get(url, timeout=timeout, headers={"User-Agent":"epg-generator/1.0"}, allow_redirects=True)
    r.raise_for_status()
    return r.content

def load_m3u_from_file_or_url(path_or_url):
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        b = download_bytes(path_or_url)
        text = b.decode("utf-8", errors="ignore")
    else:
        with open(path_or_url, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    return text

def parse_m3u(text):
    channels = []
    current = {"name": None, "attrs": {}}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            # parse basic form; keep full name
            # e.g. #EXTINF:-1 tvg-id="globosp" tvg-name="GLOBO SP" group-title="BR",GLOBO SP FHD
            name = line.split(",", 1)[1].strip() if "," in line else line
            current = {"name": name, "attrs": {}}
            # optional: try to extract tvg-id
            if 'tvg-id="' in line:
                try:
                    tvg = line.split('tvg-id="',1)[1].split('"',1)[0].strip()
                    current["attrs"]["tvg-id"] = tvg
                except Exception:
                    pass
        elif line.startswith("http://") or line.startswith("https://"):
            current["url"] = line
            # derive an ID for this channel based on tvg-id if present, else from name normalized
            if "tvg-id" in current["attrs"] and current["attrs"]["tvg-id"]:
                ch_id = current["attrs"]["tvg-id"]
            else:
                ch_id = normalize(current["name"])
            channels.append({"id": ch_id, "name": current["name"], "url": current.get("url"), "attrs": current["attrs"]})
            current = {"name": None, "attrs": {}}
    return channels

def safe_load_epg_root(epg_url):
    try:
        print(f"🧠 Loading EPG from: {epg_url}")
        data = download_bytes(epg_url)
        # handle gz
        if epg_url.endswith(".gz") or (len(data) >= 2 and data[:2] == b'\x1f\x8b'):
            print("🗜️ Detected gzip; decompressing...")
            data = gzip.decompress(data)
        root = ET.fromstring(data)
        print("✅ EPG loaded.")
        return root
    except Exception as e:
        print(f"⚠️ Could not load EPG from {epg_url}: {e}")
        return None

def build_channel_lookup(m3u_channels):
    """
    Retorna:
      - map_normal_to_m3u_id: {normalized_name: m3u_id}
      - m3u_id_to_display: {m3u_id: display_name}
    """
    map_norm = {}
    m3u_id_to_display = {}
    for ch in m3u_channels:
        m3u_id = ch["id"]
        display = ch["name"] or m3u_id
        # se id tem caracteres estranhos normaliza também
        n1 = normalize(m3u_id)
        n2 = normalize(display)
        map_norm[n1] = m3u_id
        map_norm[n2] = m3u_id
        # também incluir tvg-id se houver (já no id)
        m3u_id_to_display[m3u_id] = display
    return map_norm, m3u_id_to_display

def fuzzy_match_key(key, candidates_map):
    """
    key: string to match (already normalized)
    candidates_map: dict normalized->m3u_id
    Retorna m3u_id ou None
    """
    if not key:
        return None
    # exact
    if key in candidates_map:
        return candidates_map[key]
    # try close matches using difflib on the keys of candidates_map
    keys = list(candidates_map.keys())
    if not keys:
        return None
    matches = get_close_matches(key, keys, n=3, cutoff=FUZZY_THRESHOLD)
    if matches:
        best = matches[0]
        return candidates_map.get(best)
    # fallback: compute ratios and pick best
    best_ratio = 0.0
    best_id = None
    for k in keys:
        ratio = SequenceMatcher(None, key, k).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_id = candidates_map[k]
    if best_ratio >= FUZZY_THRESHOLD:
        return best_id
    return None

def read_manual_map():
    if os.path.exists(MANUAL_MAP_FILE):
        try:
            with open(MANUAL_MAP_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # normalize keys and values
                norm_map = {}
                for k,v in data.items():
                    nk = normalize(k)
                    nv = v  # target should be the M3U id as you want it to appear
                    norm_map[nk] = nv
                return norm_map
        except Exception as e:
            print(f"⚠️ Erro lendo {MANUAL_MAP_FILE}: {e}")
            return {}
    return {}

def build_epg(m3u_channels, source_epg_root, tz_offset=-3, hours=72):
    # root tv
    root = ET.Element("tv", attrib={"generator-info-name": "br-epg-generator-v2"})
    now = datetime.utcnow() + timedelta(hours=tz_offset)
    # create channel elements from M3U (ensures IDs match M3U)
    for ch in m3u_channels:
        ch_id = ch["id"]
        ce = ET.SubElement(root, "channel", id=ch_id)
        ET.SubElement(ce, "display-name").text = ch["name"]
    # prepare lookup maps
    norm_map, m3u_id_to_display = build_channel_lookup(m3u_channels)
    manual = read_manual_map()
    # if source_epg_root exists, iterate programmes and map channel attr
    if source_epg_root is not None:
        prog_count = 0
        mapped_count = 0
        for prog in source_epg_root.findall("programme"):
            prog_ch_raw = prog.attrib.get("channel", "")
            # try to get channel id from programme attribute or display-name inside epg channel elements
            # strategy: normalize prog_ch_raw, check manual map, exact normalized, fuzzy
            n = normalize(prog_ch_raw)
            target_m3u_id = None
            # manual mapping preferred
            if n in manual:
                target_m3u_id = manual[n]
                reason = f"manual({n})"
            else:
                # direct normalized exact
                if n in norm_map:
                    target_m3u_id = norm_map[n]
                    reason = f"exact_norm({n})"
                else:
                    # try fuzzy on program channel id
                    fm = fuzzy_match_key(n, norm_map)
                    if fm:
                        target_m3u_id = fm
                        reason = f"fuzzy_progch({n})"
                    else:
                        # as fallback, try to inspect <channel> entries in source_epg_root for display-name matching
                        # build small map from epg channel display-names to epg channel id (normalized)
                        epg_ch_map = {}
                        for ch_el in source_epg_root.findall("channel"):
                            chid = ch_el.attrib.get("id","")
                            dd = ch_el.find("display-name")
                            if dd is not None and dd.text:
                                epg_ch_map[normalize(dd.text)] = normalize(chid) or normalize(dd.text)
                        # try match between program's channel normalized and epg channel display-name
                        if n in epg_ch_map:
                            candidate = epg_ch_map[n]
                           ; # candidate is normalized epg id/display
                            fm2 = fuzzy_match_key(candidate, norm_map)
                            if fm2:
                                target_m3u_id = fm2
                                reason = f"fuzzy_via_epg_channel({candidate})"
            prog_count += 1
            if target_m3u_id:
                # append a copy of programme but change channel to m3u id
                attrib = dict(prog.attrib)
                attrib["channel"] = target_m3u_id
                newp = ET.SubElement(root, "programme", attrib)
                # copy title/desc if present
                title = prog.find("title")
                if title is not None and title.text:
                    ET.SubElement(newp, "title").text = title.text
                desc = prog.find("desc")
                if desc is not None and desc.text:
                    ET.SubElement(newp, "desc").text = desc.text
                mapped_count += 1
                print(f"Mapped prog ch '{prog_ch_raw}' -> '{target_m3u_id}' ({reason})")
            else:
                # do not append unmapped programmes (we'll create placeholders later)
                # optionally you could append them unchanged; decision: skip to avoid wrong channel IDs
                # print(f"Could not map prog channel '{prog_ch_raw}' (normalized '{n}')")
                pass
        print(f"Processed {prog_count} programmes from source EPG; mapped {mapped_count}.")
    else:
        print("No source EPG provided; will generate placeholders for all channels.")

    # For each channel ensure it has at least some programmes (placeholder) if none mapped
    for ch_id in m3u_id_to_display.keys():
        has_prog = any(p.attrib.get("channel") == ch_id for p in root.findall("programme"))
        if not has_prog:
            # create simple placeholders (6 x 1h)
            for i in range(6):
                start = now + timedelta(hours=i)
                stop = start + timedelta(hours=1)
                p = ET.SubElement(root, "programme", {
                    "start": start.strftime("%Y%m%d%H%M%S +0000"),
                    "stop": stop.strftime("%Y%m%d%H%M%S +0000"),
                    "channel": ch_id
                })
                ET.SubElement(p, "title").text = f"Programa Exemplo {i+1}"
                ET.SubElement(p, "desc").text = "Sem informações no momento."
    return ET.ElementTree(root)

def save_tree(tree, path):
    tree.write(path, encoding="utf-8", xml_declaration=True)
    print(f"💾 Saved EPG file: {path}")

def main():
    parser = argparse.ArgumentParser(description="EPG generator com normalização/fuzzy entre M3U e EPG")
    parser.add_argument("--m3u", required=True, help="arquivo M3U local ou URL")
    parser.add_argument("--epg", required=False, help="EPG XMLTV URL (opcional)")
    parser.add_argument("--out", default="epg.xml", help="arquivo de saída")
    parser.add_argument("--tz-offset", type=int, default=-3, help="offset do fuso (default -3)")
    parser.add_argument("--hours", type=int, default=72, help="horas para placeholders")
    args = parser.parse_args()

    # Load M3U
    try:
        m3u_text = load_m3u_from_file_or_url(args.m3u)
    except Exception as e:
        print(f"❌ Erro ao carregar M3U '{args.m3u}': {e}")
        sys.exit(1)

    m3u_chs = parse_m3u(m3u_text)
    print(f"📺 {len(m3u_chs)} canais encontrados na M3U.")

    # Load remote EPG if provided
    epg_root = None
    if args.epg:
        epg_root = safe_load_epg_root(args.epg)

    tree = build_epg(m3u_chs, epg_root, tz_offset=args.tz_offset, hours=args.hours)
    save_tree(tree, args.out)
    print("✅ Geração finalizada.")

if __name__ == "__main__":
    main()
