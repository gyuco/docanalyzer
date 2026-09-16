"""Importa i profili così che si registrino.

I primi tre sono il tronco comune; quelli specifici per emittente stanno nei
file successivi e di norma estendono uno dei tre.
"""

from docanalyzer.profiles import (  # noqa: F401
    core,
    personal,
    us_checking,
)
from docanalyzer.profiles.base import (
    all_profiles,
    available_profiles,
    get_profile,
    register,
)

__all__ = ["all_profiles", "available_profiles", "get_profile", "register"]
