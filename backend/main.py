import os
import json
import tempfile
import io
import csv
import secrets
from datetime import datetime, timedelta
from typing import Optional, List
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form, Response, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from groq import Groq

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

DATABASE_URL = "sqlite:///./akounta_togo.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# =====================================================================
# MODÈLE DE DONNÉES (MULTI-UTILISATEURS & ABONNEMENT SAAS)
# =====================================================================
class Trader(Base):
    __tablename__ = "traders"

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    pin_code = Column(String, nullable=False, default="1234")  # Code secret pour se connecter
    auth_token = Column(String, unique=True, index=True, nullable=True)
    credit_score = Column(Integer, default=300)
    badge = Column(String, default="Bronze")

    # Gestion de la Monétisation SaaS
    is_subscribed = Column(Boolean, default=True)  # Actif (ou en période d'essai)
    subscription_expires_at = Column(DateTime, nullable=True)
    subscription_plan = Column(String, default="ESSAI_GRATUIT")  # 'ESSAI_GRATUIT', 'MENSUEL', 'ANNUEL'

    transactions = relationship("Transaction", back_populates="trader")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    trader_id = Column(Integer, ForeignKey("traders.id"), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    type_transaction = Column(String, nullable=False)  # 'vente', 'achat', 'dette_client'
    produit = Column(String, nullable=False)
    quantite = Column(Integer, nullable=False)
    montant_total_xof = Column(Integer, nullable=False)
    client_nom = Column(String, nullable=True)
    status_antifraude = Column(String, nullable=False)
    score_impact = Column(Integer, nullable=False)
    note_vocale = Column(String, nullable=True)

    trader = relationship("Trader", back_populates="transactions")


Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_trader(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)) -> Trader:
    if not authorization:
        raise HTTPException(status_code=401, detail="Veuillez vous connecter avec votre numéro.")
    token = authorization.replace("Bearer ", "").strip()
    trader = db.query(Trader).filter(Trader.auth_token == token).first()
    if not trader:
        raise HTTPException(status_code=401, detail="Session expirée ou invalide. Reconnectez-vous.")
    
    # Vérification stricte de l'abonnement
    if trader.subscription_expires_at and trader.subscription_expires_at < datetime.utcnow():
        trader.is_subscribed = False
        db.commit()
        raise HTTPException(
            status_code=402, 
            detail="Votre abonnement Akounta Togo a expiré. Veuillez renouveler votre forfait (T-Money ou Moov Money) pour continuer."
        )
    return trader


# =====================================================================
# LOGIQUE MÉTIER & PRIX DU MARCHÉ DE LOMÉ
# =====================================================================
PRICE_GRID_LOME = {
    "riz": {"min": 18000, "max": 25000},
    "huile": {"min": 45000, "max": 65000},
    "pagne": {"min": 5000, "max": 35000},
    "mais": {"min": 600, "max": 1200},
    "maïs": {"min": 600, "max": 1200}
}


def evaluate_anti_fraud(produit: str, quantite: int, montant_total_xof: int) -> str:
    if quantite <= 0:
        return "SUSPECT"
    p = produit.lower().strip()
    prix_unitaire = montant_total_xof / quantite
    for item_key, bounds in PRICE_GRID_LOME.items():
        if item_key in p:
            if prix_unitaire > (bounds["max"] * 1.50):
                return "SUSPECT"
            break
    return "VALIDÉ"


def compute_score_impact(type_transaction: str, status_antifraude: str) -> int:
    if status_antifraude == "SUSPECT":
        return -50
    if type_transaction == "dette_client":
        return 15
    elif type_transaction == "vente":
        return 10
    return 0


def determine_badge(credit_score: int) -> str:
    if credit_score >= 750:
        return "Or"
    elif credit_score >= 500:
        return "Argent"
    return "Bronze"


def get_loan_amount(badge: str) -> int:
    if badge == "Or":
        return 100000
    elif badge == "Argent":
        return 25000
    return 0


# =====================================================================
# AGENT VOCAL & NLP (GROQ)
# =====================================================================
SYSTEM_PROMPT_AGENT_VOCAL = """Tu es l'agent comptable IA d'Akounta Togo pour les commerçants du marché de Lomé.
Le commerçant te parle oralement en français populaire ou en éwé/expressions togolaises.
Ton rôle est de tenir ses livres de comptes automatiquement.

Tu dois impérativement identifier :
1. Le type d'opération : "vente" (recette), "achat" (dépense pour le stock/charges) ou "dette_client" (remboursement ou prêt accordé)
2. Le nom du produit normalisé (ex: riz, huile, pagne, mais...)
3. La quantité (nombre entier, 1 par défaut)
4. Le montant total en XOF / FCFA (nombre entier)
5. Le nom du client si mentionné (ou null)
6. Un résumé comptable très court (ex: "Vente de 2 sacs de riz")

Réponds STRICTEMENT sous ce format JSON :
{
  "type_transaction": "vente" | "achat" | "dette_client",
  "produit": "nom normalisé",
  "quantite": int,
  "montant_total_xof": int,
  "client_nom": "nom ou null",
  "resume_ecriture": "description courte"
}
"""


