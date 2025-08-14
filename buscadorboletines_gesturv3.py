import streamlit as st
from datetime import datetime, timedelta
import pytz, feedparser, requests, re, html as html_stdlib, os
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from concurrent.futures import ThreadPoolExecutor, as_completed

st.set_page_config(page_title="Buscador boletines oficiales [BOE/BOC]", page_icon="📰", layout="wide")

# --- Estilos ---
st.markdown("""
<style>
.stMarkdown { margin-bottom: .08rem !important; margin-top: .08rem !important; }
hr { margin-top: .10rem !important; margin-bottom: .10rem !important; }
.block-container { padding-top: .9rem !important; padding-bottom: .9rem !important; }
</style>
""", unsafe_allow_html=True)

# --- Zonas horarias ---
tz_madrid = pytz.timezone("Europe/Madrid")
tz_canarias = pytz.timezone("Atlantic/Canary")
hoy_madrid = datetime.now(tz_madrid).date()
hoy_canarias = datetime.now(tz_canarias).date()

# --- Gemini: obtener clave (IMPORTANTE: strip para eliminar \n/espacios) ---
GEMINI_API_KEY = (st.secrets.get("GEMINI_API_KEY") or "").strip()
if not GEMINI_API_KEY:
    st.error("Falta GEMINI_API_KEY en secrets.")

from google import genai
from google.genai import types

# Cliente oficial Gemini (sin ping de red aquí)
try:
    gclient = genai.Client(api_key=GEMINI_API_KEY)
except Exception as e:
    st.error(f"Error inicializando el cliente de Gemini: {e}")

# --- Funciones BOE ---
def obtener_boe_reciente():
    url_rss_boe = "https://www.boe.es/rss/boe.php"
    try:
        response = requests.get(url_rss_boe)
        soup = BeautifulSoup(response.content, "xml")
    except Exception as e:
        st.error(f"Error accediendo al BOE: {e}")
        return []

    for offset in [0, 1, 2, 3, -1, -2, -3]:
        fecha_objetivo = hoy_madrid + timedelta(days=offset)
        resultados = []
        for item in soup.find_all("item"):
            try:
                pub_date_raw = item.pubDate.get_text()
                fecha_pub = date_parser.parse(pub_date_raw).astimezone(tz_madrid).date()
                if fecha_pub == fecha_objetivo:
                    titulo_real = item.find("titulo").get_text(strip=True) if item.find("titulo") else item.title.get_text(strip=True)
                    resultados.append({
                        "boletin": "BOE",
                        "titulo": titulo_real,
                        "url": item.link.get_text(strip=True),
                        "fecha": fecha_pub.strftime('%Y-%m-%d'),
                        "contenido": titulo_real
                    })
            except Exception as e:
                continue
        if resultados:
            return resultados
    return []

# --- Feeds oficiales BOC ---
BOC_FEEDS = [
    "https://www.gobiernodecanarias.org/boc/feeds/capitulo/disposiciones_generales.rss",
    "https://www.gobiernodecanarias.org/boc/feeds/capitulo/autoridades_personal_nombramientos.rss",
    "https://www.gobiernodecanarias.org/boc/feeds/capitulo/autoridades_personal_oposiciones.rss",
    "https://www.gobiernodecanarias.org/boc/feeds/capitulo/otras_resoluciones.rss",
    "https://www.gobiernodecanarias.org/boc/feeds/capitulo/administracion_justicia.rss",
    "https://www.gobiernodecanarias.org/boc/feeds/capitulo/anuncios.rss",
    "https://www.gobiernodecanarias.org/boc/feeds/capitulo/otros_anuncios.rss",
    "https://www.gobiernodecanarias.org/boc/feeds/consejeria/presidencia_del_gobierno.rss",
    "https://www.gobiernodecanarias.org/boc/feeds/consejeria/presidencia_justicia_igualdad.rss",
    "https://www.gobiernodecanarias.org/boc/feeds/consejeria/agricultura.rss",
    "https://www.gobiernodecanarias.org/boc/feeds/consejeria/empleo.rss",
    "https://www.gobiernodecanarias.org/boc/feeds/consejeria/Industria.rss",
    "https://www.gobiernodecanarias.org/boc/feeds/consejeria/educacion.rss",
    "https://www.gobiernodecanarias.org/boc/feeds/consejeria/hacienda.rss",
    "https://www.gobiernodecanarias.org/boc/feeds/consejeria/obras_publicas.rss",
    "https://www.gobiernodecanarias.org/boc/feeds/consejeria/sanidad.rss",
    "https://www.gobiernodecanarias.org/boc/feeds/consejeria/Politica_territorial.rss",
    "https://www.gobiernodecanarias.org/boc/feeds/consejeria/deportes.rss",
    "https://www.gobiernodecanarias.org/boc/feeds/cabildo/fuerteventura.rss",
    "https://www.gobiernodecanarias.org/boc/feeds/cabildo/la_gomera.rss",
    "https://www.gobiernodecanarias.org/boc/feeds/cabildo/gran_canaria.rss",
    "https://www.gobiernodecanarias.org/boc/feeds/cabildo/el_hierro.rss",
    "https://www.gobiernodecanarias.org/boc/feeds/cabildo/lanzarote.rss",
    "https://www.gobiernodecanarias.org/boc/feeds/cabildo/la_palma.rss",
    "https://www.gobiernodecanarias.org/boc/feeds/cabildo/tenerife.rss",
    "https://www.gobiernodecanarias.org/boc/feeds/universidad/la_laguna.rss",
    "https://www.gobiernodecanarias.org/boc/feeds/universidad/las_palmas.rss"
]

