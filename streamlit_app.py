"""Asistente universitario: organizador de tareas con calendario (.ics), generador de bibliografía APA 7
y formateador de documentos Word al formato APA 7.

- Tus datos viven solo en tu sesión del navegador: cada visitante ve únicamente lo suyo.
- Para conservarlos entre visitas, descarga la copia de seguridad (.json) y vuélvela a cargar.
"""
import io
import json
import re
import unicodedata
import uuid
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

import streamlit as st

TIPOS = ["Tarea", "Trabajo", "Examen", "Exposición", "Práctica", "Otro"]
ESTADOS = ["Pendiente", "En curso", "Entregado"]
RECORDATORIOS = {"1 hora antes": "-PT1H", "1 día antes": "-P1D", "2 días antes": "-P2D", "1 semana antes": "-P7D"}
ZONAS = ["America/Lima", "America/Bogota", "America/Mexico_City", "America/Santiago",
         "America/Argentina/Buenos_Aires", "America/La_Paz", "Europe/Madrid", "UTC"]


# =============================================================================== calendario (.ics)
def _escapar(t):
    return t.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")


def _plegar(linea):
    """RFC 5545: líneas de máximo 75 octetos; las siguientes empiezan con un espacio."""
    datos, salida, actual, largo = linea, [], "", 0
    for ch in datos:
        b = len(ch.encode("utf-8"))
        if largo + b > (75 if not salida else 74):
            salida.append(actual)
            actual, largo = "", 0
        actual += ch
        largo += b
    salida.append(actual)
    return "\r\n ".join(salida)


def _inicio(t):
    return datetime.combine(date.fromisoformat(t["fecha"]), time.fromisoformat(t["hora"]))


def crear_ics(tareas):
    ahora = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    L = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Asistente universitario//ES", "CALSCALE:GREGORIAN",
         "X-WR-CALNAME:Mis tareas"]
    for t in tareas:
        ini = _inicio(t)
        fin = ini + timedelta(minutes=30)
        desc = f"Curso: {t['curso']}\nTipo: {t['tipo']}\nEstado: {t['estado']}" + (f"\n{t['notas']}" if t["notas"] else "")
        L += ["BEGIN:VEVENT", f"UID:{t['id']}@asistente-universitario", f"DTSTAMP:{ahora}",
              f"DTSTART:{ini:%Y%m%dT%H%M%S}", f"DTEND:{fin:%Y%m%dT%H%M%S}",
              f"SUMMARY:{_escapar(('[' + t['curso'] + '] ' if t['curso'] else '') + t['titulo'])}",
              f"DESCRIPTION:{_escapar(desc)}"]
        for r in t["recordatorios"]:
            L += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_escapar(t['titulo'])}",
                  f"TRIGGER:{RECORDATORIOS[r]}", "END:VALARM"]
        L.append("END:VEVENT")
    L.append("END:VCALENDAR")
    return ("\r\n".join(_plegar(x) for x in L) + "\r\n").encode("utf-8")


def enlace_google(t):
    ini = _inicio(t)
    fin = ini + timedelta(minutes=30)
    texto = ("[" + t["curso"] + "] " if t["curso"] else "") + t["titulo"]
    return ("https://calendar.google.com/calendar/render?action=TEMPLATE"
            f"&text={quote(texto)}&dates={ini:%Y%m%dT%H%M%S}/{fin:%Y%m%dT%H%M%S}"
            f"&details={quote(t['notas'] or t['tipo'])}")