def parse_vocal_transcription(transcription: str) -> dict:
    if not GROQ_API_KEY:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY non configurée.")
    client = Groq(api_key=GROQ_API_KEY)
    chat_completion = client.chat.completions.create(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_AGENT_VOCAL},
            {"role": "user", "content": transcription}
        ],
        model="llama-3.1-8b-instant",
        temperature=0.1,
        response_format={"type": "json_object"}
    )
    return json.loads(chat_completion.choices[0].message.content)


def transcribe_audio_file(audio_bytes: bytes, filename: str) -> str:
    if not GROQ_API_KEY:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY non configurée.")
    client = Groq(api_key=GROQ_API_KEY)
    with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{filename}") as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    try:
        with open(tmp_path, "rb") as file:
            transcription = client.audio.transcriptions.create(
                file=(tmp_path, file.read()),
                model="whisper-large-v3",
                language="fr",
                response_format="text"
            )
        return transcription.strip()
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# =====================================================================
# APPLICATION & ROUTES FASTAPI
# =====================================================================
app = FastAPI(title="Akounta Togo - Plateforme SaaS Multi-utilisateurs", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AuthLogin(BaseModel):
    phone_number: str
    pin_code: str
    name: Optional[str] = "Commerçant Lomé"


class SubscribeInput(BaseModel):
    plan: str  # 'MENSUEL' (ex: 2 000 FCFA), 'ANNUEL' (ex: 20 000 FCFA)
    payment_method: str  # 'TMONEY', 'MOOV_MONEY', 'CARTE'
    phone_payment: str


@app.post("/auth/login")
def login_or_register(payload: AuthLogin, db: Session = Depends(get_db)):
    """Connexion ou Inscription en 1 clic par numéro de téléphone togolais."""
    phone = payload.phone_number.strip().replace(" ", "")
    trader = db.query(Trader).filter(Trader.phone_number == phone).first()
    
    if not trader:
        # Création d'un nouveau compte avec 14 jours d'essai gratuit
        trial_end = datetime.utcnow() + timedelta(days=14)
        token = secrets.token_hex(24)
        trader = Trader(
            phone_number=phone,
            name=payload.name or "Nouveau Commerçant",
            pin_code=payload.pin_code,
            auth_token=token,
            credit_score=300,
            badge="Bronze",
            is_subscribed=True,
            subscription_expires_at=trial_end,
            subscription_plan="ESSAI_14_JOURS"
        )
        db.add(trader)
        db.commit()
        db.refresh(trader)
    else:
        # Vérification du code PIN
        if trader.pin_code != payload.pin_code:
            raise HTTPException(status_code=400, detail="Code secret incorrect.")
        trader.auth_token = secrets.token_hex(24)
        db.commit()

    return {
        "token": trader.auth_token,
        "trader": {
            "id": trader.id,
            "name": trader.name,
            "phone_number": trader.phone_number,
            "credit_score": trader.credit_score,
            "badge": trader.badge,
            "eligible_loan_xof": get_loan_amount(trader.badge),
            "is_subscribed": trader.is_subscribed,
            "subscription_plan": trader.subscription_plan,
            "subscription_expires_at": trader.subscription_expires_at.strftime("%d/%m/%Y") if trader.subscription_expires_at else "Illimité"
        }
    }


@app.get("/traders/me")
def get_current_profile(trader: Trader = Depends(get_current_trader)):
    """Profil personnel de l'utilisateur connecté."""
    return {
        "id": trader.id,
        "name": trader.name,
        "phone_number": trader.phone_number,
        "credit_score": trader.credit_score,
        "badge": trader.badge,
        "eligible_loan_xof": get_loan_amount(trader.badge),
        "is_subscribed": trader.is_subscribed,
        "subscription_plan": trader.subscription_plan,
        "subscription_expires_at": trader.subscription_expires_at.strftime("%d/%m/%Y") if trader.subscription_expires_at else "Illimité"
    }


@app.post("/subscription/subscribe")
def activate_subscription(payload: SubscribeInput, trader: Trader = Depends(get_current_trader), db: Session = Depends(get_db)):
    """Active ou prolonge l'abonnement du commerçant (Simulation T-Money / Moov Money)."""
    days = 30 if payload.plan == "MENSUEL" else 365
    current_expiry = trader.subscription_expires_at or datetime.utcnow()
    start_date = max(datetime.utcnow(), current_expiry)
    
    trader.subscription_expires_at = start_date + timedelta(days=days)
    trader.is_subscribed = True
    trader.subscription_plan = payload.plan
    db.commit()

    return {
        "message": f"Félicitations ! Votre abonnement {payload.plan} via {payload.payment_method} est actif.",
        "expires_at": trader.subscription_expires_at.strftime("%d/%m/%Y")
    }


@app.post("/transactions/voice-audio")
async def add_voice_audio_transaction(
    file: UploadFile = File(...),
    trader: Trader = Depends(get_current_trader),
    db: Session = Depends(get_db)
):
    """Enregistre l'écriture comptable par la voix dans le compte privé du commerçant."""
    audio_content = await file.read()
    transcription = transcribe_audio_file(audio_content, file.filename or "audio.webm")
    parsed = parse_vocal_transcription(transcription)

    type_tx = parsed.get("type_transaction", "vente")
    produit = parsed.get("produit", "inconnu")
    quantite = int(parsed.get("quantite", 1))
    montant = int(parsed.get("montant_total_xof", 0))
    client_nom = parsed.get("client_nom")
    note = parsed.get("resume_ecriture") or transcription

    status_anti = evaluate_anti_fraud(produit, quantite, montant)
    impact = compute_score_impact(type_tx, status_anti)

    new_score = max(0, min(1000, trader.credit_score + impact))
    trader.credit_score = new_score
    trader.badge = determine_badge(new_score)

    tx = Transaction(
        trader_id=trader.id,
        type_transaction=type_tx,
        produit=produit,
        quantite=quantite,
        montant_total_xof=montant,
        client_nom=client_nom,
        status_antifraude=status_anti,
        score_impact=impact,
        note_vocale=note
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)

    return {
        "id": tx.id,
        "type_transaction": tx.type_transaction,
        "produit": tx.produit,
        "quantite": tx.quantite,
        "montant_total_xof": tx.montant_total_xof,
        "status_antifraude": tx.status_antifraude,
        "score_impact": tx.score_impact,
        "note_vocale": tx.note_vocale
    }


@app.get("/traders/me/accounting-summary")
def get_my_accounting_summary(trader: Trader = Depends(get_current_trader), db: Session = Depends(get_db)):
    txs = db.query(Transaction).filter(Transaction.trader_id == trader.id).all()
    total_ventes = sum(t.montant_total_xof for t in txs if t.type_transaction == "vente")
    total_achats = sum(t.montant_total_xof for t in txs if t.type_transaction == "achat")
    total_dettes = sum(t.montant_total_xof for t in txs if t.type_transaction == "dette_client")

    return {
        "total_ventes": total_ventes,
        "total_achats": total_achats,
        "benefice_net": total_ventes - total_achats,
        "total_dettes": total_dettes,
        "nb_transactions": len(txs),
        "dernier_score": trader.credit_score,
        "badge": trader.badge
    }


@app.get("/traders/me/transactions")
def get_my_transactions(trader: Trader = Depends(get_current_trader), db: Session = Depends(get_db)):
    return db.query(Transaction).filter(Transaction.trader_id == trader.id).order_by(Transaction.id.desc()).all()


@app.get("/traders/me/export-journal")
def export_my_journal(trader: Trader = Depends(get_current_trader), db: Session = Depends(get_db)):
    txs = db.query(Transaction).filter(Transaction.trader_id == trader.id).order_by(Transaction.timestamp.asc()).all()
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(["ID", "Date", "Type", "Produit", "Quantite", "Achats (Sorties)", "Ventes (Entrees)", "Dettes", "Tiers", "Anti-Fraude", "Resume IA"])
    for t in txs:
        writer.writerow([
            t.id,
            t.timestamp.strftime("%Y-%m-%d %H:%M"),
            t.type_transaction.upper(),
            t.produit,
            t.quantite,
            t.montant_total_xof if t.type_transaction == "achat" else 0,
            t.montant_total_xof if t.type_transaction == "vente" else 0,
            t.montant_total_xof if t.type_transaction == "dette_client" else 0,
            t.client_nom or "-",
            t.status_antifraude,
            t.note_vocale or ""
        ])
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=grand_livre_{trader.phone_number}.csv"}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
