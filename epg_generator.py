#!/usr/bin/env python3
"""
epg_generator.py

Gera epg.xml (XMLTV) a partir de uma playlist M3U (local) e, opcionalmente,
mescla programação real obtida de um XML EPG externo (local ou URL) passado em --epg-source.

Comportamento:
- Lê lista.m3u e cria <channel> para cada canal (usa tvg-id quando disponível).
- Se --epg-source for fornecido (URL ou arquivo local), tenta baixar/ler o XML e
  importar os blocos <programme> dele para os canais que existam na M3U.
- Se um canal da M3U não tiver blocos no EPG externo, gera placeholders por horas (default 48h).
- Sempre escreve XML "pretty printed".
"""

import argparse
import datetime as dt
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET
import sys
import os
from xml.dom import minidom

try:
    import requests
except ImportError:
    requests = None

TZ = ZoneInfo("America/Recife")


def now_tz():
    return dt.datetime.now(TZ)


def load_m3u(path_or_url):
    """Carrega playlist M3U (local apenas recomendado). Suporta URL também."""
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        if not requests:
            print("Erro: módulo 'requests' não disponível. Instale: pip install requests")
            sys.exit(2)
        try:
            r = requests.get(path_or_url, timeout=20)
            r.raise_for_status()
            return r.text
        except requests.exceptions.RequestException as e:
            print(f"Erro ao baixar M3U: {e}")
            sys.exit(2)
    else:
        if not os.path.exists(path_or_url):
            print(f"Arquivo M3U não encontrado: {path_or_url}")
            sys.exit(2)
        with open(path_or_url, "r", encoding="utf-8", errors="replace") as f:
            return f.read()


def parse_m3u_text(text):
    """Extrai canais da M3U: retorna lista de dicts {tvg_id, name, url}."""
    lines = [l.strip() for l in text.splitlines() if l.strip() != ""]
    channels = []
    i = 0
    import re
    while i < len(lines):
        line = lines[i]
        if line.startswith("#EXTINF"):
            # captura tvg-id="..." e o nome após a virgula
            m_id = re.search(r'tvg-id="([^"]+)"', line)
            tvg_id = m_id.group(1).strip() if m_id else None
            # pegar o nome depois da primeira virgula
            name = line.split(",", 1)[1].strip() if "," in line else (tvg_id or f"chan{i}")
            url = lines[i + 1] if i + 1 < len(lines) and not lines[i + 1].startswith("#") else ""
            channels.append({"tvg_id": tvg_id or name, "name": name, "url": url})
            i += 2
        else:
            i += 1
    return channels


def format_xmltv_datetime(dtobj):
    """Formata datetime para XMLTV: YYYYMMDDHHMMSS ±HHMM"""
    return dtobj.strftime("%Y%m%d%H%M%S %z")


def pretty_xml_bytes(elem):
    rough = ET.tostring(elem, encoding="utf-8")
    reparsed = minidom.parseString(rough)
    return reparsed.toprettyxml(indent="  ", encoding="utf-8")


def load_external_epg(epg_source):
    """
    Carrega EPG externo (arquivo local ou URL) e retorna lista de eventos:
    cada evento é dict {channel, start (datetime tz-aware), stop (datetime tz-aware), title, desc}
    """
    if epg_source.startswith("http://") or epg_source.startswith("https://"):
        if not requests:
            print("Erro: módulo 'requests' não disponível para baixar EPG. Instale: pip install requests")
            sys.exit(2)
        try:
            r = requests.get(epg_source, timeout=30)
            r.raise_for_status()
            xml_bytes = r.content
            root = ET.fromstring(xml_bytes)
        except requests.exceptions.RequestException as e:
            print(f"Erro ao baixar EPG externo: {e}")
            return []
        except ET.ParseError as e:
            print(f"Erro ao parsear EPG remoto: {e}")
            return []
    else:
        if not os.path.exists(epg_source):
            print(f"Arquivo EPG não encontrado: {epg_source}")
            return []
        try:
            tree = ET.parse(epg_source)
            root = tree.getroot()
        except Exception as e:
            print(f"Erro ao ler/parsear EPG local: {e}")
            return []

    events = []
    # procurar por elementos <programme>
    for prog in root.findall("programme"):
        ch = prog.get("channel")
        start_raw = prog.get("start")
        stop_raw = prog.get("stop")
        # extrair <title> e <desc>
        title_el = prog.find("title")
        desc_el = prog.find("desc")
        title = title_el.text.strip() if title_el is not None and title_el.text else ""
        desc = desc_el.text.strip() if desc_el is not None and desc_el.text else ""

        # tentar parse de start/stop no formato XMLTV: YYYYMMDDHHMMSS ±HHMM
        # cuidando de formatos sem espaço antes do offset ou sem offset
        try:
            # normaliza: se houver espaço antes do offset -> fromisoformat won't parse directly,
            # então vamos construir manualmente
            # ex: "20251109110000 -0300" ou "20251109110000-0300"
            if start_raw is None or stop_raw is None:
                continue
            # separar datetime e offset
            def parse_xmltv_datetime(s):
                s = s.strip()
                # possíveis formatos:
                # YYYYMMDDHHMMSS ±HHMM  (tem espaço)
                # YYYYMMDDHHMMSS±HHMM   (sem espaço)
                # YYYYMMDDHHMMSS        (sem offset)
                # converter para ISO-like: YYYY-MM-DDTHH:MM:SS+HH:MM
                if len(s) >= 14:
                    dt_part = s[:14]
                    rest = s[14:].strip()
                    year = int(dt_part[0:4]); month = int(dt_part[4:6]); day = int(dt_part[6:8])
                    hour = int(dt_part[8:10]); minute = int(dt_part[10:12]); second = int(dt_part[12:14])
                    if rest == "":
                        # naive -> attach default TZ
                        return dt.datetime(year, month, day, hour, minute, second, tzinfo=TZ)
                    else:
                        # rest like +0200 or -0300 or +02:00
                        # normalize +HHMM to +HH:MM
                        r = rest.replace(":", "")
                        sign = r[0]
                        hh = int(r[1:3])
                        mm = int(r[3:5]) if len(r) >= 5 else 0
                        offset_minutes = hh * 60 + mm
                        if sign == "-":
                            offset_minutes = -offset_minutes
                        tz = dt.timezone(dt.timedelta(minutes=offset_minutes))
                        return dt.datetime(year, month, day, hour, minute, second, tzinfo=tz)
                raise ValueError("Formato de data invalido")
            start_dt = parse_xmltv_datetime(start_raw)
            stop_dt = parse_xmltv_datetime(stop_raw)
        except Exception:
            # se falhar no parse, pula este bloco
            continue

        events.append({
            "channel": ch,
            "start": start_dt,
            "stop": stop_dt,
            "title": title,
            "desc": desc
        })
    return events


