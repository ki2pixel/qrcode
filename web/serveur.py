"""Serveur Flask local, strictement lié à 127.0.0.1:5100."""

from __future__ import annotations

import argparse
import ctypes
import os
import resource
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

sys.dont_write_bytecode = True
if __package__ in (None, ""):  # exécution directe : python web/serveur.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask, jsonify, render_template, request, send_file  # noqa: E402
from werkzeug.serving import WSGIRequestHandler, make_server  # noqa: E402

from web import config, espace_ram, securite  # noqa: E402
from web.erreurs import ErreurUtilisateur  # noqa: E402
from web.registre import REGISTRE  # noqa: E402
from web.services import consultation, generation, usb  # noqa: E402
from web.utilitaires import (  # noqa: E402
    env_sous_processus,
    lire_corps_limite,
    nom_fichier_depuis_entete,
)

STRICT_RAM = False
WEASYPRINT_OK = False


class JournalDiscret(WSGIRequestHandler):
    """Journal minimal : jamais de query string, d'en-tête ni de corps."""

    server_version = "QRCode-Local"
    sys_version = ""

    def log_request(self, code="-", size="-"):
        chemin = (self.path or "").split("?", 1)[0]
        if chemin.startswith("/static/"):
            return
        sys.stderr.write(f"{self.command} {chemin} -> {code}\n")

    def log_message(self, format, *args):
        return

    def log_error(self, format, *args):
        return


