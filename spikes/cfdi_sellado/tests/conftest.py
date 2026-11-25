import os
import sys
from pathlib import Path

import pytest

AQUI = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AQUI))

from firmante import FirmanteLocal  # noqa: E402
import verificacion_sat  # noqa: E402

DIR_CSD = Path(os.environ.get("SPIKE_CSD_DIR", Path.home() / ".cache" / "atlas-financials-spike-csd"))
# Contraseña pública de los CSD de prueba del SAT (Contraseña.txt dentro del zip).
CONTRASENA_PRUEBA = "12345678a"


def _archivo(patron: str) -> Path:
    hallados = sorted(DIR_CSD.glob(patron))
    if not hallados:
        pytest.skip(f"Falta el CSD de prueba en {DIR_CSD}; corre descargar_recursos_sat.py")
    return hallados[0]


@pytest.fixture(scope="session", autouse=True)
def _recursos_sat():
    if not verificacion_sat.recursos_disponibles():
        pytest.skip("Faltan XSD/XSLT del SAT en recursos_sat/; corre descargar_recursos_sat.py")


@pytest.fixture(scope="session")
def cer_path() -> Path:
    return _archivo("CSD_*EKU9003173C9*.cer")


@pytest.fixture(scope="session")
def key_path() -> Path:
    return _archivo("CSD_*EKU9003173C9*.key")


@pytest.fixture(scope="session")
def firmante_local(cer_path, key_path) -> FirmanteLocal:
    return FirmanteLocal.desde_archivos(cer_path, key_path, CONTRASENA_PRUEBA)
