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

# Cf issue #563 (CWE-319). Port du TLS implicite : smtplib y ouvre directement
# une session chiffree (SMTP_SSL). Partout ailleurs le chiffrement passe par
# une negociation STARTTLS explicite.
SMTP_IMPLICIT_TLS_PORT = 465

# Message unique (log serveur + reponse du bouton "Tester l'envoi") pour que
# l'utilisateur sache quoi corriger, et qu'il sache que rien n'a ete transmis.
#
# Les TROIS sorties sont nommees, pas deux. L'utilisateur que ce refus casse est
# precisement celui pour qui les deux premieres echouent : un relais qui exige
# AUTH sans offrir TLS (petit MTA de NAS, relais loopback). Chez lui, "activez
# STARTTLS" leve SMTPNotSupportedError et rien n'ecoute en TLS implicite sur
# 465 ; la seule issue est de retirer les identifiants — c'est leur presence qui
# declenche le refus, cf. la garde 1. Un message qui ne la nomme pas transforme
# le garde-fou en impasse. Les libelles cites ("Utilisateur", "Mot de passe")
# sont ceux du formulaire Parametres > Notifications > Rapports email (SMTP).
CLEARTEXT_REFUSAL_MESSAGE = (
    "Envoi refuse : un mot de passe SMTP est configure mais la session ne serait pas "
    "chiffree. Activez STARTTLS, utilisez le port 465, ou — si votre relais n'exige pas "
    "d'authentification — videz les champs Utilisateur et Mot de passe. "
    "Le mot de passe n'a pas ete transmis."
)


class SmtpCleartextRefused(smtplib.SMTPException):
    """AUTH SMTP refuse faute de session chiffree (issue #563).

    Herite de SMTPException pour rejoindre le meme chemin d'erreur que les
    autres pannes SMTP : l'envoi retourne False, jamais un succes silencieux.
    """


def smtp_session_will_be_encrypted(port: Any, use_tls: Any) -> bool:
    """Vrai si la session SMTP sera chiffree AVANT le moindre AUTH.

    Cf issue #563. Deux chemins menent au chiffrement et deux seulement :
    le TLS implicite du port 465, ou un STARTTLS demande juste apres
    l'ouverture de la session. Demander STARTTLS ne peut pas retomber en
    clair sans qu'on le sache : `smtplib.SMTP.starttls()` leve
    `SMTPNotSupportedError` si le serveur ne l'annonce pas, et
    `ssl.create_default_context()` verifie chaine et hostname. Le seul trou
    etait donc bien le cas "pas de STARTTLS demande du tout".
    """
    try:
        port_i = int(port)
    except (TypeError, ValueError):
        port_i = -1
    return port_i == SMTP_IMPLICIT_TLS_PORT or bool(use_tls)


def _socket_is_encrypted(smtp: smtplib.SMTP) -> bool:
    """Vrai si la socket REELLEMENT etablie est une socket TLS.

    Constat sur l'objet vivant, pas sur les reglages : c'est ce qui rend le
    garde insensible a une derive future entre les drapeaux et le transport.
    `SMTP_SSL` comme `starttls()` remplacent tous deux `smtp.sock` par le
    retour de `SSLContext.wrap_socket`, donc une `ssl.SSLSocket`.
    """
    return isinstance(getattr(smtp, "sock", None), ssl.SSLSocket)


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

    # GARDE 1/2 (issue #563) — refus AVANT d'ouvrir la moindre socket.
    # `smtp.login()` n'est appele que si `user` ET `password` sont renseignes ;
    # on calque exactement cette condition pour ne refuser que les envois qui
    # transmettraient reellement un secret. Un relais sans authentification
    # continue de fonctionner en clair : le mot de passe est le secret, pas le
    # rapport de scan.
    #
    # Cas legitime que ce refus casse, assume : un relais qui exige AUTH sans
    # offrir TLS (petit MTA de NAS, meme en loopback). Aucune exemption n'est
    # prevue — une branche permissive sur un chemin qui transporte un secret,
    # c'est exactement le defaut qu'on corrige. Pour CE relais, activer STARTTLS
    # et passer en 465 echouent tous les deux ; la sortie qui aboutit est de
    # vider les identifiants, et CLEARTEXT_REFUSAL_MESSAGE la nomme.
    #
    # Le log ne reprend NI l'hote NI le port : le message dit deja quoi
    # corriger, la configuration est sous les yeux de l'utilisateur, et les
    # logs CineSort partent en piece jointe des demandes de support. Rien de la
    # configuration du compte mail n'a besoin d'y figurer.
    if user and password and not smtp_session_will_be_encrypted(port, use_tls):
        logger.error("[email] %s", CLEARTEXT_REFUSAL_MESSAGE)
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
        if port == SMTP_IMPLICIT_TLS_PORT:
            smtp = smtplib.SMTP_SSL(host, port, timeout=timeout_s, context=ssl_ctx)
        else:
            smtp = smtplib.SMTP(host, port, timeout=timeout_s)
        try:
            if port != SMTP_IMPLICIT_TLS_PORT and use_tls:
                smtp.starttls(context=ssl_ctx)
            if user and password:
                # GARDE 2/2 (issue #563) — on ne fait pas confiance aux
                # drapeaux, on interroge la socket reellement negociee. La
                # garde 1 raisonne sur la configuration ; celle-ci constate le
                # transport. Elle rattrape tout ce qui pourrait desynchroniser
                # les deux plus tard (nouveau port implicite, refactor du
                # calcul de `use_tls`, sous-classe de smtplib).
                if not _socket_is_encrypted(smtp):
                    logger.error("[email] %s", CLEARTEXT_REFUSAL_MESSAGE)
                    raise SmtpCleartextRefused(CLEARTEXT_REFUSAL_MESSAGE)
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
