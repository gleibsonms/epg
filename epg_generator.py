#!/usr/bin/env python3
"""
epg_generator.py

Gera epg.xml (XMLTV) a partir de uma playlist M3U (local).
Opcionalmente mescla programação a partir de um EPG externo (--epg-source),
que pode ser uma URL ou um arquivo local (ex: epg_remote.xml baixado pelo workflow).

Este script é tolerante a EPG externo inválido:
- tenta parsear o XML,
- se falhar, registra as primeiras linhas do arquivo e faz fallback para placeholders,
  em vez de abortar com erro de parse.
"""

import argparse
import datetime as dt
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET
import sys
import os
from xml.dom import minidom
import re

try:
    import requests
except ImportError:
    requests = None

TZ = ZoneInfo("America/Recife")


def now_tz():
    return dt.datetime.now(TZ)


def load_m3u(path_or_url):
    """Carrega playlist M3U (arquivo local ou URL)."""
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        if not requests:
            print("Erro: módulo 'requests' não disponível (necessário para URLs).")
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
    lines = [l.rstrip("\n\r") for l in text.splitlines() if l.strip() != ""]
    channels = []
    i = 0
    import unicodedata
    while i < len(lines):
        line = lines[i]
        if line.startswith("#EXTINF"):
            # captura tvg-id="..." e o nome após a virgula
            m_id = re.search(r'tvg-id="([^"]+)"', line)
            tvg_id = m_id.group(1).strip() if m_id else None
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
    """Retorna bytes do XML pretty-printed (UTF-8)."""
    rough = ET.tostring(elem, encoding="utf-8")
    reparsed = minidom.parseString(rough)
    return reparsed.toprettyxml(indent="  ", encoding="utf-8")