def creer_app(jeton: str, strict_ram: bool, weasyprint_ok: bool) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["MAX_CONTENT_LENGTH"] = config.LIMITE_ZIP + 1024 * 1024
    app.config["SECRET_KEY"] = secrets.token_bytes(32)
    app.config["STRICT_RAM"] = strict_ram
    app.config["WEASYPRINT_OK"] = weasyprint_ok
    app.json.ensure_ascii = False
    app.json.sort_keys = False

    securite.installer_securite(app, jeton)

    @app.get("/")
    def accueil():
        return render_template(
            "index.html",
            version=config.VERSION,
            port=config.PORT,
            limite_csv=config.LIMITE_CSV,
            limite_json=config.LIMITE_JSON_SCANS,
            ttl_minutes=config.TTL_SECONDES // 60,
            ttl_secondes=config.TTL_SECONDES,
        )

    @app.get("/favicon.ico")
    def favicon():
        return "", 204

    @app.post("/api/session")
    def session():
        donnees = request.get_json(silent=True) or {}
        fourni = donnees.get("jeton", "") if isinstance(donnees, dict) else ""
        if not isinstance(fourni, str) or not secrets.compare_digest(fourni, jeton):
            return jsonify({"erreur": "Jeton d'accès invalide.", "code": "jeton_invalide"}), 403
        reponse = jsonify({"ok": True})
        reponse.set_cookie(
            config.NOM_COOKIE,
            jeton,
            httponly=True,
            samesite="Strict",
            secure=False,
            path="/",
        )
        return reponse

    @app.get("/api/etat")
    def etat():
        try:
            libre = shutil.disk_usage(espace_ram.racine_ram()).free
        except OSError:
            libre = None
        return jsonify(
            {
                "version": config.VERSION,
                "port": config.PORT,
                "strict_ram": strict_ram,
                "weasyprint": app.config.get("WEASYPRINT_OK", False),
                "qrencode": _which_systeme("qrencode"),
                "split": _which_systeme("split"),
                "swap_disque_actif": usb.swap_disque_actif(),
                "espace_ram_libre": libre,
                "limite_csv": config.LIMITE_CSV,
                "limite_json": config.LIMITE_JSON_SCANS,
                "ttl_secondes": config.TTL_SECONDES,
                "generations": generation.lister_jobs(),
                "consultations": consultation.lister_resumees(),
            }
        )

    @app.post("/api/purge")
    def purge():
        resultat = REGISTRE.purger_tout()
        return jsonify({"ok": True, **resultat})

    # ------------------------------------------------------------------
    # Génération
    # ------------------------------------------------------------------
    @app.post("/api/generation/apercu")
    def generation_apercu():
        donnees = lire_corps_limite(config.LIMITE_CSV)
        stats = generation.analyser_donnees(donnees, nom_fichier_depuis_entete())
        return jsonify(stats)

    @app.post("/api/generation")
    def generation_demarrer():
        donnees = lire_corps_limite(config.LIMITE_CSV)
        mise_en_page = request.headers.get("X-QR-Mise-En-Page", "compact")
        tache = generation.demarrer_generation(
            donnees, nom_fichier_depuis_entete(), mise_en_page
        )
        return jsonify(tache.instantane()), 202

    @app.get("/api/generation/<job_id>")
    def generation_etat(job_id: str):
        return jsonify(generation.obtenir_job(job_id).instantane())

    @app.post("/api/generation/<job_id>/annuler")
    def generation_annuler(job_id: str):
        return jsonify(generation.annuler_generation(job_id))

    @app.delete("/api/generation/<job_id>")
    def generation_supprimer(job_id: str):
        generation.detruire_generation(job_id)
        return jsonify({"ok": True})

    @app.get("/api/generation/<job_id>/fichier/<cle>")
    def generation_fichier(job_id: str, cle: str):
        chemin, nom, mime = generation.fichier_generation(job_id, cle)
        return send_file(
            chemin,
            mimetype=mime,
            as_attachment=True,
            download_name=nom,
            conditional=False,
            etag=False,
            max_age=0,
        )

    # ------------------------------------------------------------------
    # Consultation
    # ------------------------------------------------------------------
    @app.get("/api/consultation/sauvegardes")
    def consultation_sources():
        return jsonify(consultation.sources_disponibles())

    @app.post("/api/consultation/source")
    def consultation_source():
        donnees = request.get_json(silent=True) or {}
        if not isinstance(donnees, dict):
            raise ErreurUtilisateur("Requête invalide.", 400, "requete_invalide")
        type_source = donnees.get("type")
        if type_source == "job":
            session = consultation.creer_depuis_job(str(donnees.get("job_id", "")))
        elif type_source == "dossier":
            session = consultation.creer_depuis_dossier(str(donnees.get("chemin", "")))
        else:
            raise ErreurUtilisateur(
                "Type de source inconnu. Choisissez une session, un dossier ou une archive.",
                400,
                "source_inconnue",
            )
        return jsonify(session.instantane())

    @app.post("/api/consultation/archive")
    def consultation_archive():
        session = consultation.creer_depuis_flux(request.stream, config.LIMITE_ZIP)
        return jsonify(session.instantane())

    @app.get("/api/consultation/<session_id>")
    def consultation_etat(session_id: str):
        return jsonify(consultation.obtenir_session(session_id).instantane())

    @app.post("/api/consultation/<session_id>/scans")
    def consultation_scans(session_id: str):
        session = consultation.obtenir_session(session_id)
        donnees = lire_corps_limite(config.LIMITE_JSON_SCANS)
        info = consultation.uploader_scans(
            session, donnees, nom_fichier_depuis_entete()
        )
        return jsonify({"ok": True, "scans": info, "session": session.instantane()})

    @app.post("/api/consultation/<session_id>/recherche")
    def consultation_recherche(session_id: str):
        session = consultation.obtenir_session(session_id)
        donnees = request.get_json(silent=True) or {}
        requete = donnees.get("q", "") if isinstance(donnees, dict) else ""
        if not isinstance(requete, str):
            raise ErreurUtilisateur("Requête invalide.", 400, "requete_invalide")
        return jsonify(consultation.rechercher(session, requete))

    @app.post("/api/consultation/<session_id>/extraire")
    def consultation_extraire(session_id: str):
        session = consultation.obtenir_session(session_id)
        donnees = request.get_json(silent=True) or {}
        if not isinstance(donnees, dict):
            raise ErreurUtilisateur("Requête invalide.", 400, "requete_invalide")
        return jsonify(consultation.extraire(session, str(donnees.get("record_id", ""))))

    @app.post("/api/consultation/<session_id>/reveler")
    def consultation_reveler(session_id: str):
        session = consultation.obtenir_session(session_id)
        donnees = request.get_json(silent=True) or {}
        if not isinstance(donnees, dict):
            raise ErreurUtilisateur("Requête invalide.", 400, "requete_invalide")
        ligne = donnees.get("ligne")
        if not isinstance(ligne, int):
            raise ErreurUtilisateur("Ligne invalide.", 400, "ligne_invalide")
        return jsonify(
            consultation.reveler(
                session, str(donnees.get("extraction_id", "")), ligne
            )
        )

    @app.post("/api/consultation/<session_id>/restaurer")
    def consultation_restaurer(session_id: str):
        session = consultation.obtenir_session(session_id)
        return jsonify(consultation.restaurer(session))

    @app.get("/api/consultation/<session_id>/fichier/<cle>")
    def consultation_fichier(session_id: str, cle: str):
        session = consultation.obtenir_session(session_id)
        if cle == "extraction":
            chemin, nom, mime = consultation.fichier_extraction(session)
        elif cle == "restauration":
            chemin, nom, mime = consultation.fichier_restauration(session)
        else:
            raise ErreurUtilisateur("Fichier introuvable.", 404, "fichier_inconnu")
        return send_file(
            chemin,
            mimetype=mime,
            as_attachment=True,
            download_name=nom,
            conditional=False,
            etag=False,
            max_age=0,
        )

    @app.delete("/api/consultation/<session_id>")
    def consultation_supprimer(session_id: str):
        consultation.detruire_session(session_id)
        return jsonify({"ok": True})

    # ------------------------------------------------------------------
    # Coffre USB
    # ------------------------------------------------------------------
    @app.get("/api/usb/peripheriques")
    def usb_peripheriques():
        return jsonify(usb.peripheriques())

    @app.post("/api/usb/demonter")
    def usb_demonter():
        donnees = request.get_json(silent=True) or {}
        return jsonify(usb.demonter_partition(donnees))

    @app.post("/api/usb/commandes")
    def usb_commandes():
        donnees = request.get_json(silent=True) or {}
        return jsonify(usb.generer_commandes(donnees))

    return app


