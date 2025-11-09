#!/usr/bin/env python3
# epg_generator_auto.py
"""
Gerador de EPG com mapeamento automático entre epg.xml e lista.m3u.
- Gera channel_map_suggestions.json (com scores)
- Aplica mapeamentos com threshold configurável
- Sobrescreve epg_out (por padrão epg.xml)
"""

import re
import xml.etree.ElementTree as ET
import argparse
import os
import sys
import json
from datetime import datetime, timedelta
from difflib import SequenceMatcher

def normalize(s: str) -> str:
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r"[\s\-_\.]+", "", s)
    s = re.sub(r"[^a-z0-9áàâãéèêíïóôõöúçñ]+", "", s)
    return s.strip()

def parse_m3u(path):
    """
    Retorna lista de dicionários: {id, name, normalized}
    Extrai tvg-id="..." do #EXTINF, caso não exista tenta extrair do display name
    """
    items = []
    if not os.path.exists(path):
        print(f"Arquivo M3U não encontrado: {path}")
        return items

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        current = None
        for line in f:
            line = line.strip()
            if line.startswith("#EXTINF"):
                # captura tvg-id e nome após a vírgula
                m = re.search(r'tvg-id="([^"]*)"', line)
                name = None
                if "," in line:
                    name = line.split(",", 1)[1].strip()
                if m:
                    tvg = m.group(1).strip()
                else:
                    # tenta pegar tvg-name= ou use name
                    mt = re.search(r'tvg-name="([^"]*)"', line)
                    tvg = mt.group(1).strip() if mt else (name or "")
                current = {"id": tvg, "name": name or tvg}
            elif line and current:
                current["url"] = line
                current["normalized"] = normalize(current.get("id") or current.get("name"))
                items.append(current)
                current = None
    return items

def parse_epg(path):
    """Carrega epg.xml e retorna ElementTree root e lista de channel ids (originais)."""
    if not os.path.exists(path):
        print(f"Arquivo EPG não encontrado: {path}")
        return None, []
    tree = ET.parse(path)
    root = tree.getroot()
    channels = []
    for ch in root.findall("channel"):
        ch_id = ch.attrib.get("id", "")
        channels.append(ch_id)
    return tree, channels

def best_match(name, candidates):
    best = None
    best_score = 0.0
    for cand in candidates:
        score = SequenceMatcher(None, normalize(name), normalize(cand)).ratio()
        if score > best_score:
            best = cand
            best_score = score
    return best, best_score

def build_suggestions(epg_ids, m3u_ids):
    suggestions = {}
    m3u_candidates = [m for m in m3u_ids]
    for eid in epg_ids:
        cand, score = best_match(eid, m3u_candidates)
        suggestions[eid] = {"suggested": cand, "score": round(score, 4)}
    return suggestions

def apply_mapping_and_write(tree, suggestions, threshold, m3u_map, out_path):
    """
    Aplica mapeamento no tree: substitui channel id e programa@channel.
    m3u_map: map normalizado_m3u_id -> original_m3u_id (to ensure preserving exact tvg-id)
    """
    root = tree.getroot()
    # mapeia epg id -> tvg-id (original string from M3U) para aplicar
    epg_to_m3u = {}
    for epg_id, info in suggestions.items():
        if info["score"] >= threshold and info["suggested"]:
            # queremos usar o tvg-id original (não normalizado)
            suggested = info["suggested"]
            epg_to_m3u[epg_id] = suggested

    if not epg_to_m3u:
        print("Nenhum mapeamento automático com confiança suficiente.")
    else:
        # Trocar <channel id="..."> elements
        for ch in root.findall("channel"):
            old = ch.attrib.get("id", "")
            if old in epg_to_m3u:
                new = epg_to_m3u[old]
                # set attribute on element
                ch.set("id", new)
                # update display-name if exists
                dn = ch.find("display-name")
                if dn is not None and (not dn.text or dn.text.strip()=="" ):
                    dn.text = new

        # Trocar atributos channel em programme elements
        for prog in root.findall("programme"):
            old = prog.attrib.get("channel", "")
            if old in epg_to_m3u:
                prog.set("channel", epg_to_m3u[old])

    # escreve arquivo
    ET.indent(root)
    tree.write(out_path, encoding="utf-8", xml_declaration=True)
    return epg_to_m3u

def save_list_file(path, items):
    with open(path, "w", encoding="utf-8") as f:
        for it in items:
            f.write(f"{it}\n")

def main():
    parser = argparse.ArgumentParser(description="EPG generator with auto mapping")
    parser.add_argument("--m3u", required=True, help="arquivo M3U (local)")
    parser.add_argument("--epg", required=True, help="arquivo EPG fonte (local)")
    parser.add_argument("--out", default="epg.xml", help="arquivo EPG de saída")
    parser.add_argument("--threshold", type=float, default=0.72, help="score mínimo para aplicar mapa automaticamente (0-1)")
    parser.add_argument("--save-suggestions", default="channel_map_suggestions.json", help="arquivo com sugestões (json)")
    args = parser.parse_args()

    m3u_items = parse_m3u(args.m3u)
    if not m3u_items:
        print("Nenhum canal encontrado na M3U.")
        sys.exit(1)

    tree, epg_ids = parse_epg(args.epg)
    if tree is None:
        sys.exit(1)

    m3u_ids = [it["id"] for it in m3u_items if it.get("id")]
    # também mantenha normalizados -> original
    m3u_norm_map = { normalize(it["id"]): it["id"] for it in m3u_items }

    # salvar listas de debug
    save_list_file("m3u_ids.txt", m3u_ids)
    save_list_file("epg_ids.txt", epg_ids)

    suggestions = build_suggestions(epg_ids, m3u_ids)
    # salvar sugestões (com scores)
    with open(args.save_suggestions, "w", encoding="utf-8") as f:
        json.dump(suggestions, f, indent=2, ensure_ascii=False)

    # aplicar mapeamento automático (somente quando score >= threshold)
    epg_to_m3u = apply_mapping_and_write(tree, suggestions, args.threshold, m3u_norm_map, args.out)

    print("Sugestões salvas em:", args.save_suggestions)
    if epg_to_m3u:
        print("Mapeamentos aplicados (epg_id -> tvg-id):")
        for k,v in epg_to_m3u.items():
            print(f"  {k} -> {v}")
    else:
        print("Nenhum mapeamento aplicado automaticamente. Revise channel_map_suggestions.json e fixe manualmente se necessário.")

if __name__ == "__main__":
    main()
