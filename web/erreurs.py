"""Erreurs métier présentables à l'utilisateur."""

from __future__ import annotations


class ErreurUtilisateur(Exception):
    """Erreur attendue, avec un message français et un statut HTTP."""

    def __init__(
        self,
        message: str,
        statut: int = 400,
        code: str = "requete_invalide",
    ) -> None:
        super().__init__(message)
        self.message = message
        self.statut = statut
        self.code = code
