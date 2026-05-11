# Politique de Sécurité

## Versions supportées

Les correctifs de sécurité sont appliqués sur la dernière version stable.

| Version | Supportée |
|---------|-----------|
| 7.6.x   | ✅ |
| < 7.6   | ❌ |

## Signaler une vulnérabilité

Si tu découvres une vulnérabilité de sécurité dans CineSort, **NE PAS ouvrir d'issue
publique**. Utilise plutôt les [GitHub Security Advisories privées](https://github.com/PLACEHOLDER/cinesort/security/advisories/new).

Tu recevras un accusé de réception sous 48h. Les vulnérabilités confirmées seront
corrigées et publiées dans un délai raisonnable selon la sévérité (typiquement 7-30 jours).

## Surface d'attaque

CineSort est une app desktop locale Windows. Les surfaces sensibles :

- **Dashboard distant** (port 8642 par défaut) — protégé par token Bearer + rate limiting.
  Si exposé sur internet (à éviter), utiliser HTTPS + un token long ≥ 32 chars.
- **Stockage des clés API** (TMDb, Jellyfin, Plex, Radarr) — chiffré via DPAPI Windows.
- **Logs** — secrets scrubés avant écriture (`log_scrubber.py`).
- **Opérations destructives** — toujours via journal write-ahead + confirmation utilisateur.

## Hors scope

- Vulnérabilités dépendant d'un attaquant ayant déjà un accès local au compte Windows
- Bypass des restrictions DRM ou des protections antivirus

Merci !
