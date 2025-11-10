#!/usr/bin/env python3
import re
import xml.etree.ElementTree as ET
from unidecode import unidecode
from difflib import get_close_matches
import argparse

def normalize_name(name):
    """Remove acentos, pontuação e deixa minúsculo para comparação."""
    name = unidecode(name).lower()
    name = re.sub(r'[^a-z0-9]', '', name)
    return name

def parse_m3u(path):
    """Extrai tvg-id e nome do canal da lista M3U"""
    channels = {}
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("#EXTINF"):
                id_match = re.search(r'tvg-id="([^"]+)"', line)
                name_match = re.search(r',([^,\n\r]+)$', line.strip())
                if id_match:
                    tvgid = id_match.group(1).strip()
                    name = name_match.group(1).strip() if name_match else tvgid
                    channels[normalize_name(name)] = tvgid
    return channels

def rename_epg_channels(epg_path, m3u_channels, out_path):
    """Renomeia canais e programas no EPG para casar com os IDs da M3U"""
    tree = ET.parse(epg_path)
    root = tree.getroot()
    epg_channels = [ch.attrib.get("id") for ch in root.findall("channel") if ch.attrib.get("id")]

    renamed = 0
    for ch in root.findall("channel"):
        original_id = ch.attrib.get("id")
        norm_id = normalize_name(original_id)

        match = get_close_matches(norm_id, m3u_channels.keys(), n=1, cutoff=0.6)
        if match:
            new_id = m3u_channels[match[0]]
            for prog in root.findall(f".//programme[@channel='{original_id}']"):
                prog.attrib["channel"] = new_id
            ch.attrib["id"] = new_id
            renamed += 1

    tree.write(out_path, encoding="utf-8", xml_declaration=True)
    print(f"✔ Renomeados {renamed} canais no EPG.")
    print(f"Novo EPG salvo em: {out_path}")

def main():
    parser = argparse.ArgumentParser(description="Renomeia canais do EPG conforme IDs da lista M3U.")
    parser.add_argument("--m3u", required=True, help="Arquivo M3U de entrada (ex: lista.m3u)")
    parser.add_argument("--epg", required=True, help="Arquivo EPG original (ex: epg.xml ou epg_remote.xml)")
    parser.add_argument("--out", required=True, help="Arquivo de saída (novo epg.xml)")
    args = parser.parse_args()

    print(f"🔹 Lendo lista M3U: {args.m3u}")
    m3u_channels = parse_m3u(args.m3u)
    print(f"Encontrados {len(m3u_channels)} canais na M3U")

    print(f"🔹 Lendo EPG original: {args.epg}")
    rename_epg_channels(args.epg, m3u_channels, args.out)

if __name__ == "__main__":
    main()
