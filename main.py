# =====================================================================
# PROJET: Akounta Togo (MVP)
# Architecture: FastAPI + SQLite (SQLAlchemy) + Groq (llama-3.1-8b-instant)
# =====================================================================

import os
import json
from datetime import datetime
from typing import Optional, List
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from groq import Groq

# Charger les variables d'environnement
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# =====================================================================
# 1. BASE DE DONNÉES (SQLite via SQLAlchemy)
# =====================================================================
DATABASE_URL = "sqlite:///./akounta_togo.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Trader(Base):
    __tablename__ = "traders"

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    credit_score = Column(Integer, default=300)
    badge = Column(String, default="Bronze")

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
    status_antifraude = Column(String, nullable=False)  # 'VALIDÉ' ou 'SUSPECT'
    score_impact = Column(Integer, nullable=False)

    trader = relationship("Trader", back_populates="transactions")


# Création automatique des tables
Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =====================================================================
# 2. LOGIQUE MÉTIER & ALGORITHMES (Anti-fraude & Scoring)
# =====================================================================

# Grille de référence des prix du marché de Lomé (prix min, max en XOF)
PRICE_GRID_LOME = {
    "riz": {"min": 18000, "max": 25000},      # Sac 50kg
    "huile": {"min": 45000, "max": 65000},    # Bidon 5L
    "pagne": {"min": 5000, "max": 35000},     # Pièce
    "mais": {"min": 600, "max": 1200},        # Bol
    "maïs": {"min": 600, "max": 1200}
}


def evaluate_anti_fraud(produit: str, quantite: int, montant_total_xof: int) -> str:
    """
    Vérifie si le prix unitaire dépasse de plus de 50% le prix maximum référencé.
    """
    if quantite <= 0:
        return "SUSPECT"

    produit_clean = produit.lower().strip()
    prix_unitaire = montant_total_xof / quantite

    ref = None
    for item_key, bounds in PRICE_GRID_LOME.items():
        if item_key in produit_clean:
            ref = bounds
            break

    if ref:
        max_autorise = ref["max"] * 1.50  # Dépassement > 50% du prix max
        if prix_unitaire > max_autorise:
            return "SUSPECT"

    return "VALIDÉ"


def compute_score_impact(type_transaction: str, status_antifraude: str) -> int:
    """
    Calcul des points:
    - Fraude détectée : -50 points
    - Remboursement dette validé : +15 points
    - Vente valide : +10 points
    """
    if status_antifraude == "SUSPECT":
        return -50

    if type_transaction == "dette_client":
        return 15
    elif type_transaction == "vente":
        return 10
    return 0


def determine_badge(credit_score: int) -> str:
    """
    Attribution du badge selon les paliers de points:
    - Bronze : 0 à 490 pts (Non éligible au crédit)
    - Argent : 500 à 740 pts (Micro-prêt de 25 000 FCFA)
    - Or : 750 à 1000 pts (Prêt de croissance de 100 000 FCFA)
    """
    if credit_score >= 750:
        return "Or"
    elif credit_score >= 500:
        return "Argent"
    return "Bronze"


# =====================================================================
# 3. INTÉGRATION AGENT VOCAL NLP (GROQ LLAMA-3.1-8B-INSTANT)
# =====================================================================

SYSTEM_PROMPT_AGENT_VOCAL = """Tu es un assistant comptable pour les commerçants du marché de Lomé au Togo (Akounta Togo).
Tu reçois une transcription vocale en français populaire ou expressions locales togolaises.
Ton rôle est d'extraire les informations comptables et de renvoyer STRICTEMENT un JSON valide, sans balises de code ni texte explicatif.

Structure JSON requise :
{
  "type_transaction": "vente" | "achat" | "dette_client",
  "produit": "nom du produit normalisé (ex: riz, huile, pagne, mais...)",
  "quantite": int,
  "montant_total_xof": int,
  "client_nom": "nom du client ou null"
}

Si la quantité n'est pas précisée, assigne 1 par défaut.
Extrais uniquement les valeurs numériques entières pour le montant et la quantité.
"""


def parse_vocal_transcription(transcription: str) -> dict:
    if not GROQ_API_KEY:
        raise HTTPException(status_code=500, detail="Clé GROQ_API_KEY non configurée.")

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

    response_text = chat_completion.choices[0].message.content
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Échec du décodage JSON fourni par le modèle Groq.")


# =====================================================================
# 4. SCHÉMAS D'ENTRÉE / SORTIE (PYDANTIC)
# =====================================================================

class TraderCreate(BaseModel):
    phone_number: str
    name: str


class TraderResponse(BaseModel):
    id: int
    phone_number: str
    name: str
    credit_score: int
    badge: str

    class Config:
        from_attributes = True


