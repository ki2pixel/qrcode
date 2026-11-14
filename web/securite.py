"""Contrôles d'accès, en-têtes de sécurité et réponses d'erreur."""

from __future__ import annotations

import hmac
import secrets

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from web import config
from web.erreurs import ErreurUtilisateur

CSP = (
    "default-src 'self'; "
    "base-uri 'none'; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "form-action 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'"
)


def _est_api() -> bool:
    return request.path.startswith("/api/")


def reponse_erreur(
    message: str,
    statut: int,
    code: str = "erreur",
    reference: str | None = None,
):
    if _est_api():
        charge: dict[str, object] = {"erreur": message, "code": code}
        if reference:
            charge["reference"] = reference
        return jsonify(charge), statut
    return (
        render_template(
            "erreur.html",
            titre="Accès refusé" if statut in (401, 403) else "Erreur",
            message=message,
            statut=statut,
            reference=reference,
        ),
        statut,
    )


def _origine_autorisee() -> bool:
    origine = request.headers.get("Origin")
    if not origine:
        return True
    return origine.rstrip("/") in config.ORIGINES_AUTORISEES


def installer_securite(app: Flask, jeton: str) -> None:
    app.config["JETON"] = jeton

    @app.before_request
    def controler_acces():
        hote = (request.host or "").lower()
        if hote not in config.HOTES_AUTORISES:
            return reponse_erreur(
                "Hôte non autorisé. Ouvrez http://127.0.0.1:5100/.",
                403,
                "hote_non_autorise",
            )

        chemin = request.path
        if chemin == "/" or chemin == "/favicon.ico" or chemin.startswith("/static/"):
            return None

        entete_api = request.headers.get(config.ENTETE_API) == "1"

        if chemin == "/api/session" and request.method == "POST":
            if not entete_api:
                return reponse_erreur(
                    "En-tête d'interface manquant.", 403, "entete_manquant"
                )
            if not _origine_autorisee():
                return reponse_erreur(
                    "Origine non autorisée.", 403, "origine_non_autorisee"
                )
            return None

        if chemin.startswith("/api/"):
            if not entete_api:
                return reponse_erreur(
                    "En-tête d'interface manquant.", 403, "entete_manquant"
                )
            cookie = request.cookies.get(config.NOM_COOKIE, "")
            if not cookie or not hmac.compare_digest(cookie, jeton):
                return reponse_erreur(
                    "Session expirée. Relancez ./lancer_interface.sh et ouvrez le lien affiché.",
                    401,
                    "session_expiree",
                )
            if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not _origine_autorisee():
                return reponse_erreur(
                    "Origine non autorisée.", 403, "origine_non_autorisee"
                )
        return None

    @app.after_request
    def ajouter_entetes(reponse):
        reponse.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        reponse.headers["Pragma"] = "no-cache"
        reponse.headers["Expires"] = "0"
        reponse.headers["X-Content-Type-Options"] = "nosniff"
        reponse.headers["X-Frame-Options"] = "DENY"
        reponse.headers["Referrer-Policy"] = "no-referrer"
        reponse.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), interest-cohort=()"
        )
        reponse.headers["Content-Security-Policy"] = CSP
        reponse.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        reponse.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        reponse.headers["Server"] = "QRCode-Local"
        return reponse

    @app.errorhandler(ErreurUtilisateur)
    def erreur_utilisateur(exc: ErreurUtilisateur):
        return reponse_erreur(exc.message, exc.statut, exc.code)

    @app.errorhandler(HTTPException)
    def erreur_http(exc: HTTPException):
        messages = {
            400: "Requête invalide.",
            403: "Accès refusé.",
            404: "Ressource introuvable.",
            405: "Méthode non autorisée.",
            413: "Fichier trop volumineux.",
            500: "Erreur interne.",
        }
        return reponse_erreur(
            messages.get(exc.code or 500, "Erreur HTTP."),
            exc.code or 500,
            f"http_{exc.code or 500}",
        )

    @app.errorhandler(Exception)
    def erreur_generale(exc: Exception):
        reference = secrets.token_hex(4)
        # Ne jamais journaliser le contenu de l'exception : il peut contenir
        # des fragments de CSV ou de secrets.
        app.logger.error(
            "Erreur interne %s (%s)", reference, type(exc).__name__
        )
        return reponse_erreur(
            "Erreur interne. Consultez le terminal du serveur avec cette référence.",
            500,
            "erreur_interne",
            reference,
        )