def _desactiver_core_dumps() -> None:
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ValueError, OSError) as exc:
        raise RuntimeError(
            "Impossible de désactiver les core dumps. Arrêt par précaution."
        ) from exc
    if resource.getrlimit(resource.RLIMIT_CORE)[0] != 0:
        raise RuntimeError("Les core dumps sont toujours actifs. Arrêt par précaution.")


def _desactiver_dumpable() -> None:
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl(4, 0, 0, 0, 0)  # PR_SET_DUMPABLE
    except (OSError, AttributeError):
        pass


def _verrouiller_memoire() -> bool:
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        limite = resource.getrlimit(resource.RLIMIT_MEMLOCK)[0]
        drapeaux = 1  # MCL_CURRENT
        if limite == resource.RLIM_INFINITY or limite >= 512 * 1024 * 1024:
            drapeaux |= 2  # MCL_FUTURE, seulement si la limite couvre la croissance
        if libc.mlockall(drapeaux) == 0:
            return True
    except (OSError, AttributeError, ValueError):
        pass
    return False


def _which_systeme(commande: str) -> bool:
    chemin = config.PATH_SYSTEME or os.environ.get("PATH", "")
    return shutil.which(commande, path=chemin) is not None


def _weasyprint_disponible() -> bool:
    espace = espace_ram.EspaceRam("verif")
    try:
        env = env_sous_processus(espace)
        resultat = subprocess.run(
            [config.PYTHON_SYSTEME, "-c", "import weasyprint"],
            cwd=str(espace.base),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
        return resultat.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        espace.detruire()


def main() -> int:
    parser = argparse.ArgumentParser(description="Interface web locale de sauvegarde QR.")
    parser.add_argument(
        "--strict-ram",
        action="store_true",
        help="Refuser le démarrage si un swap disque est actif.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Ne pas ouvrir automatiquement le navigateur.",
    )
    args = parser.parse_args()

    os.umask(0o077)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        _desactiver_core_dumps()
    except RuntimeError as exc:
        print(f"[ERREUR] {exc}", file=sys.stderr)
        return 1
    _desactiver_dumpable()
    memoire_verrouillee = _verrouiller_memoire()

    try:
        base = espace_ram.initialiser_ram()
    except RuntimeError as exc:
        print(f"[ERREUR] {exc}", file=sys.stderr)
        return 1

    swap_disque = usb.swap_disque_actif()
    if swap_disque and args.strict_ram:
        print(
            "[ERREUR] --strict-ram : un swap disque est actif.\n"
            "Désactivez-le avec « sudo swapoff -a », relancez l'interface, puis "
            "réactivez-le avec « sudo swapon -a » après usage.",
            file=sys.stderr,
        )
        espace_ram.arreter_ram()
        return 1
    if swap_disque:
        print(
            "[ATTENTION] Un swap disque est actif : des pages de mémoire peuvent "
            "être écrites sur le disque. Utilisez --strict-ram ou le coffre USB "
            "pour une confidentialité maximale.",
            file=sys.stderr,
        )

    weasyprint_ok = _weasyprint_disponible()
    if not weasyprint_ok:
        print(
            "[ATTENTION] WeasyPrint n'est pas importable par le Python système : "
            "les PDF ne seront pas générés, les HTML resteront disponibles.",
            file=sys.stderr,
        )
    for commande in ("qrencode", "split"):
        if not _which_systeme(commande):
            print(f"[ATTENTION] Commande absente : {commande}", file=sys.stderr)

    jeton = secrets.token_urlsafe(32)
    app = creer_app(jeton, args.strict_ram, weasyprint_ok)
    REGISTRE.demarrer_nettoyage()

    try:
        serveur = make_server(
            config.HOTE,
            config.PORT,
            app,
            threaded=True,
            request_handler=JournalDiscret,
        )
    except OSError as exc:
        REGISTRE.arreter()
        espace_ram.arreter_ram()
        print(
            f"[ERREUR] Impossible d'écouter sur {config.HOTE}:{config.PORT} : {exc}\n"
            "Le port 5100 est peut-être déjà utilisé.",
            file=sys.stderr,
        )
        return 1

    url = f"http://{config.HOTE}:{config.PORT}/#jeton={jeton}"
    print()
    print("=" * 68)
    print("  Interface web locale — Sauvegarde QR")
    print("=" * 68)
    print(f"  URL : {url}")
    print(f"  RAM : {base}")
    print(f"  WeasyPrint : {'oui' if weasyprint_ok else 'non (HTML seulement)'}")
    print(f"  Mémoire verrouillée : {'oui' if memoire_verrouillee else 'non'}")
    print(f"  Swap disque actif : {'oui' if swap_disque else 'non'}")
    print()
    print("  Tout est traité en mémoire vive. Ctrl+C pour tout effacer et quitter.")
    print("=" * 68)
    print()

    if not args.no_browser and (
        os.environ.get("DISPLAY")
        or os.environ.get("WAYLAND_DISPLAY")
        or os.environ.get("BROWSER")
    ):
        threading.Thread(
            target=lambda: webbrowser.open(url, new=2), daemon=True
        ).start()

    arret_demande = False

    def arreter(signum, frame):
        nonlocal arret_demande
        if arret_demande:
            return
        arret_demande = True
        # Un terminal peut envoyer plusieurs SIGHUP lors de sa fermeture.
        # Ignorer les signaux suivants évite d'interrompre la purge tmpfs.
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            try:
                signal.signal(sig, signal.SIG_IGN)
            except (OSError, ValueError):
                pass
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, arreter)
    signal.signal(signal.SIGTERM, arreter)
    signal.signal(signal.SIGHUP, arreter)

    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt demandé. Purge de la mémoire vive…", file=sys.stderr)
    finally:
        try:
            serveur.server_close()
        except Exception:
            pass
        try:
            REGISTRE.arreter()
        finally:
            espace_ram.arreter_ram()
        print("Session purgée. À bientôt.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
