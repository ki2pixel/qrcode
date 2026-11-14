#!/usr/bin/env python3
"""Harness PTY pour les tests loopback du coffre USB.

Répond aux invites interactives de init_usb_coffre.sh,
executer_sauvegarde_ram.sh et consulter_coffre_ro.sh avec des phrases
synthétiques, sans écho et sans dépendance externe.

Les secrets sont lus dans l'environnement :
  QR_LOOP_LUKS_PASS   phrase LUKS2 synthétique
  QR_LOOP_AGE_PASS    phrase age synthétique

Ils sont réservés aux tests loopback. Ne jamais utiliser de vraies phrases.
"""

from __future__ import annotations

import argparse
import os
import pty
import re
import select
import signal
import subprocess
import sys
import termios
import time
from pathlib import Path

PROFILES = {
    "init": [
        (r"Tape EFFACER pour continuer", "confirm", False),
        (r"Tape .+ pour confirmer", "device", False),
        (r"Tape le numéro de série exact", "serial", True),
        (r"Are you sure|Type 'yes' to confirm|capital letters", "yes", False),
        (r"Enter passphrase for", "luks", False),
        (r"Verify passphrase", "luks", False),
        (r"Enter passphrase for", "luks", False),
        (r"Enter passphrase", "age", False),
        (r"Confirm passphrase", "age", False),
        (r"note-la maintenant|Entrée pour continuer", "enter", False),
    ],
    "save": [
        (r"Enter passphrase for", "luks", False),
        (r"Enter passphrase", "age", False),
        (r"Confirm passphrase", "age", False),
        (r"note-la maintenant|Entrée pour continuer", "enter", False),
        (r"Continuer le transfert", "continue", True),
        (r"Supprimer ces anciennes capsules", "no", True),
    ],
    "consult": [
        (r"Enter passphrase for", "luks", False),
        (r"Détruire l'original", "no", True),
        (r"Appuie sur Entrée pour tout effacer", "enter", False),
    ],
}


def device_serial(device: str) -> str:
    try:
        result = subprocess.run(
            ["lsblk", "-dn", "-o", "SERIAL", device],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return ""
    return result.stdout.strip()


def response(kind: str, luks: str, age: str, device: str, serial: str) -> bytes:
    values = {
        "confirm": "EFFACER",
        "device": os.path.basename(device),
        "serial": serial,
        "yes": "YES",
        "luks": luks,
        "age": age,
        "enter": "",
        "continue": "o",
        "no": "n",
    }
    return (values[kind] + "\n").encode("utf-8")


def run(args: argparse.Namespace) -> int:
    luks = os.environ.get("QR_LOOP_LUKS_PASS", "")
    age = os.environ.get("QR_LOOP_AGE_PASS", "")
    if not luks or not age:
        print(
            "ERREUR : QR_LOOP_LUKS_PASS et QR_LOOP_AGE_PASS doivent être définis.",
            file=sys.stderr,
        )
        return 2

    queue = [
        (re.compile(pattern.encode("utf-8"), re.IGNORECASE), kind, optional)
        for pattern, kind, optional in PROFILES[args.profile]
    ]
    serial = device_serial(args.device)

    print(
        f"[harness] profil={args.profile} device={args.device} "
        f"timeout={args.timeout}s",
        file=sys.stderr,
        flush=True,
    )

    pid, fd = pty.fork()
    if pid == 0:
        env = os.environ.copy()
        env.update(
            {
                "LC_ALL": "C",
                "LANG": "C",
                "NO_COLOR": "1",
                "TERM": "dumb",
            }
        )
        try:
            os.execvpe(args.command[0], args.command, env)
        except OSError as exc:
            os.write(2, f"exec impossible : {exc}\n".encode("utf-8"))
            os._exit(127)

    try:
        attrs = termios.tcgetattr(fd)
        attrs[3] &= ~termios.ECHO
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
    except termios.error:
        pass

    buffer = b""
    deadline = time.monotonic() + args.timeout
    timed_out = False

    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            readable, _, _ = select.select([fd], [], [], min(remaining, 1.0))
            if not readable:
                continue
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break

            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
            buffer += chunk
            if len(buffer) > 16384:
                buffer = buffer[-16384:]

            while queue:
                matched = None
                for index, (pattern, kind, optional) in enumerate(queue):
                    match = pattern.search(buffer)
                    if match is not None:
                        matched = (index, kind, optional, match)
                        break
                if matched is None:
                    break

                index, kind, _optional, match = matched
                if kind == "enter" and args.hold_final > 0:
                    if args.ready_file:
                        try:
                            Path(args.ready_file).write_text(
                                "ready\n", encoding="utf-8"
                            )
                        except OSError as exc:
                            print(
                                f"[harness] témoin impossible : {exc}",
                                file=sys.stderr,
                            )
                    time.sleep(args.hold_final)
                os.write(fd, response(kind, luks, age, args.device, serial))
                queue.pop(index)
                buffer = buffer[match.end():]
    except KeyboardInterrupt:
        os.kill(pid, signal.SIGTERM)
        os.waitpid(pid, 0)
        return 130
    finally:
        try:
            os.close(fd)
        except OSError:
            pass

    if timed_out:
        os.kill(pid, signal.SIGTERM)
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
        print(
            f"[harness] TIMEOUT après {args.timeout}s ; invites restantes: "
            + ", ".join(
                step[0].pattern.decode("utf-8", errors="replace")
                for step in queue[:3]
            ),
            file=sys.stderr,
        )
        return 124

    _, status = os.waitpid(pid, 0)
    code = os.waitstatus_to_exitcode(status)
    unused = [
        step[0].pattern.decode("utf-8", errors="replace")
        for step in queue
        if not step[2]
    ]
    if unused:
        print(
            "[harness] invites obligatoires non rencontrées : "
            + ", ".join(unused),
            file=sys.stderr,
        )
    print(f"[harness] code de sortie={code}", file=sys.stderr)
    return code


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Harness PTY pour scripts de coffre loopback."
    )
    parser.add_argument("--profile", choices=sorted(PROFILES), required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument(
        "--hold-final",
        type=int,
        default=0,
        help="Délai avant d'envoyer Entrée sur une invite 'enter'",
    )
    parser.add_argument(
        "--ready-file",
        default=None,
        help="Fichier témoin créé avant le délai de --hold-final",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    if not re.fullmatch(r"/dev/loop[0-9]+", args.device):
        parser.error("--device doit être un périphérique /dev/loopN")
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        parser.error("commande absente après --")
    if args.timeout <= 0:
        parser.error("--timeout doit être strictement positif")
    if args.hold_final < 0:
        parser.error("--hold-final doit être positif ou nul")

    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
