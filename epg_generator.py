import re
import xml.etree.ElementTree as ET
import argparse
import os
import sys
from datetime import datetime, timedelta

def normalize_channel_id(name: str) -> str:
    """Normaliza o ID de canal para comparação entre M3U e EPG."""
    if not name:
        return ""
    name = name.lower()
    name = re.sub(r"[\s\.\-\_]+", "", name)  # remove espaços, pontos e traços
    name = name.replace("hd", "")  # opcional: remove 'hd' para ampliar compatibilidade
    return name.strip()

def parse_m3u(file_path):
    """Lê e processa o arquivo M3U."""
    channels = []
    current = {}
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if line.startswith("#EXTINF"):
                match = re.search(r'tvg-id="([^"]*)".*?,(.*)$', line)
                if match:
                    tvg_id, name = match.groups()
                    current = {
                        "id": tvg_id.strip(),
                        "name": name.strip(),
                        "normalized_id": normalize_channel_id(tvg_id or name)
                    }
            elif line and current:
                current["url"] = line
                channels.append(current)
                current = {}
    return channels

def generate_epg(channels, out_file="epg.xml", tz_offset=-3):
    """Gera um EPG básico para canais encontrados."""
    root = ET.Element("tv", attrib={"generator-info-name": "epg-generator-v2"})

    now = datetime.utcnow() + timedelta(hours=tz_offset)
    for ch in channels:
        channel = ET.SubElement(root, "channel", id=ch["id"] or ch["name"])
        ET.SubElement(channel, "display-name").text = ch["name"]
        ET.SubElement(channel, "icon", src="https://static.imgb.in/logos/{}".format(ch["normalized_id"] + ".png"))

        # Adiciona uma programação genérica (exemplo)
        for i in range(6):
            start = (now + timedelta(hours=i)).strftime("%Y%m%d%H%M%S +0000")
            stop = (now + timedelta(hours=i + 1)).strftime("%Y%m%d%H%M%S +0000")
            prog = ET.SubElement(root, "programme", start=start, stop=stop, channel=ch["id"] or ch["name"])
            ET.SubElement(prog, "title", lang="pt").text = f"Programa Exemplo {i+1}"
            ET.SubElement(prog, "desc", lang="pt").text = f"Programação fictícia para o canal {ch['name']}."

    ET.indent(root)
    tree = ET.ElementTree(root)
    tree.write(out_file, encoding="utf-8", xml_declaration=True)
    print(f"✅ EPG gerado com sucesso ({len(channels)} canais) → {out_file}")

def main():
    parser = argparse.ArgumentParser(description="Gerador de EPG baseado em lista M3U local")
    parser.add_argument("--m3u", required=True, help="Caminho do arquivo M3U")
    parser.add_argument("--out", default="epg.xml", help="Arquivo de saída (XML)")
    parser.add_argument("--tz-offset", type=int, default=-3, help="Offset de fuso horário (ex: -3)")
    args = parser.parse_args()

    if not os.path.exists(args.m3u):
        print(f"❌ Arquivo M3U não encontrado: {args.m3u}")
        sys.exit(1)

    channels = parse_m3u(args.m3u)
    if not channels:
        print("⚠️ Nenhum canal encontrado na lista M3U.")
        sys.exit(1)

    generate_epg(channels, args.out, args.tz_offset)

if __name__ == "__main__":
    main()