def detect_html_or_error_file(path):
    """Checa rapidamente se o arquivo parece HTML ou contém tags <html> ou DOCTYPE."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            head = f.read(1024).lower()
            if "<html" in head or "<!doctype html" in head or "access denied" in head or "forbidden" in head:
                return True
    except Exception:
        pass
    return False


def load_external_epg(epg_source):
    """
    Tenta carregar EPG externo (arquivo local ou URL).
    Retorna lista de eventos (cada evento: dict with channel,start,stop,title,desc).
    Em caso de falha de parse, retorna None e registra debug info (arquivo parcial).
    """
    text = None
    is_local = not (epg_source.startswith("http://") or epg_source.startswith("https://"))
    if not is_local:
        if not requests:
            print("Aviso: requests não disponível; não foi possível baixar EPG remoto.")
            return None
        try:
            r = requests.get(epg_source, timeout=60)
            r.raise_for_status()
            # salvar cópia local para debug (opcional)
            try:
                with open("epg_remote.xml", "wb") as f:
                    f.write(r.content)
            except Exception:
                pass
            text = r.content.decode("utf-8", errors="replace")
        except requests.exceptions.RequestException as e:
            print(f"Erro ao baixar EPG remoto: {e}")
            return None
    else:
        if not os.path.exists(epg_source):
            print(f"Arquivo EPG externo não encontrado: {epg_source}")
            return None
        with open(epg_source, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()

    # se o conteúdo parecer HTML (erro), aborta parse e retorna None (para fallback)
    # (o workflow já salva epg_remote.xml; aqui verificamos também)
    if not text or "<tv" not in text:
        # possível HTML ou conteúdo inválido
        print("Conteúdo do EPG externo parece inválido ou não contém tag <tv>. Vai usar fallback.")
        # registrar primeiras linhas para debug
        try:
            snippet = text[:2000] if text else ""
            print("----- início do EPG remoto (snippet) -----")
            print(snippet)
            print("----- fim do snippet -----")
        except Exception:
            pass
        return None

    # Tentar parse com ElementTree; em caso de erro, retornar None (fallback)
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError as e:
        print(f"Erro ao parsear EPG externo: {e}")
        # gravar snippet para debug
        try:
            with open("epg_remote_debug_snippet.txt", "w", encoding="utf-8", errors="replace") as f:
                f.write(text[:4000])
            print("Gravado epg_remote_debug_snippet.txt (primeiras 4000 chars)")
        except Exception:
            pass
        # imprimir primeiras linhas no log (útil no Actions)
        try:
            print("----- início do EPG remoto (primeiras linhas para debug) -----")
            for nl in text.splitlines()[:40]:
                print(nl)
            print("----- fim do snippet -----")
        except Exception:
            pass
        return None

    # Se chegou aqui, parse ok; extrair eventos
    events = []
    for prog in root.findall("programme"):
        ch = prog.get("channel")
        if not ch:
            continue
        start_raw = prog.get("start")
        stop_raw = prog.get("stop")
        title = (prog.findtext("title") or "").strip()
        desc = (prog.findtext("desc") or "").strip()

        # tenta parse simples do start/stop no estilo XMLTV YYYYMMDDHHMMSS±HHMM
        try:
            def parse_xmltv_datetime(s):
                s = s.strip()
                if len(s) < 14:
                    raise ValueError("datetime curto")
                dt_part = s[:14]
                year = int(dt_part[0:4]); month = int(dt_part[4:6]); day = int(dt_part[6:8])
                hour = int(dt_part[8:10]); minute = int(dt_part[10:12]); second = int(dt_part[12:14])
                rest = s[14:].strip()
                if rest == "":
                    return dt.datetime(year, month, day, hour, minute, second, tzinfo=TZ)
                # normalizar offset tipo +HHMM ou -HHMM (sem :)
                sign = rest[0]
                r = rest[1:].replace(":", "")
                hh = int(r[0:2]) if len(r) >= 2 else 0
                mm = int(r[2:4]) if len(r) >= 4 else 0
                offset_minutes = hh * 60 + mm
                if sign == "-":
                    offset_minutes = -offset_minutes
                tz = dt.timezone(dt.timedelta(minutes=offset_minutes))
                return dt.datetime(year, month, day, hour, minute, second, tzinfo=tz)

            start_dt = parse_xmltv_datetime(start_raw)
            stop_dt = parse_xmltv_datetime(stop_raw)
        except Exception:
            # se falhar, não quebra; guarda start_raw/stop_raw como None (vai ignorar esse bloco)
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
    Monta o XMLTV final:
    - adiciona <channel> para cada canal da M3U
    - se external_events possuir eventos para o tvg-id, usa eles
    - caso contrário, gera placeholders hora-a-hora (hours)
    """
    tv = ET.Element("tv", {"source-info-name": "epg-generator", "generator-info-name": "epg_generator.py"})

    # indexar external_events por channel id (string)
    events_by_channel = {}
    if external_events:
        for ev in external_events:
            events_by_channel.setdefault(ev["channel"], []).append(ev)
        for evs in events_by_channel.values():
            evs.sort(key=lambda x: x["start"])

    start_base = now_tz().replace(minute=0, second=0, microsecond=0)

    for ch in channels:
        ch_id = ch["tvg_id"]
        ch_el = ET.SubElement(tv, "channel", {"id": ch_id})
        display = ET.SubElement(ch_el, "display-name")
        display.text = ch["name"]

        evs = events_by_channel.get(ch_id)
        if evs:
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
            # fallback placeholders
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

    # pretty print e gravar
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
    parser.add_argument("--hours", type=int, default=48, help="Horas para gerar placeholders (padrao 48)")
    parser.add_argument("--out", default="epg.xml", help="Arquivo de saida (padrao epg.xml)")
    args = parser.parse_args()

    print("Carregando M3U...")
    text = load_m3u(args.m3u)
    channels = parse_m3u_text(text)
    if not channels:
        print("Nenhum canal detectado na playlist M3U.")
        sys.exit(2)
    print(f"Canais detectados: {len(channels)}")

    external_events = None
    if args.epg_source:
        print(f"Carregando EPG externo de: {args.epg_source}")
        external_events = load_external_epg(args.epg_source)
        if external_events is None:
            print("Falha ao carregar/parsear EPG externo. Usando placeholders para todos os canais.")
        else:
            print(f"Eventos externos lidos: {len(external_events)}")

    build_xmltv(channels, external_events, hours=args.hours, out_path=args.out)


if __name__ == "__main__":
    main()
