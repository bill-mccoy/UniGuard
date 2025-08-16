import secrets
import string
import hashlib
import re

def generate_verification_code(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def hash_code(code: str) -> str:
    # truncamos a 10 hex chars como pediste
    return hashlib.sha256(code.encode()).hexdigest()[:10]

def validate_university_email(email: str) -> bool:
    return bool(re.fullmatch(r"[^@]+@mail\.pucv\.cl", email.strip(), flags=re.IGNORECASE))

def validate_minecraft_username(username: str) -> bool:
    """Valida que el nombre de Minecraft sea válido"""
    return re.match(r'^\w{3,16}$', username) is not None