# =============================================================================== bibliografía APA 7
def _sin_acentos(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _iniciales(nombres):
    partes = []
    for tok in nombres.split():
        sub = [p[0].upper() + "." for p in tok.split("-") if p]
        partes.append("-".join(sub))
    return " ".join(partes)


def _formatear_autor(linea):
    linea = linea.strip()
    if "," in linea:
        ap, nom = linea.split(",", 1)
        return f"{ap.strip()}, {_iniciales(nom)}".strip().rstrip(",")
    return linea  # autor institucional (p. ej. Ministerio del Ambiente)


def _lista_autores(texto, conector):
    a = [_formatear_autor(x) for x in texto.splitlines() if x.strip()]
    if not a:
        return ""
    if len(a) == 1:
        return a[0]
    if len(a) == 2:
        return f"{a[0]} {conector} {a[1]}"
    if len(a) <= 20:
        coma = "," if conector == "&" else ""
        return ", ".join(a[:-1]) + f"{coma} {conector} {a[-1]}"
    return ", ".join(a[:19]) + ", . . . " + a[-1]


def _punto(t):
    t = t.strip()
    return t if t.endswith((".", "?", "!")) else t + "."


def _url(u):
    u = u.strip()
    if re.match(r"^10\.\d{4,9}/\S+$", u):
        return "https://doi.org/" + u
    return u


def _fin(t):
    """Punto final si el texto no termina ya en . ? !"""
    return "" if t.rstrip().endswith((".", "?", "!")) else "."


def construir_referencia(tipo, d, conector):
    """Devuelve una lista de segmentos (texto, cursiva)."""
    autores = _lista_autores(d.get("autores", ""), conector)
    anio = d.get("anio", "").strip() or "s. f."
    titulo = d.get("titulo", "").strip()
    seg = []
    if autores:
        seg.append((_punto(autores) + f" ({anio}). ", False))

    def item(texto, cursiva=False):
        if texto:
            seg.append((texto, cursiva))

    def titulo_cursiva(extra=""):
        """Título en cursiva; si no hay autor, el año va justo después (APA 7)."""
        item(titulo, True)
        item(extra + _fin(titulo + extra) + " ")
        if not autores:
            item(f"({anio}). ")

    if tipo == "Libro":
        ed = d.get("edicion", "").strip()
        titulo_cursiva(f" ({ed}.ª ed.)" if ed.isdigit() else (f" ({ed} ed.)" if ed else ""))
        if d.get("editorial", "").strip():
            item(_punto(d["editorial"]))
        if d.get("url", "").strip():
            item(" " + _url(d["url"]))

    elif tipo == "Artículo de revista":
        if not autores:
            item(titulo + _fin(titulo) + f" ({anio}). ")
        else:
            item(titulo + _fin(titulo) + " ")
        item(d.get("revista", "").strip(), True)
        if d.get("volumen", "").strip():
            item(", ")
            item(d["volumen"].strip(), True)
            if d.get("numero", "").strip():
                item(f"({d['numero'].strip()})")
        if d.get("paginas", "").strip():
            item(f", {d['paginas'].strip()}")
        item(".")
        if d.get("url", "").strip():
            item(" " + _url(d["url"]))

    elif tipo == "Página web":
        titulo_cursiva()
        if d.get("sitio", "").strip():
            item(_punto(d["sitio"]) + " ")
        item(_url(d.get("url", "")))

    elif tipo == "Tesis":
        item(titulo, True)
        inst = d.get("institucion", "").strip()
        item(f" [{d.get('grado', '')}{', ' + inst if inst else ''}]. ")
        if not autores:
            item(f"({anio}). ")
        if d.get("repositorio", "").strip():
            item(_punto(d["repositorio"]) + " ")
        item(_url(d.get("url", "")))

    if seg:
        t, c = seg[-1]
        seg[-1] = (t.rstrip(), c)
    return [x for x in seg if x[0]]


def a_texto(segs):
    return "".join(t for t, _ in segs)


def a_markdown(segs):
    def esc(t):
        for ch in "*_`":
            t = t.replace(ch, "\\" + ch)
        return t
    return "".join(f"*{esc(t)}*" if c and t.strip() else esc(t) for t, c in segs)


def crear_docx(referencias):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    doc = Document()
    estilo = doc.styles["Normal"]
    estilo.font.name = "Times New Roman"
    estilo.font.size = Pt(12)
    h = doc.add_paragraph()
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    h.add_run("Referencias").bold = True
    for segs in sorted(referencias, key=lambda s: _sin_acentos(a_texto(s))):
        p = doc.add_paragraph()
        pf = p.paragraph_format
        pf.left_indent, pf.first_line_indent, pf.line_spacing = Cm(1.27), Cm(-1.27), 2
        for t, c in segs:
            r = p.add_run(t)
            r.italic = c
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()



# =============================================================================== formateador APA de documentos Word
FUENTES_APA = {"Times New Roman 12": ("Times New Roman", 12), "Calibri 11": ("Calibri", 11),
               "Arial 11": ("Arial", 11), "Georgia 11": ("Georgia", 11), "Lucida Sans Unicode 10": ("Lucida Sans Unicode", 10)}
TITULOS_REFERENCIAS = {"referencias", "referencias bibliográficas", "referencias bibliograficas", "bibliografía",
                       "bibliografia", "lista de referencias", "references", "bibliography"}


def _quitar_tema_fuente(elemento_rpr, nombre):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn as _qn
    rf = elemento_rpr.find(_qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        elemento_rpr.insert(0, rf)
    for a in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        rf.attrib.pop(_qn(a), None)
    for a in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rf.set(_qn(a), nombre)


def _estilo_apa(estilo, fuente, tam, negrita=None, cursiva=None, alineacion=None, sangria=None):
    from docx.shared import Cm, Pt, RGBColor
    f = estilo.font
    f.name, f.size = fuente, Pt(tam)
    f.color.rgb = RGBColor(0, 0, 0)
    if negrita is not None:
        f.bold = negrita
    if cursiva is not None:
        f.italic = cursiva
    _quitar_tema_fuente(estilo.element.get_or_add_rPr(), fuente)
    pf = estilo.paragraph_format
    pf.space_before = pf.space_after = Pt(0)
    pf.line_spacing = 2
    if alineacion is not None:
        pf.alignment = alineacion
    if sangria is not None:
        pf.left_indent = Cm(sangria)
        pf.first_line_indent = Cm(0)


def _limpiar_runs(p_xml, quitar_color=False):
    from docx.oxml.ns import qn as _qn
    for r in p_xml.iter(_qn("w:r")):
        rpr = r.find(_qn("w:rPr"))
        if rpr is None:
            continue
        tags = ["w:rFonts", "w:sz", "w:szCs"] + (["w:color", "w:highlight"] if quitar_color else [])
        for t in tags:
            for el in rpr.findall(_qn(t)):
                rpr.remove(el)


def _es_vacio(p):
    from docx.oxml.ns import qn as _qn
    if p.text.strip():
        return False
    x = p._p
    if x.find(".//" + _qn("w:drawing")) is not None or x.find(".//" + _qn("w:pict")) is not None:
        return False
    if x.find(".//" + _qn("w:br")) is not None or x.find(".//" + _qn("w:object")) is not None:
        return False
    if x.find(".//" + _qn("w:fldChar")) is not None or x.find(".//" + _qn("w:sectPr")) is not None:
        return False
    return True


def _numero_de_pagina(seccion, fuente, tam):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn as _qn
    from docx.shared import Pt
    enc = seccion.header
    enc.is_linked_to_previous = False
    for p in list(enc.paragraphs)[1:]:
        p._p.getparent().remove(p._p)
    p = enc.paragraphs[0]
    for r in list(p._p):
        if r.tag != _qn("w:pPr"):
            p._p.remove(r)
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = p.add_run()
    run.font.name, run.font.size = fuente, Pt(tam)
    for tipo, texto in (("begin", None), (None, " PAGE "), ("separate", None), (None, "1"), ("end", None)):
        if tipo:
            el = OxmlElement("w:fldChar")
            el.set(_qn("w:fldCharType"), tipo)
        elif texto.strip() == "PAGE":
            el = OxmlElement("w:instrText")
            el.set(_qn("xml:space"), "preserve")
            el.text = texto
        else:
            el = OxmlElement("w:t")
            el.text = texto
        run._r.append(el)


def formatear_apa(datos, fuente_nombre, tam, papel, portada, quitar_vacios, titulos_visuales):
    """Aplica estructura APA 7 a un .docx. No cambia el texto. Devuelve (bytes, informe)."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    doc = Document(io.BytesIO(datos))
    inf = {"niveles": {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}, "cuerpo": 0, "listas": 0, "vacios": 0,
           "referencias": False, "tablas": len(doc.tables), "imagenes": len(doc.inline_shapes), "avisos": []}
    C, L = WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.LEFT

    # --- estilos (se conservan los estilos de título de Word: sigue funcionando el panel de navegación y el índice)
    _estilo_apa(doc.styles["Normal"], fuente_nombre, tam)
    doc.styles["Normal"].paragraph_format.line_spacing = None  # tablas y encabezados no se tocan
    doc.styles["Normal"].paragraph_format.space_after = None
    doc.styles["Normal"].paragraph_format.space_before = None
    for nombre, kw in {"Heading 1": dict(negrita=True, cursiva=False, alineacion=C),
                       "Heading 2": dict(negrita=True, cursiva=False, alineacion=L),
                       "Heading 3": dict(negrita=True, cursiva=True, alineacion=L),
                       "Heading 4": dict(negrita=True, cursiva=False, alineacion=L, sangria=1.27),
                       "Heading 5": dict(negrita=True, cursiva=True, alineacion=L, sangria=1.27),
                       "Title": dict(negrita=True, cursiva=False, alineacion=C)}.items():
        try:
            _estilo_apa(doc.styles[nombre], fuente_nombre, tam, **kw)
        except KeyError:
            pass

    # --- página: márgenes, tamaño y número de página
    ancho, alto = (21.59, 27.94) if papel == "Carta" else (21.0, 29.7)
    for sec in doc.sections:
        sec.page_width, sec.page_height = Cm(ancho), Cm(alto)
        sec.left_margin = sec.right_margin = sec.top_margin = sec.bottom_margin = Cm(2.54)
    _numero_de_pagina(doc.sections[0], fuente_nombre, tam)

    # --- párrafos
    en_referencias = False
    parrafos = list(doc.paragraphs)
    for p in parrafos:
        nombre = (p.style.name if p.style is not None else "") or ""
        pf = p.paragraph_format
        if quitar_vacios and _es_vacio(p):
            p._p.getparent().remove(p._p)
            inf["vacios"] += 1
            continue
        if nombre.startswith(("TOC", "Table of", "Índice", "Contents")):
            continue
        es_titulo = nombre == "Title" or re.fullmatch(r"Heading [1-9]", nombre) is not None
        nivel = 1 if nombre == "Title" else (min(int(nombre.split()[-1]), 5) if es_titulo else 0)
        texto = p.text.strip()
        if not es_titulo and titulos_visuales and texto and len(texto) <= 80 and not texto.endswith((".", ":", ";", ",")):
            runs_txt = [r for r in p.runs if r.text.strip()]
            if runs_txt and all(r.bold for r in runs_txt) and "List" not in nombre \
                    and (p._p.pPr is None or p._p.pPr.numPr is None):
                es_titulo, nivel = True, 1
                p.alignment = C
                for r in runs_txt:
                    r.bold = True

        if es_titulo:
            inf["niveles"][nivel] += 1
            _limpiar_runs(p._p, quitar_color=True)
            pf.space_before = pf.space_after = Pt(0)
            pf.line_spacing = 2
            pf.first_line_indent = Cm(0)
            if nivel <= 3:
                pf.left_indent = Cm(0)
            en_referencias = texto.lower().strip(" :.") in TITULOS_REFERENCIAS
            if en_referencias:
                inf["referencias"] = True
                pf.page_break_before = True
                p.alignment = C
            continue

        _limpiar_runs(p._p)
        es_lista = (p._p.pPr is not None and p._p.pPr.numPr is not None) or nombre.startswith("List")
        pf.space_before = pf.space_after = Pt(0)
        pf.line_spacing = 2
        if es_lista:
            inf["listas"] += 1
            continue
        if "Caption" in nombre or nombre == "Leyenda":
            continue
        if p.alignment == C and len(texto) <= 100:
            pf.first_line_indent = Cm(0)
            continue
        inf["cuerpo"] += 1
        p.alignment = L
        if en_referencias:  # sangría francesa
            pf.left_indent, pf.first_line_indent = Cm(1.27), Cm(-1.27)
        elif pf.left_indent is not None and pf.left_indent > Cm(0.9):  # cita en bloque
            pf.first_line_indent = Cm(0)
        else:
            pf.left_indent, pf.first_line_indent = Cm(0), Cm(1.27)

    # tablas: solo se unifica la tipografía
    for t in doc.tables:
        for fila in t.rows:
            for celda in fila.cells:
                for p in celda.paragraphs:
                    _limpiar_runs(p._p)

    if sum(inf["niveles"].values()) == 0:
        inf["avisos"].append("No se encontraron títulos con los estilos de Word (Título 1, 2, 3). "
                             "Si tus títulos solo tienen negrita, activa «Detectar títulos en negrita».")
    if not inf["referencias"]:
        inf["avisos"].append("No se encontró una sección llamada «Referencias» (o «Bibliografía»): no se aplicó sangría francesa.")

    # --- portada (hoja de título de trabajo estudiantil)
    if portada:
        datos_portada = [(portada["titulo"], True), (portada["autor"], False), (portada["institucion"], False),
                         (portada["curso"], False), (portada["profesor"], False), (portada["fecha"], False)]
        primero = doc.element.body[0]
        creados = []
        for i, (txt, neg) in enumerate([d for d in datos_portada if d[0].strip()]):
            par = doc.add_paragraph()
            par.alignment = C
            par.paragraph_format.line_spacing = 2
            par.paragraph_format.space_before = Pt(72) if i == 0 else Pt(0)
            par.paragraph_format.space_after = Pt(0)
            par.paragraph_format.first_line_indent = Cm(0)
            r = par.add_run(txt.strip())
            r.bold = neg
            creados.append(par)
        for par in creados:
            primero.addprevious(par._p)
        resto = [p for p in doc.paragraphs if p not in creados]
        if resto and doc.element.body.index(resto[0]._p) == len(creados):
            resto[0].paragraph_format.page_break_before = True
        else:
            salto = doc.add_paragraph()
            salto.paragraph_format.page_break_before = True
            primero.addprevious(salto._p)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue(), inf


# =============================================================================== interfaz
def _estado():
    st.session_state.setdefault("tareas", [])
    st.session_state.setdefault("refs", [])
    st.session_state.setdefault("zona", "America/Lima")


def _hoy():
    return datetime.now(ZoneInfo(st.session_state["zona"])).date()


def _faltan(t):
    d = (date.fromisoformat(t["fecha"]) - _hoy()).days
    if t["estado"] == "Entregado":
        return "✔ Entregado"
    if d < 0:
        return f"⚠ Vencida hace {-d} d"
    return "Hoy" if d == 0 else ("Mañana" if d == 1 else f"En {d} días")


def pestana_tareas():
    st.caption("🔒 Tus tareas viven solo en tu sesión: nadie más las ve. Descarga la copia de seguridad para no perderlas.")
    with st.form("nueva", clear_on_submit=True):
        c1, c2 = st.columns([3, 2])
        titulo = c1.text_input("Qué hay que hacer", placeholder="Ej.: Informe de laboratorio 2")
        curso = c2.text_input("Curso", placeholder="Ej.: Estadística")
        c3, c4, c5 = st.columns(3)
        tipo = c3.selectbox("Tipo", TIPOS)
        fecha = c4.date_input("Fecha límite", value=_hoy() + timedelta(days=3))
        hora = c5.time_input("Hora límite", value=time(23, 59))
        recs = st.multiselect("Recordatorios", list(RECORDATORIOS), default=["1 día antes"])
        notas = st.text_input("Notas (opcional)")
        if st.form_submit_button("➕ Agregar", type="primary"):
            if not titulo.strip():
                st.error("Escribe qué hay que hacer.")
            else:
                st.session_state["tareas"].append(dict(
                    id=uuid.uuid4().hex, titulo=titulo.strip(), curso=curso.strip(), tipo=tipo,
                    fecha=fecha.isoformat(), hora=hora.strftime("%H:%M"), recordatorios=recs,
                    estado="Pendiente", notas=notas.strip()))

    tareas = sorted(st.session_state["tareas"], key=lambda t: (t["fecha"], t["hora"]))
    if not tareas:
        st.info("Aún no hay tareas. Agrega la primera arriba o carga una copia de seguridad.")
    else:
        pend = [t for t in tareas if t["estado"] != "Entregado"]
        prox = [t for t in pend if 0 <= (date.fromisoformat(t["fecha"]) - _hoy()).days <= 7]
        venc = [t for t in pend if date.fromisoformat(t["fecha"]) < _hoy()]
        m1, m2, m3 = st.columns(3)
        m1.metric("Pendientes", len(pend))
        m2.metric("Próximos 7 días", len(prox))
        m3.metric("Vencidas", len(venc))
        st.dataframe(
            [{"Fecha": f"{date.fromisoformat(t['fecha']):%d/%m/%Y} {t['hora']}", "Faltan": _faltan(t),
              "Tarea": t["titulo"], "Curso": t["curso"], "Tipo": t["tipo"], "Estado": t["estado"],
              "Recordatorios": ", ".join(t["recordatorios"]) or "—"} for t in tareas],
            use_container_width=True, hide_index=True)

        with st.expander("✏️ Cambiar estado, eliminar o agregar a Google Calendar"):
            idx = st.selectbox("Tarea", range(len(tareas)),
                               format_func=lambda i: f"{date.fromisoformat(tareas[i]['fecha']):%d/%m} · {tareas[i]['titulo']}")
            t = tareas[idx]
            c1, c2 = st.columns(2)
            nuevo = c1.selectbox("Estado", ESTADOS, index=ESTADOS.index(t["estado"]))
            if c1.button("Guardar estado"):
                t["estado"] = nuevo
                st.rerun()
            if c2.button("🗑 Eliminar tarea"):
                st.session_state["tareas"] = [x for x in st.session_state["tareas"] if x["id"] != t["id"]]
                st.rerun()
            st.link_button("📆 Agregar solo esta tarea a Google Calendar", enlace_google(t))

        a, b = st.columns(2)
        a.download_button("📥 Calendario (.ics)", crear_ics(pend), "mis_tareas.ics", "text/calendar",
                          disabled=not pend, help="Incluye las tareas no entregadas. Ábrelo en tu celular o impórtalo en Google Calendar / Outlook.")
        b.download_button("💾 Copia de seguridad (.json)", json.dumps(tareas, ensure_ascii=False, indent=1),
                          "copia_tareas.json", "application/json")

    with st.expander("📤 Cargar una copia de seguridad"):
        f = st.file_uploader("Archivo .json", type="json")
        if f is not None and st.button("Cargar y reemplazar mis tareas"):
            try:
                datos = json.loads(f.getvalue().decode("utf-8"))
                for t in datos:
                    date.fromisoformat(t["fecha"]); time.fromisoformat(t["hora"])
                    t.setdefault("id", uuid.uuid4().hex)
                    t.setdefault("curso", ""); t.setdefault("tipo", "Otro"); t.setdefault("notas", "")
                    t.setdefault("estado", "Pendiente"); t["recordatorios"] = [r for r in t.get("recordatorios", []) if r in RECORDATORIOS]
                st.session_state["tareas"] = datos
                st.rerun()
            except Exception:
                st.error("El archivo no tiene el formato esperado.")

    with st.expander("⚙️ Zona horaria"):
        st.selectbox("Para calcular «Faltan»", ZONAS, key="zona")
    st.caption("Las horas del calendario se guardan sin zona horaria, así que tu dispositivo las interpreta en tu hora local. "
               "Para recibir el aviso por correo, en Google Calendar cambia la notificación del calendario o del evento a «Correo».")


def pestana_apa():
    st.caption("Formato APA 7.ª edición. Escribe los títulos como van en la referencia (APA usa mayúscula solo al inicio y en nombres propios).")
    c1, c2 = st.columns([2, 1])
    tipo = c1.selectbox("Tipo de fuente", ["Libro", "Artículo de revista", "Página web", "Tesis"])
    conector = c2.selectbox("Conector de autores", ["y", "&"], help="«y» en español; «&» si tu universidad lo pide.")
    d = {}
    d["autores"] = st.text_area("Autores (uno por línea: Apellido, Nombre)", height=90,
                                placeholder="Gómez Pérez, Ana María\nMinisterio del Ambiente   (autor institucional: sin coma)")
    c1, c2 = st.columns([1, 3])
    d["anio"] = c1.text_input("Año", placeholder="2024 (vacío = s. f.)")
    d["titulo"] = c2.text_input("Título")
    if tipo == "Libro":
        c1, c2 = st.columns([1, 3])
        d["edicion"] = c1.text_input("Edición", placeholder="2")
        d["editorial"] = c2.text_input("Editorial")
        d["url"] = st.text_input("URL o DOI (opcional)")
    elif tipo == "Artículo de revista":
        d["revista"] = st.text_input("Nombre de la revista")
        c1, c2, c3 = st.columns(3)
        d["volumen"] = c1.text_input("Volumen")
        d["numero"] = c2.text_input("Número")
        d["paginas"] = c3.text_input("Páginas", placeholder="45-60")
        d["url"] = st.text_input("DOI o URL (opcional)", placeholder="10.1000/xyz123")
    elif tipo == "Página web":
        d["sitio"] = st.text_input("Nombre del sitio web", help="Déjalo vacío si es el mismo que el autor.")
        d["url"] = st.text_input("URL")
    else:
        c1, c2 = st.columns(2)
        d["grado"] = c1.selectbox("Tipo de trabajo", ["Tesis de licenciatura", "Tesis de maestría", "Tesis doctoral",
                                                      "Trabajo de suficiencia profesional"])
        d["institucion"] = c2.text_input("Institución")
        d["repositorio"] = st.text_input("Repositorio (opcional)", placeholder="Repositorio institucional")
        d["url"] = st.text_input("URL")

    if d["titulo"].strip():
        segs = construir_referencia(tipo, d, conector)
        st.markdown("**Vista previa**")
        st.markdown(a_markdown(segs))
        if st.button("➕ Agregar a mi lista", type="primary"):
            st.session_state["refs"].append(segs)
            st.toast("Referencia agregada")

    refs = sorted(st.session_state["refs"], key=lambda s: _sin_acentos(a_texto(s)))
    if refs:
        st.divider()
        st.subheader(f"Mi lista de referencias ({len(refs)})")
        for s in refs:
            st.markdown("- " + a_markdown(s))
        a, b, c = st.columns(3)
        a.download_button("📄 Descargar Word (.docx)", crear_docx(refs), "referencias.docx",
                          "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                          help="Con sangría francesa, interlineado doble y cursivas.")
        b.download_button("📝 Descargar texto (.txt)", "\n\n".join(a_texto(s) for s in refs), "referencias.txt")
        if c.button("Vaciar lista"):
            st.session_state["refs"] = []
            st.rerun()


def pestana_formato():
    st.caption("Sube tu informe en Word y la app le aplica la **estructura de formato APA 7**. No cambia tu texto, "
               "no revisa citas ni corrige referencias: solo el formato.")
    f = st.file_uploader("Documento Word (.docx)", type="docx", key="doc_apa")
    c1, c2 = st.columns(2)
    fuente = c1.selectbox("Fuente y tamaño", list(FUENTES_APA))
    papel = c2.selectbox("Tamaño de papel", ["A4", "Carta"], help="APA usa Carta; en Perú se suele usar A4.")
    c3, c4 = st.columns(2)
    quitar_vacios = c3.checkbox("Eliminar párrafos vacíos", value=True)
    titulos_visuales = c4.checkbox("Detectar títulos en negrita", value=False,
                                   help="Úsalo si tus títulos no tienen los estilos Título 1, 2, 3 de Word. Los trata como nivel 1.")
    con_portada = st.checkbox("Agregar portada (hoja de título)")
    portada = None
    if con_portada:
        portada = {}
        portada["titulo"] = st.text_input("Título del trabajo")
        a, b = st.columns(2)
        portada["autor"] = a.text_input("Autor(es)")
        portada["institucion"] = b.text_input("Institución / facultad")
        c, d, e = st.columns(3)
        portada["curso"] = c.text_input("Curso")
        portada["profesor"] = d.text_input("Docente")
        portada["fecha"] = e.text_input("Fecha de entrega", placeholder="20 de noviembre de 2026")

    if f is not None and st.button("Aplicar formato APA", type="primary"):
        try:
            nombre, tam = FUENTES_APA[fuente]
            datos, inf = formatear_apa(f.getvalue(), nombre, tam, papel, portada, quitar_vacios, titulos_visuales)
            st.session_state["apa_doc"] = (datos, inf, re.sub(r"\.docx$", "", f.name, flags=re.I) + "_APA.docx")
        except Exception as e:  # archivo dañado, protegido, etc.
            st.session_state.pop("apa_doc", None)
            st.error(f"No pude procesar el archivo ({type(e).__name__}). Prueba abrirlo y guardarlo de nuevo en Word.")

    if "apa_doc" in st.session_state:
        datos, inf, nombre = st.session_state["apa_doc"]
        st.success("Documento formateado.")
        st.download_button("⬇️ Descargar Word con formato APA", datos, nombre,
                           "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        niv = ", ".join(f"nivel {k}: {v}" for k, v in inf["niveles"].items() if v) or "ninguno"
        st.markdown(f"**Qué se aplicó:** márgenes de 2,54 cm, interlineado doble sin espacio entre párrafos, "
                    f"sangría de 1,27 cm en cada párrafo, texto alineado a la izquierda, número de página arriba a la derecha. \n"
                    f"**Títulos encontrados:** {niv}. **Párrafos de texto:** {inf['cuerpo']}. "
                    f"**Vacíos eliminados:** {inf['vacios']}. **Referencias con sangría francesa:** {'sí' if inf['referencias'] else 'no'}.")
        for a in inf["avisos"]:
            st.warning(a)
        st.info("Revisa a mano: las mayúsculas de los títulos, las citas dentro del texto, y las tablas y figuras "
                f"({inf['tablas']} tablas y {inf['imagenes']} imágenes se dejaron como estaban, solo con la misma tipografía). "
                "Los títulos de nivel 4 y 5 quedan en línea aparte, no en la misma línea del párrafo como pide APA.")


def main():
    st.set_page_config(page_title="Asistente universitario", page_icon="🎓", layout="centered")
    _estado()
    st.title("🎓 Asistente universitario")
    t1, t2, t3 = st.tabs(["📅 Tareas y recordatorios", "📚 Bibliografía APA", "📄 Formato APA de documento"])
    with t1:
        pestana_tareas()
    with t2:
        pestana_apa()
    with t3:
        pestana_formato()


if __name__ == "__main__":
    main()
