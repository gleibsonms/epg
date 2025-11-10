#!/usr/bin/env python3
import argparse
import xml.etree.ElementTree as ET
from difflib import get_close_matches
import json
import re
from pathlib import Path

def normalize_id(value):
    if not value:
        return ""
    # Remove espaços, pontos, hífens e coloca tudo em minúsculo
    value = re.sub(r'[^a-zA-Z0-9]', '', value)
    return value.lower()

def load_channel_map():
    """Carrega mapa manual (opcional) channel_map.json"""
    mapping_file = Path("channel_map.json")
    if mapping_file.exists():
        try:
            with open(mapping_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[AVISO] Erro ao carregar channel_map.json: {e}")
    return {}

def parse_args():
    p = argparse.ArgumentParser(description="Gerador de EPG a partir de M3U e XML EPG existente")
    p.add_argument("--m3u", required=True, help="Arquivo M3U de entrada")
    p.add_argument("--epg", required=True, help="Arquivo EPG XML existente")
    p.add_argument("--out", required=True, help="Arquivo de saída (novo EPG)")
    p.add_argument("--threshold", type=float, default=0.7, help="Limite de similaridade (0-1)")
    return p.parse_args()

def main():
    args = parse_args()

    print(f"Lendo lista M3U: {args.m3u}")
    with open(args.m3u, "r", encoding="utf-8", errors="ignore") as f:
        m3u_lines = f.readlines()

    m3u_ids = []
    for line in m3u_lines:
        if "tvg-id=" in line:
            match = re.search(r'tvg-id="([^"]+)"', line)
            if match:
                m3u_ids.append(match.group(1))

    print(f"Encontrados {len(m3u_ids)} canais na M3U")

    print(f"Lendo EPG base: {args.epg}")
    tree = ET.parse(args.epg)
    root = tree.getroot()

    epg_channels = {}
    for ch in root.findall("channel"):
        cid = ch.attrib.get("id")
        if cid:
            epg_channels[normalize_id(cid)] = ch.attrib["id"]

    print(f"Indexados {len(epg_channels)} canais do EPG")

    channel_map = load_channel_map()
    matches = 0

    new_root = ET.Element("tv", attrib=root.attrib)

    for m3u_id in m3u_ids:
        normalized_m3u_id = normalize_id(m3u_id)
        match_id = None

        # 1️⃣ tenta mapa manual
        if m3u_id in channel_map:
            match_id = channel_map[m3u_id]
        else:
            # 2️⃣ tenta match direto
            if normalized_m3u_id in epg_channels:
                match_id = epg_channels[normalized_m3u_id]
            else:
                # 3️⃣ fuzzy match se não achou
                possible = get_close_matches(normalized_m3u_id, epg_channels.keys(), n=1, cutoff=args.threshold)
                if possible:
                    match_id = epg_channels[possible[0]]

        if match_id:
            matches += 1
            # copia canal + programas
            for elem in root.findall(f".//channel[@id='{match_id}']"):
                new_root.append(elem)
            for prog in root.findall(f".//programme[@channel='{match_id}']"):
                new_root.append(prog)

    print(f"Correspondências: {matches} de {len(m3u_ids)} canais")

    ET.ElementTree(new_root).write(args.out, encoding="utf-8", xml_declaration=True)
    print(f"Novo EPG salvo em {args.out}")

if __name__ == "__main__":
    main()
