"""Rapport par email — envoie un resume apres scan ou apply via SMTP stdlib.

L'envoi est non-bloquant (thread daemon) et ne doit jamais crasher le flow principal.
"""

from __future__ import annotations

import contextlib
import logging
import smtplib
import ssl
import threading
from datetime import datetime
from email.mime.text import MIMEText
from typing import Any, Dict

logger = logging.getLogger("cinesort.email")

# Timeout TCP de la session SMTP (connect + chaque commande). 30 s couvre les
# serveurs lents (NAS, instances cloud overcommitted) tout en restant en-deca
# du delai standard d'un thread daemon de notification (l'utilisateur ne doit
# pas voir l'app figee). Override possible via la settings "email_smtp_timeout_s".
_DEFAULT_SMTP_TIMEOUT_S = 30
_MIN_SMTP_TIMEOUT_S = 5
_MAX_SMTP_TIMEOUT_S = 120


def _resolve_smtp_timeout(settings: Dict[str, Any]) -> int:
    """Clamp la valeur settings dans [_MIN, _MAX]. Defaut si absent/invalide."""
    raw = settings.get("email_smtp_timeout_s")
    if raw is None:
        return _DEFAULT_SMTP_TIMEOUT_S
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_SMTP_TIMEOUT_S
    if value < _MIN_SMTP_TIMEOUT_S:
        return _MIN_SMTP_TIMEOUT_S
    if value > _MAX_SMTP_TIMEOUT_S:
        return _MAX_SMTP_TIMEOUT_S
    return value


def _resolve_smtp_port(settings: Dict[str, Any]) -> int:
    """Retourne le port SMTP avec fallback 587. Une valeur non-numerique
    (ex: ``"abc"`` saisi par l'utilisateur) retombe sur 587 au lieu de
    crasher silencieusement le thread daemon d'envoi.
    """
    raw = settings.get("email_smtp_port")
    if raw is None or raw == "":
        return 587
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning("[email] port SMTP invalide %r, fallback 587", raw)
        return 587


def _build_subject(event: str, data: Dict[str, Any]) -> str:
    """Construit le sujet de l'email selon l'evenement."""
    if event == "post_scan":
        rows = data.get("data", {}).get("rows", 0)
        return f"CineSort — Scan termine ({rows} film(s))"
    if event == "post_apply":
        renames = data.get("data", {}).get("renames", 0)
        return f"CineSort — Apply termine ({renames} renomme(s))"
    return f"CineSort — {event}"


def _build_body(event: str, data: Dict[str, Any]) -> str:
    """Construit le corps texte brut de l'email."""
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    run_id = data.get("run_id", "?")
    inner = data.get("data", {})
    lines = [
        f"Rapport CineSort — {now}",
        f"Evenement : {event}",
        f"Run : {run_id}",
        "",
    ]
    if event == "post_scan":
        lines.append(f"Films detectes : {inner.get('rows', 0)}")
        lines.append(f"Dossiers scannes : {inner.get('folders_scanned', 0)}")
        roots = inner.get("roots", [])
        if roots:
            lines.append(f"Roots : {', '.join(str(r) for r in roots)}")
    elif event == "post_apply":
        lines.append(f"Renommes : {inner.get('renames', 0)}")
        lines.append(f"Deplaces : {inner.get('moves', 0)}")
        lines.append(f"Erreurs : {inner.get('errors', 0)}")
    else:
        for k, v in inner.items():
            lines.append(f"{k} : {v}")
    lines.append("")
    lines.append("-- Envoye automatiquement par CineSort.")
    return "\n".join(lines)


def send_email_report(
    settings: Dict[str, Any],
    event: str,
    data: Dict[str, Any],
) -> bool:
    """Envoie un rapport email. Retourne True si succes, False sinon."""
    host = str(settings.get("email_smtp_host") or "").strip()
    port = _resolve_smtp_port(settings)
    user = str(settings.get("email_smtp_user") or "").strip()
    password = str(settings.get("email_smtp_password") or "")
    use_tls = bool(settings.get("email_smtp_tls", True))
    to_addr = str(settings.get("email_to") or "").strip()
    from_addr = user or "cinesort@localhost"

    if not host or not to_addr:
        logger.warning("[email] SMTP host ou destinataire manquant — email non envoye.")
        return False

    subject = _build_subject(event, data)
    body = _build_body(event, data)

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr

    timeout_s = _resolve_smtp_timeout(settings)
    try:
        # Cf issue #66 : SSL context strict avec verification hostname + chaine
        # certificats. Sans cela, smtplib accepte les certs auto-signes/invalides
        # et MITM LAN pourrait intercepter le password SMTP.
        ssl_ctx = ssl.create_default_context()
        if port == 465:
            smtp = smtplib.SMTP_SSL(host, port, timeout=timeout_s, context=ssl_ctx)
        else:
            smtp = smtplib.SMTP(host, port, timeout=timeout_s)
        try:
            if port != 465 and use_tls:
                smtp.starttls(context=ssl_ctx)
            if user and password:
                smtp.login(user, password)
            smtp.sendmail(from_addr, [to_addr], msg.as_string())
        finally:
            # Garantit quit() meme si starttls/login/sendmail leve : sinon la
            # socket TCP restait ouverte sur erreur d'auth et fuyait des
            # connexions vers le serveur SMTP a chaque retry.
            with contextlib.suppress(smtplib.SMTPException):
                smtp.quit()
        logger.info("[email] rapport envoye a %s (%s)", to_addr, event)
        return True
    except (smtplib.SMTPException, OSError, TimeoutError) as exc:
        logger.warning("[email] echec envoi a %s: %s", to_addr, exc)
        return False


def dispatch_email(
    settings: Dict[str, Any],
    event: str,
    data: Dict[str, Any],
) -> None:
    """Dispatch l'envoi d'email dans un thread daemon (non-bloquant)."""
    if not settings.get("email_enabled"):
        return
    if event == "post_scan" and not settings.get("email_on_scan", True):
        return
    if event == "post_apply" and not settings.get("email_on_apply", True):
        return
    t = threading.Thread(
        target=send_email_report,
        args=(settings, event, data),
        daemon=True,
        name=f"email-{event}",
    )
    t.start()
