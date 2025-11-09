import argparse
import requests
import gzip
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from io import BytesIO

# Lista de canais brasileiros prioritários (nomes e aliases comuns)
BR_CHANNELS = {
    "globo": ["globo", "tv globo", "rede globo"],
    "record": ["record", "recordtv", "record tv"],
    "sbt": ["sbt", "sbt hd", "sbt sp", "sbt rio"],
    "band": ["band", "rede bandeirantes", "bandeirantes"],
    "cultura": ["cultura", "tv cultura"],
    "rede_tv": ["redetv", "rede tv", "rede tv!"],
    "cnn_brasil": ["cnn brasil", "cnn-brasil", "cnnbrasil"],
    "globonews": ["globonews", "globo news"],
    "sportv": ["sportv", "sportv1", "sportv2", "sportv3"],
    "premiere": ["premiere", "premiere clubes", "premiere hd"],
}

def download_file(url):
    print(f"🔽 Baixando: {url}")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return resp.content

def parse_m3u(m3u_text):
    channels = []
    current = {}
    for line in m3u_text.splitlines():
        line = line.strip()
        if line.startswith("#EXTINF"):
            info = line.split(",", 1)
            name = info[1].strip() if len(info) > 1 else "Sem nome"
            current = {"name": name}
        elif line.startswith("http"):
            current["url"] = line
            channels.append(current)
    return channels

def match_channel(name):
    name_lower = name.lower()
    for key, aliases in BR_CHANNELS.items():
        if any(alias in name_lower for alias in aliases):
            return key
    return None

def load_epg(epg_url):
    print(f"🧠 Carregando EPG de: {epg_url}")
    data = download_file(epg_url)
    if epg_url.endswith(".gz"):
        data = gzip.decompress(data)
    return ET.fromstring(data)

def build_epg(m3u_channels, source_epg, tz_offset=-3, hours=72):
    root = ET.Element("tv", attrib={"generator-info-name": "br-epg-generator"})

    now = datetime.utcnow() + timedelta(hours=tz_offset)
    end_time = now + timedelta(hours=hours)

    channel_ids = set()

    for ch in m3u_channels:
        matched = match_channel(ch["name"])
        ch_id = matched if matched else ch["name"].lower().replace(" ", "_")
        channel = ET.SubElement(root, "channel", id=ch_id)
        ET.SubElement(channel, "display-name").text = ch["name"]
        channel_ids.add(ch_id)

    # Copiar apenas os canais brasileiros da fonte
    for prog in source_epg.findall("programme"):
        ch_id = prog.attrib.get("channel", "").lower()
        if any(alias in ch_id for aliases in BR_CHANNELS.values() for alias in aliases):
            root.append(prog)

    # Se algum canal não tiver EPG real, criar placeholders básicos
    for ch in channel_ids:
        if not any(p.attrib.get("channel") == ch for p in root.findall("programme")):
            for i in range(6):
                start = now + timedelta(hours=i)
                stop = start + timedelta(hours=1)
                prog = ET.SubElement(
                    root,
                    "programme",
                    channel=ch,
                    start=start.strftime("%Y%m%d%H%M%S +0000"),
                    stop=stop.strftime("%Y%m%d%H%M%S +0000"),
                )
                ET.SubElement(prog, "title").text = f"Programa Exemplo {i+1}"
                ET.SubElement(prog, "desc").text = "Sem informações no momento."

    return ET.ElementTree(root)

def save_epg(tree, filename):
    tree.write(filename, encoding="utf-8", xml_declaration=True)
    print(f"💾 EPG salvo como {filename}")

def main():
    parser = argparse.ArgumentParser(description="Gerador de EPG prioritário para canais brasileiros.")
    parser.add_argument("--m3u", required=True, help="URL da lista M3U")
    parser.add_argument("--epg", required=False, help="URL do EPG real (XMLTV)")
    parser.add_argument("--out", default="epg.xml", help="Arquivo de saída")
    parser.add_argument("--hours", type=int, default=72, help="Número de horas de programação")
    parser.add_argument("--tz-offset", type=int, default=-3, help="Offset de fuso horário (padrão: -3)")
    args = parser.parse_args()

    m3u_text = download_file(args.m3u).decode("utf-8", errors="ignore")
    channels = parse_m3u(m3u_text)
    print(f"📺 {len(channels)} canais encontrados na M3U.")

    if args.epg:
        source_epg = load_epg(args.epg)
    else:
        print("⚠️ Nenhum EPG externo informado, gerando apenas placeholders.")
        source_epg = ET.Element("tv")

    tree = build_epg(channels, source_epg, tz_offset=args.tz_offset, hours=args.hours)
    save_epg(tree, args.out)

if __name__ == "__main__":
    main()