def extraer_numero_anuncio(descripcion):
    descripcion_html = html_stdlib.unescape(descripcion)
    soup = BeautifulSoup(descripcion_html, "html.parser")
    h3 = soup.find("h3")
    if h3:
        b = h3.find("b")
        if b and b.text.strip().isdigit():
            return b.text.strip()
    return None

def parsear_feed_con_fecha(url, fecha_objetivo):
    resultados = []
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            if "published_parsed" in entry:
                fecha_pub = datetime(*entry.published_parsed[:6]).astimezone(tz_canarias).date()
                if fecha_pub == fecha_objetivo:
                    titulo = entry.title.strip()
                    resumen = entry.get("summary", "").strip()
                    link = entry.link

                    match_boletin = re.search(r"/boc/(\d{4})/(\d{1,3})/", link)
                    if match_boletin:
                        anio, num_boletin = match_boletin.groups()
                    else:
                        anio = num_boletin = None

                    num_anuncio = extraer_numero_anuncio(resumen)
                    if anio and num_boletin and num_anuncio:
                        url_correcta = f"https://www.gobiernodecanarias.org/boc/{anio}/{num_boletin}/{num_anuncio}.html"
                    else:
                        url_correcta = link

                    resultados.append({
                        "boletin": "BOC",
                        "titulo": titulo,
                        "url": url_correcta,
                        "fecha": fecha_pub.strftime('%Y-%m-%d'),
                        "contenido": resumen
                    })
    except Exception as e:
        pass
    return resultados

def obtener_boc_reciente():
    for offset in [0, 1, 2, 3, -1, -2, -3]:
        fecha_objetivo = hoy_canarias + timedelta(days=offset)
        resultados = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            tareas = [executor.submit(parsear_feed_con_fecha, url, fecha_objetivo) for url in BOC_FEEDS]
            for future in as_completed(tareas):
                resultados += future.result()
        if resultados:
            return resultados
    return []

