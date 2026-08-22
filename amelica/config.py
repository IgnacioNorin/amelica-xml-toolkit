"""
config.py — Credenciales del portal.

credentials.json vive en la raiz del proyecto (al lado de pyproject.toml) y
esta en .gitignore: nunca se sube al repo, queda solo en tu disco. Usa
credentials.example.json como plantilla.
"""

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS_FILE = PROJECT_ROOT / "credentials.json"


class Credentials:
    """email / password / volume, con las variables de entorno por delante.

    `volume` es el numero+edicion tal cual aparece en la lista de AmeliCA
    (ej: "38 (1)"). Si coincide con un numero "En proceso", se selecciona
    automaticamente sin preguntar.
    """

    def __init__(self, email=None, password=None, volume=None):
        self.email = email
        self.password = password
        self.volume = volume

    def __iter__(self):
        """Permite: email, password, volume = load_credentials()"""
        return iter((self.email, self.password, self.volume))


def load_credentials() -> Credentials:
    """Lee las credenciales de las variables de entorno y, si faltan, del
    credentials.json de la raiz. Las variables de entorno tienen prioridad,
    para poder correr en CI o en otra maquina sin tocar el archivo."""
    env = Credentials(
        email=os.environ.get("AMELICA_EMAIL"),
        password=os.environ.get("AMELICA_PASSWORD"),
        volume=os.environ.get("AMELICA_VOLUME"),
    )
    if env.email and env.password:
        return env

    if not CREDENTIALS_FILE.exists():
        return env

    try:
        data = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"No se pudo leer {CREDENTIALS_FILE.name}: {e}")
        return env

    return Credentials(
        email=env.email or data.get("email"),
        password=env.password or data.get("password"),
        volume=env.volume or data.get("volume"),
    )
