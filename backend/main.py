import os
import json
import tempfile
from datetime import datetime
from typing import Optional, List
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from groq import Groq

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

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


Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


PRICE_GRID_LOME = {
    "riz": {"min": 18000, "max": 25000},      # Sac 50kg
    "huile": {"min": 45000, "max": 65000},    # Bidon 5L
    "pagne": {"min": 5000, "max": 35000},     # Pièce
    "mais": {"min": 600, "max": 1200},        # Bol
    "maïs": {"min": 600, "max": 1200}
}


def evaluate_anti_fraud(produit: str, quantite: int, montant_total_xof: int) -> str:
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
        max_autorise = ref["max"] * 1.50
        if prix_unitaire > max_autorise:
            return "SUSPECT"

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


SYSTEM_PROMPT_AGENT_VOCAL = """Tu es un assistant comptable pour les commerçants du marché de Lomé au Togo (Akounta Togo).
Tu reçois une transcription vocale en français populaire ou expressions locales togolaises (mélange de français et termes éwé).
Extrais les informations comptables sous forme de JSON strict:
{
  "type_transaction": "vente" | "achat" | "dette_client",
  "produit": "nom du produit normalisé (ex: riz, huile, pagne, mais...)",
  "quantite": int,
  "montant_total_xof": int,
  "client_nom": "nom du client ou null"
}
Si la quantité n'est pas précisée, assigne 1 par défaut.
Renvoie uniquement le JSON pur sans texte ni explications.
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


class TraderCreate(BaseModel):
    phone_number: str
    name: str


class TraderResponse(BaseModel):
    id: int
    phone_number: str
    name: str
    credit_score: int
    badge: str
    eligible_loan_xof: int

    class Config:
        from_attributes = True


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


app = FastAPI(title="Akounta Togo API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_loan_amount(badge: str) -> int:
    if badge == "Or":
        return 100000
    elif badge == "Argent":
        return 25000
    return 0


def format_trader_response(trader: Trader) -> dict:
    return {
        "id": trader.id,
        "phone_number": trader.phone_number,
        "name": trader.name,
        "credit_score": trader.credit_score,
        "badge": trader.badge,
        "eligible_loan_xof": get_loan_amount(trader.badge)
    }


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

    status_antifraude = evaluate_anti_fraud(produit, quantite, montant_total_xof)
    impact = compute_score_impact(type_transaction, status_antifraude)

    new_score = max(0, min(1000, trader.credit_score + impact))
    trader.credit_score = new_score
    trader.badge = determine_badge(new_score)

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


@app.post("/traders/", response_model=TraderResponse, status_code=201)
def create_trader(trader_in: TraderCreate, db: Session = Depends(get_db)):
    existing = db.query(Trader).filter(Trader.phone_number == trader_in.phone_number).first()
    if existing:
        return format_trader_response(existing)

    trader = Trader(phone_number=trader_in.phone_number, name=trader_in.name, credit_score=300, badge="Bronze")
    db.add(trader)
    db.commit()
    db.refresh(trader)
    return format_trader_response(trader)


@app.get("/traders/{trader_id}", response_model=TraderResponse)
def get_trader(trader_id: int, db: Session = Depends(get_db)):
    trader = db.query(Trader).filter(Trader.id == trader_id).first()
    if not trader:
        raise HTTPException(status_code=404, detail="Commerçant introuvable.")
    return format_trader_response(trader)


@app.post("/transactions/manual", response_model=TransactionResponse)
def add_manual_transaction(payload: ManualTransactionInput, db: Session = Depends(get_db)):
    return record_transaction(
        trader_id=payload.trader_id,
        type_transaction=payload.type_transaction,
        produit=payload.produit,
        quantite=payload.quantite,
        montant_total_xof=payload.montant_total_xof,
        client_nom=payload.client_nom,
        db=db
    )


@app.post("/transactions/voice-audio", response_model=TransactionResponse)
async def add_voice_audio_transaction(
    trader_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    audio_content = await file.read()
    transcription = transcribe_audio_file(audio_content, file.filename or "audio.webm")
    parsed = parse_vocal_transcription(transcription)

    return record_transaction(
        trader_id=trader_id,
        type_transaction=parsed.get("type_transaction", "vente"),
        produit=parsed.get("produit", "inconnu"),
        quantite=int(parsed.get("quantite", 1)),
        montant_total_xof=int(parsed.get("montant_total_xof", 0)),
        client_nom=parsed.get("client_nom"),
        db=db
    )


@app.get("/traders/{trader_id}/transactions", response_model=List[TransactionResponse])
def get_transactions(trader_id: int, db: Session = Depends(get_db)):
    return db.query(Transaction).filter(Transaction.trader_id == trader_id).order_by(Transaction.id.desc()).all()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