# --- Función para extraer texto completo de un enlace ---
def extraer_texto_completo_desde_url(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        # BOE
        if "boe.es" in url:
            textoxslt_div = soup.find("div", id="textoxslt")
            if textoxslt_div:
                return textoxslt_div.get_text(separator="\n", strip=True)
        # BOC
        if "gobiernodecanarias.org" in url:
            for clase in ["texto", "contenido", "cuerpo", "main", "articulo"]:
                texto_div = soup.find("div", class_=clase)
                if texto_div:
                    return texto_div.get_text(separator="\n", strip=True)
            if soup.body:
                return soup.body.get_text(separator="\n", strip=True)
            else:
                return "⚠️ No se pudo extraer contenido útil del enlace."
        return "⚠️ No se pudo extraer contenido útil del enlace."
    except Exception as e:
        return f"❌ Error al extraer texto completo: {e}"

# --- Función para resumir con Gemini ---
import time
import random

def resumir_con_gemini(texto, max_tokens=700, modelo="gemini-2.5-pro", debug=False):
    """
    Resumen legal en español con el SDK oficial de Gemini (google-genai).
    - Config simple (sin safety_settings).
    - Reintenta 5xx y hace fallback a 'gemini-2.5-flash'.
    - Fuerza salida en texto plano.
    """
    prompt_usuario = (
        "Resume de forma clara, directa y en español el siguiente contenido legal. "
        "Incluye el motivo del decreto, sus objetivos principales y las medidas más relevantes.\n\n"
        + (texto or "")
    )

    def _extract_text(resp):
        try:
            if hasattr(resp, "text") and isinstance(resp.text, str) and resp.text.strip():
                return resp.text.strip()
        except Exception:
            pass
        try:
            for c in getattr(resp, "candidates", []) or []:
                content = getattr(c, "content", None)
                parts = getattr(content, "parts", None) if content else None
                if parts:
                    trozos = []
                    for p in parts:
                        t = getattr(p, "text", None)
                        if isinstance(t, str) and t.strip():
                            trozos.append(t.strip())
                    if trozos:
                        return "\n".join(trozos).strip()
        except Exception:
            pass
        try:
            t = getattr(resp, "output_text", None)
            if isinstance(t, str) and t.strip():
                return t.strip()
        except Exception:
            pass
        return None

    def _finish_info(resp):
        try:
            info = []
            for c in getattr(resp, "candidates", []) or []:
                fr = getattr(c, "finish_reason", None) or getattr(c, "finishReason", None)
                if fr: info.append(f"finish_reason={fr}")
                sr = getattr(c, "safety_ratings", None) or getattr(c, "safetyRatings", None)
                if sr: info.append(f"safety_ratings={sr}")
            pf = getattr(resp, "prompt_feedback", None) or getattr(resp, "promptFeedback", None)
            if pf:
                br = getattr(pf, "block_reason", None) or getattr(pf, "blockReason", None)
                if br: info.append(f"prompt_block_reason={br}")
            return " | ".join(info) if info else None
        except Exception:
            return None

    def _call(modelo_activo, max_out):
        return gclient.models.generate_content(
            model=modelo_activo,          # "gemini-2.5-pro" o "models/gemini-2.5-pro"
            contents=prompt_usuario,      # string directo
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=max_out,
                system_instruction="Eres un experto legal que resume documentos de manera precisa.",
                response_mime_type="text/plain",  # salida en texto plano
            ),
        )

    max_out_main = min(max_tokens, 700)

    # 1) Intentos contra el modelo principal
    for intento in range(3):
        try:
            resp = _call(modelo, max_out_main)
            texto_out = _extract_text(resp)
            if texto_out:
                return texto_out
            if debug:
                diag = _finish_info(resp)
                if diag:
                    st.info(f"Diagnóstico de respuesta (sin texto): {diag}")
            return "⚠️ El modelo no devolvió texto. Activa debug=True para ver detalles y/o prueba con 'gemini-2.5-flash'."
        except Exception as e:
            msg = str(e)
            if any(code in msg for code in [" 500", " 502", " 503", " 504", "INTERNAL", "UNAVAILABLE", "DEADLINE_EXCEEDED"]):
                time.sleep((2 ** intento) + random.uniform(0, 0.5))
                continue
            return f"❌ Error generando resumen con Gemini ({modelo}): {e}"

    # 2) Fallback a modelo rápido
    modelo_fallback = "gemini-2.5-flash"
    try:
        resp = _call(modelo_fallback, min(max_tokens, 600))
        texto_out = _extract_text(resp)
        if texto_out:
            return texto_out + "\n\n_(Generado con modelo de respaldo: gemini-2.5-flash)_"
        if debug:
            diag = _finish_info(resp)
            if diag:
                st.info(f"Diagnóstico (fallback sin texto): {diag}")
        return "⚠️ El modelo de respaldo no devolvió texto. Prueba con un texto más corto."
    except Exception as e2:
        return f"❌ Error con el modelo de respaldo ({modelo_fallback}): {e2}"

# --- Cargar boletines al iniciar (cache) ---
@st.cache_data(show_spinner="Cargando boletines...")
def cargar_boletines_con_numeracion():
    boe = obtener_boe_reciente()
    boc = obtener_boc_reciente()
    resultados_totales = boe + boc
    # Asignar numeración original global
    for idx, r in enumerate(resultados_totales, 1):
        r["n_original"] = idx
    return boe, boc, resultados_totales

# --- App principal ---
st.set_page_config(page_title="Buscador boletines", page_icon="⚖️")
st.title("Buscador boletines oficiales [BOE/BOC]")

st.info(f"📅 Hoy (Madrid): {hoy_madrid.strftime('%Y-%m-%d')} | 📅 Hoy (Canarias): {hoy_canarias.strftime('%Y-%m-%d')}")

