"""Registre en mémoire des tâches et sessions, avec expiration."""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

from web import config
from web import espace_ram


class Registre:
    def __init__(self) -> None:
        self._verrou = threading.RLock()
        self._jobs: dict[str, Any] = {}
        self._consultations: dict[str, Any] = {}
        self._executeur = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="qr-generation"
        )
        self._arret = threading.Event()
        self._thread_nettoyage: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Génération
    # ------------------------------------------------------------------
    def ajouter_job(self, job: Any) -> None:
        with self._verrou:
            for identifiant, ancien in list(self._jobs.items()):
                if getattr(ancien, "etat", "") not in {"attente", "en_cours"}:
                    self._jobs.pop(identifiant, None)
                    try:
                        ancien.detruire()
                    except Exception:
                        pass
            self._jobs[job.id] = job

    def obtenir_job(self, identifiant: str) -> Any | None:
        with self._verrou:
            job = self._jobs.get(identifiant)
        if job is not None:
            job.derniere_activite = time.time()
        return job

    def lister_jobs(self) -> list[Any]:
        with self._verrou:
            return list(self._jobs.values())

    def supprimer_job(self, identifiant: str) -> bool:
        with self._verrou:
            job = self._jobs.pop(identifiant, None)
        if job is None:
            return False
        try:
            job.annuler()
        except Exception:
            pass
        try:
            job.detruire()
        except Exception:
            pass
        return True

    def generation_active(self) -> bool:
        with self._verrou:
            return any(
                getattr(job, "etat", "") in {"attente", "en_cours"}
                for job in self._jobs.values()
            )

    def soumettre(self, fonction: Callable[..., Any], *args: Any) -> Future:
        return self._executeur.submit(fonction, *args)

    # ------------------------------------------------------------------
    # Consultation
    # ------------------------------------------------------------------
    def ajouter_consultation(self, session: Any) -> None:
        with self._verrou:
            anciennes = sorted(
                self._consultations.values(),
                key=lambda s: getattr(s, "derniere_activite", 0),
            )
            while len(anciennes) >= 3:
                vieille = anciennes.pop(0)
                self._consultations.pop(vieille.id, None)
                try:
                    vieille.detruire()
                except Exception:
                    pass
            self._consultations[session.id] = session

    def obtenir_consultation(self, identifiant: str) -> Any | None:
        with self._verrou:
            session = self._consultations.get(identifiant)
        if session is not None:
            session.derniere_activite = time.time()
        return session

    def lister_consultations(self) -> list[Any]:
        with self._verrou:
            return list(self._consultations.values())

    def supprimer_consultation(self, identifiant: str) -> bool:
        with self._verrou:
            session = self._consultations.pop(identifiant, None)
        if session is None:
            return False
        try:
            session.detruire()
        except Exception:
            pass
        return True

    # ------------------------------------------------------------------
    # Nettoyage
    # ------------------------------------------------------------------
    def demarrer_nettoyage(self) -> None:
        if self._thread_nettoyage is not None:
            return
        self._thread_nettoyage = threading.Thread(
            target=self._boucle_nettoyage,
            name="qr-nettoyage",
            daemon=True,
        )
        self._thread_nettoyage.start()

    def _boucle_nettoyage(self) -> None:
        while not self._arret.wait(config.INTERVALLE_NETTOYAGE):
            self.purger_expires()

    def purger_expires(self) -> None:
        maintenant = time.time()
        jobs_expires: list[Any] = []
        consultations_expirees: list[Any] = []
        with self._verrou:
            for identifiant, job in list(self._jobs.items()):
                etat = getattr(job, "etat", "")
                if etat in {"attente", "en_cours"}:
                    continue
                if maintenant - getattr(job, "derniere_activite", 0) > config.TTL_SECONDES:
                    jobs_expires.append(self._jobs.pop(identifiant))
            for identifiant, session in list(self._consultations.items()):
                if (
                    maintenant - getattr(session, "derniere_activite", 0)
                    > config.TTL_SECONDES
                ):
                    consultations_expirees.append(self._consultations.pop(identifiant))
        for job in jobs_expires:
            try:
                job.detruire()
            except Exception:
                pass
        for session in consultations_expirees:
            try:
                session.detruire()
            except Exception:
                pass

    def purger_tout(self) -> dict[str, int]:
        with self._verrou:
            jobs = list(self._jobs.values())
            consultations = list(self._consultations.values())
            self._jobs.clear()
            self._consultations.clear()
        for job in jobs:
            try:
                job.annuler()
            except Exception:
                pass
        for job in jobs:
            try:
                job.detruire()
            except Exception:
                pass
        for session in consultations:
            try:
                session.detruire()
            except Exception:
                pass
        espace_ram.purger_racine()
        return {"generations": len(jobs), "consultations": len(consultations)}

    def arreter(self) -> None:
        self._arret.set()
        self.purger_tout()
        self._executeur.shutdown(wait=False, cancel_futures=True)
        if self._thread_nettoyage is not None:
            self._thread_nettoyage.join(timeout=2)


REGISTRE = Registre()
