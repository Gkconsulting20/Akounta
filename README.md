# Akounta Togo (Version Corrigée Cloudflare)

Ce dépôt contient le code complet prêt pour Cloudflare et Render.

### Changements apportés pour corriger l'erreur Cloudflare :
1. Suppression de `_redirects` qui causait l'erreur `Infinite loop detected (code: 100324)`.
2. Ajout de `wrangler.jsonc` moderne avec la directive `assets.directory: "frontend"`.

### Déploiement :
1. Déposez ce contenu sur votre GitHub (`git add .`, `git commit -m "fix cloudflare"`, `git push origin main`).
2. Cloudflare déploiera automatiquement sans erreur.
