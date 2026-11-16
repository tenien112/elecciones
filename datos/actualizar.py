#!/usr/bin/env python3
"""RADAR ELECCIONES-LORENZITO: actualiza encuestas (Wikipedia) y apuestas (Polymarket).

Lo lanza el botón ACTUALIZAR de la app (GitHub Actions, workflow elecciones.yml)
y también se ejecuta solo cada pocas horas. Solo toca datos.json y apuestas.json.
"""
import json, re, sys, os, datetime as dt, urllib.request, urllib.parse
from zoneinfo import ZoneInfo

AQUI = os.path.dirname(os.path.abspath(__file__))
TZ = ZoneInfo("Europe/Madrid")
UA = {"User-Agent": "RadarElecciones/1.0 (app personal; github.com/tenien112/bolsa)"}
WIKI_PAG = "Opinion_polling_for_the_2026_Spanish_general_election"
WIKI_URL = "https://en.wikipedia.org/wiki/" + WIKI_PAG
MEDIOS = {"Prisa": "El País / Cadena SER", "Atresmedia": "La Sexta / Antena 3", "Vocento": "ABC"}
MESES = {m: i + 1 for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}


NAV = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
       "Accept": "application/json, text/html, */*"}


def get(url, nav=False):
    req = urllib.request.Request(url, headers=NAV if nav else UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8")


def ahora():
    return dt.datetime.now(TZ)


# ---------------------------------------------------------------- ENCUESTAS
def wikitext():
    q = urllib.parse.urlencode({"action": "parse", "page": WIKI_PAG, "prop": "wikitext",
                                "format": "json", "formatversion": "2", "redirects": "1"})
    return json.loads(get("https://en.wikipedia.org/w/api.php?" + q))["parse"]["wikitext"]


def primera_tabla(t):
    i = t.find("{|", t.find("====Voting intention estimates===="))
    return t[i:t.find("\n|}", i)]


def columnas(tabla):
    """Nombres de los partidos de la cabecera, en orden."""
    cab = tabla.split("\n|-", 2)[1]
    nombres = []
    for l in cab.split("\n"):
        if not l.startswith("!"):
            continue
        m = re.search(r"link=[^|\]]*\|([^\]]+)\]\]", l) or re.search(r"\[\[[^|\]]*\|([^\]]+)\]\]", l)
        txt = m.group(1) if m else re.sub(r".*\|", "", l).strip()
        nombres.append(txt.strip())
    return nombres  # incluye Polling firm, Fieldwork, Sample, Turnout, partidos..., Lead


def celdas(fila):
    out = []
    for l in fila.split("\n"):
        if not l.startswith("|") or l.startswith("|-") or l.startswith("|}"):
            if out and l and not l.startswith("|"):
                out[-1] += "\n" + l
            continue
        out.append(l[1:])
    res = []
    for c in out:
        span = 1
        m = re.match(r'\s*colspan="?(\d+)"?\s*\|(.*)', c, re.S)
        if m:
            span, c = int(m.group(1)), m.group(2)
        else:  # estilos tipo {{Party shading/PP}}| o style="..."|
            m2 = re.match(r'\s*(\{\{Party shading[^}]*\}\}|style="[^"]*")\s*\|(.*)', c, re.S)
            if m2:
                c = m2.group(2)
        res.extend([c] * span)
    return res


def valor(c):
    c = re.sub(r"<!--.*?-->", "", c, flags=re.S)
    pct = None
    m = re.match(r"\s*'*\s*([\d.]+)", c)
    if m:
        try:
            pct = float(m.group(1))
        except ValueError:
            pct = None
    esc = "s/d"
    m = re.search(r"text=([\d/–-]+)\}\}", c)
    if m:
        esc = m.group(1).replace("/", "-").replace("–", "-")
    return pct, esc


def fecha_pub(celda0, campo):
    m = re.search(r"\|\s*date=(\d{1,2}) (\w{3})\w* (\d{4})", celda0)
    if m and m.group(2) in MESES:
        return dt.date(int(m.group(3)), MESES[m.group(2)], int(m.group(1))).isoformat()
    m = re.search(r"(\d{1,2})\s*(\w{3})?\s*$", campo.strip())  # fin del trabajo de campo
    hoy = ahora().date()
    if m:
        mes = MESES.get((m.group(2) or "")[:3], hoy.month)
        return dt.date(hoy.year, mes, int(m.group(1))).isoformat()
    return hoy.isoformat()


def suma_esc(a, b):
    def rango(e):
        n = [int(x) for x in re.findall(r"\d+", e or "")]
        return (n[0], n[-1]) if n else None
    ra, rb = rango(a), rango(b)
    if not ra or not rb:
        return "s/d"
    lo, hi = ra[0] + rb[0], ra[1] + rb[1]
    return str(lo) if lo == hi else f"{lo}-{hi}"


def encuestas():
    tabla = primera_tabla(wikitext())
    cols = columnas(tabla)
    idx = {k: cols.index(n) for k, n in
           [("pp", "PP"), ("psoe", "PSOE"), ("vox", "Vox"), ("fa", "FA"), ("podemos", "Podemos")]}
    filas = tabla.split("\n|-")[3:]
    vistos, lista = set(), []
    for f in filas:
        c = celdas(f)
        if len(c) < max(idx.values()) + 1:
            continue
        nombre = re.split(r"<ref|\{\{", c[0])[0].strip()
        if "election" in nombre.lower() or "/" not in nombre:
            continue
        nombre = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", nombre)
        inst, medio = [x.strip() for x in nombre.split("/", 1)]
        medio = MEDIOS.get(medio, medio)
        if inst.lower() in vistos:
            continue
        datos = {k: valor(c[i]) for k, i in idx.items()}
        if datos["pp"][0] is None or datos["psoe"][0] is None:
            continue
        url = re.search(r"\|\s*url=(\S+)", c[0])
        e = {"instituto": inst, "medio": medio, "fecha": fecha_pub(c[0], c[1])}
        for k, (p, s) in datos.items():
            e[k] = {"pct": p, "esc": s}
        e["ppvox"] = suma_esc(datos["pp"][1], datos["vox"][1])
        e["url"] = url.group(1).strip() if url else WIKI_URL
        lista.append(e)
        vistos.add(inst.lower())
        if len(lista) == 4:
            break
    if len(lista) < 4:
        raise RuntimeError(f"Solo {len(lista)} encuestas leídas de Wikipedia")
    return lista


def media(lista, k, fn):
    v = [fn(x, k) for x in lista]
    v = [x for x in v if isinstance(x, (int, float))]
    return round(sum(v) / len(v), 1) if v else None


def historial(h, entrada):
    h = [x for x in h if x.get("fecha") != entrada["fecha"]]
    h.append(entrada)
    return h


# ---------------------------------------------------------------- POLITICO Poll of Polls
POL_P = {"PP": "pp", "PSOE": "psoe", "VOX": "vox", "FA": "fa", "Podemos": "podemos"}


def politico():
    """Media de TODAS las encuestas (POLITICO Poll of Polls) y las encuestas de los últimos 10 días."""
    d = json.loads(get("https://www.politico.eu/wp-json/politico/v1/poll-of-polls/ES-parliament", True))
    t = d["trends"]["kalman"][-1]
    media = {v: round(t["parties"][k], 1) for k, v in POL_P.items() if k in t["parties"]}
    lim = (dt.date.fromisoformat(t["date"]) - dt.timedelta(days=10)).isoformat()
    lista = []
    for x in reversed(d["polls"]):
        if x.get("date", "") < lim:
            break
        lista.append({"firma": x.get("firm"), "fecha": x.get("date"), "muestra": x.get("sample_size"),
                      **{v: x["parties"].get(k) for k, v in POL_P.items()}})
    return {"fecha": t["date"], "media": media, "encuestas": lista,
            "url": "https://www.politico.eu/europe-poll-of-polls/national-parliament-voting-intention/spain/"}


# ---------------------------------------------------------------- APUESTAS
def polymarket(slug_ini, buscar):
    ev = None
    for q in (buscar, "spain general election", "spain"):
        try:
            res = json.loads(get("https://gamma-api.polymarket.com/public-search?q=" + urllib.parse.quote(q), True)).get("events", [])
        except Exception as e:
            print("Polymarket búsqueda", q, ":", e)
            continue
        ev = next((e for e in res if e.get("slug", "").startswith(slug_ini) and not e.get("closed")), None)
        if ev:
            break
    if not ev:
        raise RuntimeError("No encuentro el mercado " + slug_ini)
    precios = {}
    for m in ev.get("markets", []):
        if m.get("closed") or not m.get("active"):
            continue
        try:
            si = float(json.loads(m["outcomePrices"])[0])
        except Exception:
            continue
        precios[m.get("groupItemTitle", "")] = round(si * 100, 1)
    return precios, "https://polymarket.com/event/" + ev["slug"]


# ---------------------------------------------------------------- MANIFOLD (dinero ficticio)
MANIFOLD = {"gobierno": ("t2hIcyupSt", "Próximo presidente del Gobierno"),
            "ganar": ("dssO0cOpPU", "Partido ganador")}
MF_NOMBRES = {"pp": ("feij", "pp"), "psoe": ("s\u00e1nchez", "sanchez", "psoe"), "vox": ("abascal", "vox")}


def manifold(clave, hoy):
    mid, mercado = MANIFOLD[clave]
    m = json.loads(get("https://api.manifold.markets/v0/market/" + mid, True))
    ent = {"casa": "Manifold (dinero ficticio)", "mercado": mercado, "fecha": hoy, "tipo": "prob",
           "pp": None, "psoe": None, "vox": None, "url": m.get("url") or "https://manifold.markets"}
    for a in m.get("answers", []):
        t = a.get("text", "").lower()
        for k, cl in MF_NOMBRES.items():
            if ent[k] is None and any(re.search(r"\b" + re.escape(c), t) for c in cl):
                ent[k] = round(a.get("probability", 0) * 100, 1)
    return ent


def apuestas(d, hoy):
    hechos = []
    try:
        p, url = polymarket("next-prime-minister-of-spain", "next prime minister of spain")
        ent = {"casa": "Polymarket", "mercado": "Próximo presidente del Gobierno", "fecha": hoy, "tipo": "prob",
               "pp": p.get("Alberto Núñez Feijóo"), "psoe": p.get("Pedro Sánchez"),
               "vox": p.get("Santiago Abascal"), "url": url}
        d["gobierno"] = [ent] + [x for x in d.get("gobierno", []) if x.get("casa") != "Polymarket"]
        hechos.append("gobierno")
    except Exception as e:
        print("Polymarket gobierno:", e)
    try:
        p, url = polymarket("spain-general-election-winner", "spain general election winner")
        ent = {"casa": "Polymarket", "mercado": "Partido con más escaños", "fecha": hoy, "tipo": "prob",
               "pp": p.get("PP"), "psoe": p.get("PSOE"), "vox": p.get("Vox"), "url": url}
        d["ganar"] = [ent] + [x for x in d.get("ganar", []) if x.get("casa") != "Polymarket"]
        hechos.append("ganar")
    except Exception as e:
        print("Polymarket ganar:", e)
    for clave in ("gobierno", "ganar"):
        try:
            ent = manifold(clave, hoy)
            d[clave] = [x for x in d.get(clave, []) if x.get("casa") != ent["casa"]] + [ent]
            hechos.append("manifold-" + clave)
        except Exception as e:
            print("Manifold", clave, ":", e)
    # Fuera las cuotas de casas que llevan más de 7 días sin renovarse
    lim = (dt.date.fromisoformat(hoy) - dt.timedelta(days=7)).isoformat()
    for clave in ("gobierno", "ganar"):
        d[clave] = [x for x in d.get(clave, []) if x.get("fecha", "") >= lim]
        d[clave] = [x for x in d[clave] if x.get("casa") != "Smarkets"]
    return hechos


def prob(x, k):
    v = x.get(k)
    if not isinstance(v, (int, float)):
        return None
    return v if x.get("tipo") == "prob" else 100 / v


# ---------------------------------------------------------------- MAIN
def guardar(nombre, d):
    with open(os.path.join(AQUI, nombre), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
        f.write("\n")


def registrar(sello, d, a):
    """Registro de cada actualización (historial completo hasta el 29N).
    Si la lanza Lorenzo con el botón ACTUALIZAR se guarda siempre;
    si es la automática, solo cuando algo ha cambiado."""
    ruta = os.path.join(AQUI, "registro.json")
    try:
        with open(ruta, encoding="utf-8") as f:
            r = json.load(f)
    except Exception:
        r = {"registro": []}
    lista = d.get("encuestas", [])
    f2 = lambda x, k: (x.get(k) or {}).get("pct")
    ent = {
        "enc": {k: media(lista, k, f2) for k in ("pp", "psoe", "vox", "fa", "podemos")},
        "fuentes": [f"{x.get('instituto')} {x.get('fecha')}" for x in lista],
        "todas": (d.get("politico") or {}).get("media"),
        "gob": {k: media(a.get("gobierno", []), k, prob) for k in ("pp", "psoe", "vox")},
        "gan": {k: media(a.get("ganar", []), k, prob) for k in ("pp", "psoe", "vox")},
    }
    boton = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    ult = r["registro"][-1] if r["registro"] else None
    cambia = not ult or any(ult.get(k) != ent[k] for k in ent)
    if boton or cambia:
        r["registro"].append({"t": sello, "o": "tu" if boton else "auto", **ent})
        guardar("registro.json", r)
        print("Registro:", len(r["registro"]), "entradas")


def main():
    t = ahora()
    sello = t.replace(microsecond=0).isoformat()
    hoy = t.date().isoformat()
    fallos = []

    # Encuestas
    with open(os.path.join(AQUI, "datos.json"), encoding="utf-8") as f:
        d = json.load(f)
    try:
        lista = encuestas()
        d["encuestas"] = lista
        f2 = lambda x, k: x[k]["pct"]
        d["historial"] = historial(d.get("historial", []), {"fecha": hoy, **{k: media(lista, k, f2) for k in ("pp", "psoe", "vox", "fa")}})
        if t.date() >= dt.date(2026, 11, 24) and t.date() < dt.date(2026, 11, 29):
            d["nota"] = "Veda de encuestas en España desde el 24/11: se muestran las últimas publicadas."
        else:
            d["nota"] = ""
        print("Encuestas:", ", ".join(f"{x['instituto']} {x['fecha']}" for x in lista))
    except Exception as e:
        fallos.append("encuestas")
        print("ERROR encuestas:", e)
    try:
        d["politico"] = politico()
        print("POLITICO:", d["politico"]["fecha"], d["politico"]["media"], len(d["politico"]["encuestas"]), "encuestas")
    except Exception as e:
        print("POLITICO:", e)
    d["actualizado"] = sello
    guardar("datos.json", d)

    # Apuestas
    with open(os.path.join(AQUI, "apuestas.json"), encoding="utf-8") as f:
        a = json.load(f)
    hechos = apuestas(a, hoy)
    if not any(h in hechos for h in ('gobierno', 'ganar')) and not hechos:
        fallos.append("apuestas")
    a["historial"] = historial(a.get("historial", []), {
        "fecha": hoy,
        "gan_pp": media(a.get("ganar", []), "pp", prob), "gan_psoe": media(a.get("ganar", []), "psoe", prob),
        "gob_pp": media(a.get("gobierno", []), "pp", prob), "gob_psoe": media(a.get("gobierno", []), "psoe", prob)})
    a["actualizado"] = sello
    guardar("apuestas.json", a)
    registrar(sello, d, a)
    print("Apuestas actualizadas:", hechos)
    if fallos:
        print("Falló:", fallos)
        sys.exit(1 if len(fallos) == 2 else 0)


if __name__ == "__main__":
    main()