# --- Cargar resultados con numeración global ---
resultados_boe, resultados_boc, resultados_totales = cargar_boletines_con_numeracion()

# --- Menú de acciones ---
accion = st.selectbox(
    "¿Qué quieres hacer?",
    ["🗂️ Ver boletines", "🔍 Buscar texto", "📝 Resumir por número"]
)

# --- Acción: Ver boletines ---
if accion == "🗂️ Ver boletines":
    filtro = st.selectbox(
        "Filtrar por boletín:",
        ["✅ Todos", "🟥 Solo BOE", "⬜ Solo BOC"]
    )
    if filtro == "🟥 Solo BOE":
        resultados = [r for r in resultados_totales if r["boletin"] == "BOE"]
    elif filtro == "⬜ Solo BOC":
        resultados = [r for r in resultados_totales if r["boletin"] == "BOC"]
    else:
        resultados = resultados_totales

    por_pagina = 20
    total_paginas = (len(resultados) + por_pagina - 1) // por_pagina or 1
    pagina = st.number_input("Página", min_value=1, max_value=total_paginas, value=1, step=1)

    inicio = (pagina - 1) * por_pagina
    fin = min(inicio + por_pagina, len(resultados))

    st.write(f"📋 Mostrando resultados {inicio + 1} a {fin} de {len(resultados)}")

    for r in resultados[inicio:fin]:
        st.markdown(f"**[{r['n_original']}]** {'🟥' if r['boletin']=='BOE' else '⬜'} {r['boletin']} - {r['fecha']}")
        st.markdown(f"📰 {r['titulo']}")
        st.markdown(f"🔗 [Ir al boletín original]({r['url']})")
        st.markdown("<hr style='margin:0.15rem 0;'>", unsafe_allow_html=True)

# --- Acción: Buscar texto ---
elif accion == "🔍 Buscar texto":
    consulta = st.text_input("Escribe el texto que quieres buscar en los boletines:")
    if consulta and len(consulta) >= 2:
        encontrados = []
        for r in resultados_totales:
            texto = f"{r['titulo']} {r['contenido']}".lower()
            if consulta.lower() in texto:
                encontrados.append(r)
        st.success(f"Coincidencias encontradas: {len(encontrados)}")
        for r in encontrados:
            st.markdown(f"**[{r['n_original']}]** {'🟥' if r['boletin']=='BOE' else '⬜'} {r['boletin']} - {r['fecha']}")
            st.markdown(f"📰 {r['titulo']}")
            st.markdown(f"🔗 [Ir al boletín original]({r['url']})")
            st.write("---")
    elif consulta:
        st.warning("Escribe al menos 2 caracteres para buscar.")

# --- Acción: Resumir por número global (n_original) ---
elif accion == "📝 Resumir por número":
    num_str = st.text_input("Introduce el número del anuncio (ejemplo: 82):")
    if num_str:
        try:
            num = int(num_str)
            anuncio = next((r for r in resultados_totales if r["n_original"] == num), None)
            if anuncio is not None:
                st.markdown(f"### 📰 {(anuncio.get('titulo') or '').strip()}")
                st.markdown(f"🔗 [Ver boletín completo]({anuncio.get('url', '')})")
                with st.spinner("📡 Obteniendo texto completo del enlace..."):
                    texto_completo = extraer_texto_completo_desde_url(anuncio['url'])
                if texto_completo.startswith("❌") or texto_completo.startswith("⚠️"):
                    st.error(texto_completo)
                else:
                    st.success("Texto extraído correctamente. Generando resumen...")
                    # Nuevo corte ajustado para no superar el límite de tokens
                    max_palabras = 3500
                    palabras = texto_completo.split()
                    if len(palabras) > max_palabras:
                        texto_para_modelo = " ".join(palabras[:max_palabras]) + "..."
                        st.info(f"✂️ Texto recortado a {max_palabras} palabras para no superar el límite del modelo.")
                    else:
                        texto_para_modelo = texto_completo
                    with st.spinner("⏳ Resumiendo con Gemini 2.5 Pro..."):
                        resumen = resumir_con_gemini(texto_para_modelo)
                    st.markdown("#### 📃 RESUMEN GENERADO")
                    st.write(resumen)
            else:
                st.error("❌ Número fuera del rango.")
        except ValueError:
            st.error("❌ Por favor introduce un número válido.")


st.info("Desarrollado por JCastro / ©2025")
