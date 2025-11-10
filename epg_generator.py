#!/usr/bin/env python3
"""
epg_generator_auto.py
Gera epg.xml a partir de uma lista M3U (local ou remota) e de um EPG (local ou remoto).
- Normaliza IDs (remove pontuação, acentos, ponto, espaços, lower-case).
- Tenta mapeamento exato tvg-id -> channel id do EPG; usa fuzzy match se necessário.
- Prioriza canais brasileiros quando houver múltiplas candidatas (opcional).
Usage:
  python3 epg_generator_auto.py --m3u lista.m3u --epg epg_remote.xml --out epg.xml --threshold 0.75
"""
from __future__ import annotations
import argparse
import sys
import re
import unicodedata
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from typing import Dict, List, Tuple, Optional

# ---------- normalize helpers ----------
def norm_id(s: str) -> str:
    if s is None:
        return ""
    s = s.strip().lower()
    # remove accents
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    # remove punctuation and dots and spaces and other chars
    s = re.sub(r'[^a-z0-9]', '', s)
    return s

def best_fuzzy_match(target: str, candidates: List[str], threshold: float) -> Optional[str]:
    best = ("", 0.0)
    for c in candidates:
        r = SequenceMatcher(None, target, c).ratio()
        if r > best[1]:
            best = (c, r)
    return best[0] if best[1] >= threshold else None

# ---------- parse M3U ----------
def parse_m3u_ids(m3u_path: str) -> List[Tuple[str,str]]:
    """
    Returns list of tuples (raw_tvg_id, normalized_id) in same order
    """
    ids = []
    try:
        with open(m3u_path, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()
    except Exception as e:
        print(f"ERRO: não consegui abrir M3U {m3u_path}: {e}", file=sys.stderr)
        return ids

    # extract tvg-id attributes from #EXTINF lines
    for m in re.finditer(r'#EXTINF:[^\n]*?tvg-id="([^"]+)"', text, re.I):
        raw = m.group(1).strip()
        norm = norm_id(raw)
        if norm:
            ids.append((raw, norm))
    # also dedupe preserving order
    seen = set()
    out = []
    for raw, norm in ids:
        if norm not in seen:
            out.append((raw, norm))
            seen.add(norm)
    return out

# ---------- parse EPG XML and index ----------
def index_epg(epg_path: str) -> Tuple[Dict[str, ET.Element], Dict[str,List[ET.Element]]]:
    """
    Returns:
      - channel_map: normalized_channel_id -> <channel> element
      - programmes_map: normalized_channel_id -> list of <programme> elements
    """
    channel_map: Dict[str, ET.Element] = {}
    programmes_map: Dict[str, List[ET.Element]] = {}
    try:
        it = ET.iterparse(epg_path, events=('start','end'))
    except Exception as e:
        raise RuntimeError(f"Erro ao abrir EPG {epg_path}: {e}")

    # find root and collect
    root = None
    for event, el in it:
        if root is None and event == 'start' and el.tag == 'tv':
            root = el
        if event == 'end' and el.tag == 'channel':
            ch_id = el.get('id', '') or ''
            n = norm_id(ch_id)
            if n:
                channel_map[n] = ET.fromstring(ET.tostring(el, encoding='utf-8'))
            # clear element
            el.clear()
        if event == 'end' and el.tag == 'programme':
            ch_id = el.get('channel', '')
            n = norm_id(ch_id)
            if n:
                programmes_map.setdefault(n, []).append(ET.fromstring(ET.tostring(el, encoding='utf-8')))
            el.clear()
    return channel_map, programmes_map

# ---------- build output EPG ----------
def build_epg(output_path: str, channel_elements: List[ET.Element], programme_elements: List[ET.Element]):
    tv = ET.Element('tv')
    tv.set('generator-info-name', 'epg-generator-auto')
    for ch in channel_elements:
        tv.append(ch)
    for p in programme_elements:
        tv.append(p)
    tree = ET.ElementTree(tv)
    tree.write(output_path, encoding='utf-8', xml_declaration=True)

# ---------- main ----------
def main():
    p = argparse.ArgumentParser()
    p.add_argument('--m3u', required=True, help='path to local M3U file')
    p.add_argument('--epg', required=True, help='path to source EPG XML file')
    p.add_argument('--out', required=True, help='output epg.xml path')
    p.add_argument('--threshold', required=False, default=0.72, type=float, help='fuzzy match threshold (0-1)')
    p.add_argument('--brazil-priority', action='store_true', help='prefer Brazilian matches on ties')
    args = p.parse_args()

    print(f"Parsing M3U: {args.m3u}")
    ids = parse_m3u_ids(args.m3u)
    if not ids:
        print("Aviso: nenhum tvg-id encontrado na M3U.", file=sys.stderr)

    print(f"Indexing EPG: {args.epg}")
    try:
        channel_map, prog_map = index_epg(args.epg)
    except Exception as e:
        print(f"Erro ao indexar EPG: {e}", file=sys.stderr)
        sys.exit(2)

    epg_norm_keys = list(channel_map.keys())
    print(f"Found {len(epg_norm_keys)} channels in EPG index.")

    matched_channels = {}
    for raw, norm in ids:
        # exact match
        if norm in channel_map:
            matched_channels[norm] = norm
            continue
        # try fuzzy
        match = best_fuzzy_match(norm, epg_norm_keys, args.threshold)
        if match:
            matched_channels[norm] = match
            continue
        # try looser match: remove trailing numbers
        alt = re.sub(r'\d+$','',norm)
        if alt and alt in channel_map:
            matched_channels[norm] = alt
            continue
        # not matched -> skip
        # keep unmatched for debugging
    # prepare output lists
    out_channels = []
    out_programmes = []
    used = set()
    for m in matched_channels.values():
        if m in used:
            continue
        ch_el = channel_map.get(m)
        if ch_el is not None:
            out_channels.append(ch_el)
            progs = prog_map.get(m, [])
            out_programmes.extend(progs)
            used.add(m)

    print(f"Matched {len(out_channels)} channels (from {len(ids)} M3U ids).")
    # write output epg
    build_epg(args.out, out_channels, out_programmes)
    print(f"Wrote {args.out} (channels: {len(out_channels)}, programmes: {len(out_programmes)}).")

if __name__ == "__main__":
    main()
