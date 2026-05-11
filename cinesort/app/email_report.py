"""Rapport par email — envoie un resume apres scan ou apply via SMTP stdlib.

L'envoi est non-bloquant (thread daemon) et ne doit jamais crasher le flow principal.
"""

from __future__ import annotations

import logging
import smtplib
import threading
from datetime import datetime
from email.mime.text import MIMEText
from typing import Any, Dict

logger = logging.getLogger("cinesort.email")


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
    port = int(settings.get("email_smtp_port") or 587)
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

    try:
        if port == 465:
            smtp = smtplib.SMTP_SSL(host, port, timeout=15)
        else:
            smtp = smtplib.SMTP(host, port, timeout=15)
            if use_tls:
                smtp.starttls()
        if user and password:
            smtp.login(user, password)
        smtp.sendmail(from_addr, [to_addr], msg.as_string())
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
