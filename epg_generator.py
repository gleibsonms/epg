#!/usr/bin/env python3
"""
epg_generator.py

Gera epg.xml (XMLTV) a partir de uma playlist M3U (local) e mescla com um EPG externo.
Inclui:
 - fallback se o EPG externo for inválido
 - mapeamento automatico (fuzzy match) entre canais da M3U e canais do EPG externo
 - pretty-print do XML de saida

Uso:
  python epg_generator.py lista.m3u --epg-source epg_remote.xml --out epg.xml
  python epg_generator.py lista.m3u --epg-source "https://epg.brtwo.fyi/epg.xml"

Opcoes:
  --hours N        : horas de placeholders ao gerar fallback (default 48)
  --min-ratio R    : ratio minimo (0..1) do fuzzy match para aceitar um match (default 0.6)
  --write-map FILE : opcional, grava CSV com mapeamento sugerido (tvg-id,matched_epg_id,score)
"""

import argparse
import datetime as dt
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET
import sys
import os
import re
from xml.dom import minidom
import difflib
import csv

try:
    import requests
except ImportError:
    requests = None

TZ = ZoneInfo("America/Recife")


# ---------------- utilities ----------------

def now_tz():
    return dt.datetime.now(TZ)


def pretty_xml_bytes(elem):
    rough = ET.tostring(elem, encoding="utf-8")
    reparsed = minidom.parseString(rough)
    return reparsed.toprettyxml(indent="  ", encoding="utf-8")


def format_xmltv_datetime(dtobj):
    return dtobj.strftime("%Y%m%d%H%M%S %z")


def safe_read_text(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def load_m3u(path_or_url):
    """Carrega playlist M3U (arquivo local ou URL)."""
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        if not requests:
            print("Erro: requests necessário para baixar M3U. Instale: pip install requests")
            sys.exit(2)
        try:
            r = requests.get(path_or_url, timeout=30)
            r.raise_for_status()
            return r.text
        except requests.exceptions.RequestException as e:
            print(f"Erro ao baixar M3U: {e}")
            sys.exit(2)
    else:
        if not os.path.exists(path_or_url):
            print(f"Arquivo M3U nao encontrado: {path_or_url}")
            sys.exit(2)
        return safe_read_text(path_or_url)


def parse_m3u_text(text):
    """Retorna lista de canais {tvg_id, name, url}."""
    lines = [l.rstrip("\n\r") for l in text.splitlines() if l.strip() != ""]
    channels = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#EXTINF"):
            # tenta tvg-id e nome
            m_id = re.search(r'tvg-id="([^"]+)"', line)
            tvg_id = m_id.group(1).strip() if m_id else None
            name = line.split(",", 1)[1].strip() if "," in line else (tvg_id or f"chan{i}")
            url = lines[i+1] if i+1 < len(lines) and not lines[i+1].startswith("#") else ""
            channels.append({"tvg_id": tvg_id or name, "name": name, "url": url})
            i += 2
        else:
            i += 1
    return channels


# ------------- load external EPG --------------

def load_external_raw(epg_source):
    """Retorna string do EPG remoto/local ou None em caso de erro."""
    is_url = epg_source.startswith("http://") or epg_source.startswith("https://")
    if is_url:
        if not requests:
            print("Aviso: requests nao instalado; nao e possivel baixar EPG remoto.")
            return None
        try:
            r = requests.get(epg_source, timeout=60)
            r.raise_for_status()
            # gravar copia local para debug (opcional)
            try:
                with open("epg_remote.xml", "wb") as f:
                    f.write(r.content)
            except Exception:
                pass
            return r.content.decode("utf-8", errors="replace")
        except requests.exceptions.RequestException as e:
            print(f"Erro ao baixar EPG remoto: {e}")
            return None
    else:
        if not os.path.exists(epg_source):
            print(f"Arquivo EPG nao encontrado: {epg_source}")
            return None
        return safe_read_text(epg_source)


def parse_external_epg_raw(text):
    """
    Parseia texto XML do EPG externo e retorna:
      - epg_channels: list of dicts {id, display}
      - epg_events: dict epg_id -> list of events {start_dt,stop_dt,title,desc}
    Retorna (None, None) em caso de parse falho.
    """
    if not text or "<tv" not in text:
        print("Conteudo do EPG parece invalido (nao contem <tv>)")
        try:
            print("Snippet (primeiras 1000 chars):")
            print((text or "")[:1000])
        except Exception:
            pass
        return None, None

    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError as e:
        print(f"Erro ao parsear EPG externo: {e}")
        # salvar snippet para debug
        try:
            with open("epg_remote_debug_snippet.txt", "w", encoding="utf-8", errors="replace") as f:
                f.write((text or "")[:5000])
            print("Gravado epg_remote_debug_snippet.txt")
        except Exception:
            pass
        return None, None

    # coletar canais (id + display-name)
    epg_channels = []
    for ch in root.findall("channel"):
        cid = ch.get("id")
        display = ch.findtext("display-name") or ""
        epg_channels.append({"id": cid, "display": display.strip()})

    # coletar events por channel id
    events = {}
    for prog in root.findall("programme"):
        ch = prog.get("channel")
        if not ch:
            continue
        start_raw = prog.get("start") or ""
        stop_raw = prog.get("stop") or ""
        title = (prog.findtext("title") or "").strip()
        desc = (prog.findtext("desc") or "").strip()
        # parse datas no formato XMLTV (YYYYMMDDHHMMSS±HHMM ou sem offset)
        try:
            start_dt = parse_xmltv_datetime(start_raw)
            stop_dt = parse_xmltv_datetime(stop_raw)
        except Exception:
            # pular blocos com datas invalidas
            continue
        events.setdefault(ch, []).append({
            "start": start_dt,
            "stop": stop_dt,
            "title": title,
            "desc": desc
        })

    # ordenar eventos por inicio
    for k in events:
        events[k].sort(key=lambda e: e["start"])
    return epg_channels, events


def parse_xmltv_datetime(s):
    """Parse simplificado de XMLTV datetime YYYYMMDDHHMMSS±HHMM."""
    s = (s or "").strip()
    if len(s) < 14:
        raise ValueError("datetime invalido")
    dt_part = s[:14]
    year = int(dt_part[0:4]); month = int(dt_part[4:6]); day = int(dt_part[6:8])
    hour = int(dt_part[8:10]); minute = int(dt_part[10:12]); second = int(dt_part[12:14])
    rest = s[14:].strip()
    if rest == "":
        return dt.datetime(year, month, day, hour, minute, second, tzinfo=TZ)
    # rest like +HHMM or -HHMM or +HH:MM
    r = rest.replace(":", "")
    sign = r[0]
    hh = int(r[1:3]) if len(r) >= 3 else 0
    mm = int(r[3:5]) if len(r) >= 5 else 0
    offset_minutes = hh * 60 + mm
    if sign == "-":
        offset_minutes = -offset_minutes
    tz = dt.timezone(dt.timedelta(minutes=offset_minutes))
    return dt.datetime(year, month, day, hour, minute, second, tzinfo=tz)


# ---------- fuzzy matching logic ----------

def normalize_name(s):
    """Normaliza nome para comparacao: minusculas, remove nao alnum."""
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^a-z0-9 ]", "", s)
    s = s.strip()
    return s