class VoiceInput(BaseModel):
    trader_id: int
    transcription: str


class ManualTransactionInput(BaseModel):
    trader_id: int
    type_transaction: str
    produit: str
    quantite: int = Field(gt=0)
    montant_total_xof: int = Field(ge=0)
    client_nom: Optional[str] = None


class TransactionResponse(BaseModel):
    id: int
    trader_id: int
    timestamp: datetime
    type_transaction: str
    produit: str
    quantite: int
    montant_total_xof: int
    client_nom: Optional[str]
    status_antifraude: str
    score_impact: int

    class Config:
        from_attributes = True


# =====================================================================
# 5. APPLICATION FASTAPI ET ENDPOINTS
# =====================================================================

app = FastAPI(
    title="Akounta Togo API",
    description="Backend MVP pour commerçants du marché de Lomé (FastAPI + Groq)",
    version="1.0.0"
)


@app.post("/traders/", response_model=TraderResponse, status_code=201)
def create_trader(trader_in: TraderCreate, db: Session = Depends(get_db)):
    """Crée un commerçant avec un score initial de 300 et badge Bronze."""
    existing = db.query(Trader).filter(Trader.phone_number == trader_in.phone_number).first()
    if existing:
        raise HTTPException(status_code=400, detail="Numéro de téléphone déjà enregistré.")

    trader = Trader(
        phone_number=trader_in.phone_number,
        name=trader_in.name,
        credit_score=300,
        badge="Bronze"
    )
    db.add(trader)
    db.commit()
    db.refresh(trader)
    return trader


@app.get("/traders/{trader_id}", response_model=TraderResponse)
def get_trader(trader_id: int, db: Session = Depends(get_db)):
    """Récupère le profil, le score de crédit et le badge d'un commerçant."""
    trader = db.query(Trader).filter(Trader.id == trader_id).first()
    if not trader:
        raise HTTPException(status_code=404, detail="Commerçant introuvable.")
    return trader


def record_transaction(
    trader_id: int,
    type_transaction: str,
    produit: str,
    quantite: int,
    montant_total_xof: int,
    client_nom: Optional[str],
    db: Session
) -> Transaction:
    trader = db.query(Trader).filter(Trader.id == trader_id).first()
    if not trader:
        raise HTTPException(status_code=404, detail="Commerçant introuvable.")

    # 1. Évaluation Anti-Fraude
    status_antifraude = evaluate_anti_fraud(produit, quantite, montant_total_xof)

    # 2. Calcul d'impact sur le Score
    impact = compute_score_impact(type_transaction, status_antifraude)

    # 3. Mise à jour dynamique du score (borné entre 0 et 1000)
    new_score = max(0, min(1000, trader.credit_score + impact))
    trader.credit_score = new_score
    trader.badge = determine_badge(new_score)

    # 4. Sauvegarde de la transaction
    transaction = Transaction(
        trader_id=trader.id,
        type_transaction=type_transaction,
        produit=produit,
        quantite=quantite,
        montant_total_xof=montant_total_xof,
        client_nom=client_nom,
        status_antifraude=status_antifraude,
        score_impact=impact
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    db.refresh(trader)

    return transaction


@app.post("/transactions/manual", response_model=TransactionResponse)
def add_manual_transaction(payload: ManualTransactionInput, db: Session = Depends(get_db)):
    """Enregistre directement une transaction saisie manuellement."""
    return record_transaction(
        trader_id=payload.trader_id,
        type_transaction=payload.type_transaction,
        produit=payload.produit,
        quantite=payload.quantite,
        montant_total_xof=payload.montant_total_xof,
        client_nom=payload.client_nom,
        db=db
    )


@app.post("/transactions/voice", response_model=TransactionResponse)
def add_voice_transaction(payload: VoiceInput, db: Session = Depends(get_db)):
    """
    Extrait les paramètres via Groq (llama-3.1-8b-instant) depuis la transcription vocale
    puis applique l'anti-fraude et le credit scoring.
    """
    parsed_data = parse_vocal_transcription(payload.transcription)

    return record_transaction(
        trader_id=payload.trader_id,
        type_transaction=parsed_data.get("type_transaction", "vente"),
        produit=parsed_data.get("produit", "inconnu"),
        quantite=int(parsed_data.get("quantite", 1)),
        montant_total_xof=int(parsed_data.get("montant_total_xof", 0)),
        client_nom=parsed_data.get("client_nom"),
        db=db
    )


@app.get("/traders/{trader_id}/transactions", response_model=List[TransactionResponse])
def get_trader_transactions(trader_id: int, db: Session = Depends(get_db)):
    """Historique des transactions d'un commerçant."""
    return db.query(Transaction).filter(Transaction.trader_id == trader_id).all()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
