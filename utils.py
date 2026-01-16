# utils.py
import re
import secrets
import string
import hashlib

# --- Validadores y Helpers ---
def generate_verification_code(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()[:10]

def validate_university_email(email: str) -> bool:
    return bool(re.search(r"@(?:mail\.)?pucv\.cl$", email.strip(), flags=re.IGNORECASE))

def validate_minecraft_username(username: str) -> bool:
    return re.match(r'^\w{3,16}$', username) is not None

# --- DATOS DE CARRERAS (Actualizado con tus Emojis) ---
FACULTIES = {
    "Arquitectura y Urbanismo": {
        "🏛️ Arquitectura": "ARQ",
        "🎨 Diseño": "DIS",
        "🎭 Licenciatura en Arte": "ART"
    },
    "Ciencias": {
        "🔬 Bachillerato en Ciencias": "BCI",
        "📐 Pedagogía en Matemáticas": "PMA",
        "➗ Licenciatura en Matemáticas": "LMA",
        "🔭 Pedagogía en Física": "PFI",
        "⚛️ Licenciatura en Física": "LFI",
        "🌱 Pedagogía en Biología": "PBI",
        "🧬 Licenciatura en Biología": "LBI",
        "🧫 Pedagogía en Química": "PQU",
        "🧪 Bioquímica": "BIO",
        "🏭 Química Industrial": "QIN",
        "💊 Química y Farmacia": "QYF",
        "🏥 Tecnología Médica": "TME",
        "🏃‍♂️ Kinesiología": "KIN"
    },
    "Agronomía": {
        "🌾 Agronomía": "AGR"
    },
    "Ciencias del Mar": {
        "🌍 Geografía": "GEO",
        "🌊 Oceanografía": "OCE"
    },
    "Económicas y Administrativas": {
        "💰 Contador Auditor": "CAU",
        "📈 Ingeniería Comercial": "ICO",
        "🏢 Ing. Admin Negocios": "IAN",
        "📰 Periodismo": "PER",
        "🤝 Trabajo Social": "TSO"
    },
    "Derecho": {
        "⚖️ Derecho": "DER"
    },
    "Teología": {
        "✝️ Teología": "TEO",
        "📖 Ciencias Religiosas": "CRE"
    },
    "Filosofía y Educación": {
        "👶 Educación Parvularia": "EPA",
        "🏫 Educación Básica": "EBA",
        "♿ Educación Especial": "EES",
        "🇬🇧 Pedagogía en Inglés": "PIN",
        "🔤 Traducción/Interpretación": "TRI",
        "🎵 Música": "MUS",
        "🤔 Filosofía": "FIL",
        "🏺 Historia": "HIS",
        "✏️ Castellano": "CAS",
        "📚 Literatura": "LIT",
        "🏋️‍♂️ Educación Física": "EFI",
        "🧩 Psicología": "PSI"
    },
    "Ingeniería": {
        "🏗️ Ingeniería Civil": "ICV",
        "🧫 Civil Bioquímica": "ICB",
        "⛏️ Civil de Minas": "ICM",
        "⚡ Civil Eléctrica": "ICE",
        "🔌 Civil Electrónica": "IEL",
        "💻 Civil Ciencia de Datos": "ICD",
        "🏘️ Civil Construcción": "ICC",
        "📡 Civil Telecomunicaciones": "ICT",
        "🚚 Civil Transporte": "ITR",
        "🏭 Civil Industrial": "IND",
        "🖥️ Ingeniería Civil Informática": "ICI",
        "🔩 Civil Metalúrgica": "IME",
        "⚙️ Civil Mecánica": "ICZ",
        "🧪 Civil Química": "ICQ",
        "🔌 Ingeniería Eléctrica": "IEG",
        "📟 Ingeniería Electrónica": "IEN",
        "🏗️ Ingeniería Construcción": "ICO",
        "💻 Ingeniería Informática": "INF",
        "⚙️ Ingeniería Mecánica": "MEC"
    },
    "Formación Profesional (PIFP)": {
        "🏛️ Administración Pública": "APU",
        "🎬 Animación Digital": "ANI",
        "🎮 Videojuegos y Simulación": "VID",
        "📸 Fotografía": "FOT",
        "🎨 Ilustración": "ILU",
        "🎶 Producción Musical": "PRM",
        "📢 Publicidad": "PUB"
    }
}