def build_mapping(m3u_channels, epg_channels, min_ratio=0.6):
    """
    Faz fuzzy match entre canais da M3U e canais do EPG externo.
    Retorna:
      mapping: dict m3u_tvg_id -> (matched_epg_id or None, score)
      unmatched lists printed to log
    """
    # construir lista de candidates: use both epg id and display name
    candidates = []
    for ec in epg_channels:
        # candidate string: prefer display name, fallback to id
        cand_name = ec["display"] or ec["id"] or ""
        candidates.append((ec["id"], cand_name, normalize_name(cand_name)))

    mapping = {}
    epg_norm_map = {ec_id: norm for (ec_id, _, norm) in candidates}

    # for fast matching use list of normalized strings
    candidate_norms = [norm for (_, _, norm) in candidates]

    # also build mapping index -> epg_id
    idx_to_epg = [ec_id for (ec_id, _, _) in candidates]

    for ch in m3u_channels:
        mname = ch.get("name") or ch.get("tvg_id")
        tvg = ch["tvg_id"]
        norm = normalize_name(mname)
        best_score = 0.0
        best_epg_id = None

        # try exact id match first
        for ec in epg_channels:
            if ec["id"] and ec["id"].lower() == tvg.lower():
                best_epg_id = ec["id"]
                best_score = 1.0
                break

        if best_score < 1.0:
            # compare with display names using SequenceMatcher ratio
            for i, cand_norm in enumerate(candidate_norms):
                if not cand_norm:
                    continue
                score = difflib.SequenceMatcher(None, norm, cand_norm).ratio()
                if score > best_score:
                    best_score = score
                    best_epg_id = idx_to_epg[i]

        if best_score >= min_ratio:
            mapping[tvg] = (best_epg_id, best_score)
        else:
            mapping[tvg] = (None, best_score)

    # print summary
    matched = [(tvg, m[0], m[1]) for tvg, m in mapping.items() if m[0]]
    unmatched = [(tvg, m[1]) for tvg, m in mapping.items() if not m[0]]
    print(f"Mapping summary: {len(matched)} matched, {len(unmatched)} unmatched (min_ratio={min_ratio})")
    # optional small sample prints
    if matched:
        print("Exemplo matches (tvg_id -> epg_id : score):")
        for t, e, s in matched[:12]:
            print(f"  {t} -> {e} : {s:.2f}")
    if unmatched:
        print("Exemplo unmatched (tvg_id : best_score):")
        for t, s in unmatched[:12]:
            print(f"  {t} : {s:.2f}")

    return mapping