def build_xmltv(channels, external_events, hours=48, out_path="epg.xml"):
    """
    Monta o XMLTV:
    - adiciona <channel> para cada canal da M3U
    - se external_events contiver programas para o tvg-id do canal, adiciona esses programas
    - se não houver eventos para o canal, gera placeholders hora-a-hora (hours)
    """
    tv = ET.Element("tv", {"source-info-name": "epg-generator", "generator-info-name": "epg_generator.py"})

    # mapa de canal -> lista de eventos
    events_by_channel = {}
    for ev in external_events:
        events_by_channel.setdefault(ev["channel"], []).append(ev)

    # opcional: ordenar eventos por start
    for ch_id, evs in events_by_channel.items():
        evs.sort(key=lambda x: x["start"])

    start_base = now_tz().replace(minute=0, second=0, microsecond=0)

    for ch in channels:
        ch_id = ch["tvg_id"]
        ch_el = ET.SubElement(tv, "channel", {"id": ch_id})
        display = ET.SubElement(ch_el, "display-name")
        display.text = ch["name"]

        evs = events_by_channel.get(ch_id)
        if evs:
            # usar eventos do EPG externo para este canal
            for ev in evs:
                prog = ET.SubElement(tv, "programme", {
                    "start": format_xmltv_datetime(ev["start"]),
                    "stop": format_xmltv_datetime(ev["stop"]),
                    "channel": ch_id
                })
                title = ET.SubElement(prog, "title")
                title.text = ev["title"]
                desc = ET.SubElement(prog, "desc")
                desc.text = ev["desc"]
        else:
            # fallback: gerar placeholders hora-a-hora
            for i in range(hours):
                s = start_base + dt.timedelta(hours=i)
                e = s + dt.timedelta(hours=1)
                prog = ET.SubElement(tv, "programme", {
                    "start": format_xmltv_datetime(s),
                    "stop": format_xmltv_datetime(e),
                    "channel": ch_id
                })
                title = ET.SubElement(prog, "title")
                title.text = f"Program {i+1} - {ch['name']}"
                desc = ET.SubElement(prog, "desc")
                desc.text = f"Programa gerado automaticamente - {ch['name']} - Bloco {i+1}"

    # pretty print e salvar
    xml_bytes = pretty_xml_bytes(tv)
    try:
        with open(out_path, "wb") as f:
            f.write(xml_bytes)
        print(f"✅ EPG gerado: {out_path} ({len(channels)} canais).")
    except Exception as e:
        print(f"Erro ao escrever {out_path}: {e}")
        sys.exit(2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("m3u", help="Caminho para playlist .m3u (local preferencial)")
    parser.add_argument("--epg-source", help="URL ou arquivo local com EPG XML externo (opcional)", default=None)
    parser.add_argument("--hours", type=int, default=48, help="Horas para gerar placeholders (padrão 48)")
    parser.add_argument("--out", default="epg.xml", help="Arquivo de saída (padrão epg.xml)")
    args = parser.parse_args()

    # ler M3U
    text = load_m3u(args.m3u)
    channels = parse_m3u_text(text)
    if not channels:
        print("Nenhum canal detectado na playlist M3U.")
        sys.exit(2)
    print(f"Canais detectados: {len(channels)}")

    # carregar EPG externo (se fornecido)
    external_events = []
    if args.epg_source:
        print(f"Carregando EPG externo de: {args.epg_source}")
        external_events = load_external_epg(args.epg_source)
        print(f"Eventos externos lidos: {len(external_events)}")

    build_xmltv(channels, external_events, hours=args.hours, out_path=args.out)


if __name__ == "__main__":
    main()
