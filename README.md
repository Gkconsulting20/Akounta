# Akounta Togo (MVP)

Projet de comptabilité vocale et notation de micro-crédit pour les commerçants du marché de Lomé au Togo.

## Structure
- `/backend` : API FastAPI, SQLite, moteur Anti-fraude Lomé, Groq (Whisper + Llama 3.1)
- `/frontend` : Application mobile Web / PWA prête pour Cloudflare Pages
- `wrangler.toml` : Fichier de configuration Cloudflare

## Déploiement

### 1. GitHub
```bash
git init
git add .
git commit -m "Initial commit Akounta Togo"
git branch -M main
git remote add origin <VOTRE_REPO_GITHUB>
git push -u origin main
```

### 2. Frontend sur Cloudflare Pages
- Connecter le repository GitHub à Cloudflare Pages
- Répertoire racine : `frontend`
- Répertoire de sortie : `.`

### 3. Backend (FastAPI + Groq)
- Déployer sur Replit, Render, Fly.io ou Docker
- Ajouter la variable : `GROQ_API_KEY`
- Renseigner l'URL obtenue dans `frontend/app.js`