# ---------- build final epg ----------

def build_final_epg(m3u_channels, epg_events, mapping, hours=48, out_path="epg.xml"):
    """
    Para cada canal da M3U:
      - se mapping[tvg] aponta para um epg_id com eventos, usa esses eventos (mas escreve channel attr = tvg)
      - senao gera placeholders
    """
    tv = ET.Element("tv", {"source-info-name": "epg-generator", "generator-info-name": "epg_generator.py"})
    start_base = now_tz().replace(minute=0, second=0, microsecond=0)

    for ch in m3u_channels:
        tvg = ch["tvg_id"]
        name = ch["name"]
        ch_el = ET.SubElement(tv, "channel", {"id": tvg})
        ET.SubElement(ch_el, "display-name").text = name

        mapped = mapping.get(tvg, (None, 0.0))[0]
        if mapped and epg_events and mapped in epg_events:
            events = epg_events[mapped]
            for ev in events:
                prog = ET.SubElement(tv, "programme", {
                    "start": format_xmltv_datetime(ev["start"]),
                    "stop": format_xmltv_datetime(ev["stop"]),
                    "channel": tvg
                })
                ET.SubElement(prog, "title").text = ev["title"]
                ET.SubElement(prog, "desc").text = ev["desc"]
        else:
            # fallback placeholders
            for i in range(hours):
                s = start_base + dt.timedelta(hours=i)
                e = s + dt.timedelta(hours=1)
                prog = ET.SubElement(tv, "programme", {
                    "start": format_xmltv_datetime(s),
                    "stop": format_xmltv_datetime(e),
                    "channel": tvg
                })
                ET.SubElement(prog, "title").text = f"Program {i+1} - {name}"
                ET.SubElement(prog, "desc").text = f"Programa gerado automaticamente - {name} - Bloco {i+1}"

    xml_bytes = pretty_xml_bytes(tv)
    with open(out_path, "wb") as f:
        f.write(xml_bytes)
    print(f"✅ EPG final gravado: {out_path} (canais: {len(m3u_channels)})")


# -------------- main ----------------

def main():
    p = argparse.ArgumentParser()
    p.add_argument("m3u", help="Caminho ou URL da playlist .m3u (preferencial local)")
    p.add_argument("--epg-source", help="URL ou arquivo local com EPG XML externo (opcional)", default=None)
    p.add_argument("--hours", type=int, default=48, help="Horas para placeholders (padrao 48)")
    p.add_argument("--min-ratio", type=float, default=0.6, help="Ratio minimo para aceitar fuzzy match (0..1)")
    p.add_argument("--out", default="epg.xml", help="Arquivo de saida")
    p.add_argument("--write-map", help="Opcional: grava CSV sugerido com mapeamento (tvg-id,epg-id,score)")
    args = p.parse_args()

    print("Carregando M3U...")
    m3u_text = load_m3u(args.m3u)
    m3u_channels = parse_m3u_text(m3u_text)
    if not m3u_channels:
        print("Nenhum canal detectado na M3U.")
        sys.exit(2)
    print(f"Canais detectados na M3U: {len(m3u_channels)}")

    epg_channels = []
    epg_events = None
    if args.epg_source:
        print(f"Carregando EPG externo de: {args.epg_source}")
        raw = load_external_raw(args.epg_source)
        if raw is None:
            print("Nao foi possivel obter EPG externo; sera gerado EPG com placeholders.")
        else:
            epg_channels, epg_events = parse_external_epg_raw(raw)
            if epg_channels is None:
                print("Falha ao parsear EPG externo; sera gerado EPG com placeholders.")
                epg_channels = []
                epg_events = None
            else:
                print(f"Canais no EPG externo: {len(epg_channels)}; eventos: {sum(len(v) for v in (epg_events or {}).values())}")
    else:
        print("Nenhum EPG externo informado; gerando placeholders unicamente.")

    # build mapping between m3u tvg_id and epg id
    mapping = {}
    if epg_channels:
        mapping = build_mapping(m3u_channels, epg_channels, min_ratio=args.min_ratio)
    else:
        # tudo None
        mapping = {ch["tvg_id"]: (None, 0.0) for ch in m3u_channels}

    # opcional: gravar CSV com mapping sugerido
    if args.write_map:
        try:
            with open(args.write_map, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["tvg-id", "matched-epg-id", "score"])
                for tvg, (mid, score) in mapping.items():
                    writer.writerow([tvg, mid or "", f"{score:.3f}"])
            print(f"Map CSV gravado em: {args.write_map}")
        except Exception as e:
            print(f"Falha ao gravar map CSV: {e}")

    # finalmente, montar epg final
    build_final_epg(m3u_channels, epg_events, mapping, hours=args.hours, out_path=args.out)


if __name__ == "__main__":
    main()
