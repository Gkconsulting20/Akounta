const API_BASE_URL = window.location.hostname === 'localhost' 
  ? 'http://localhost:8000' 
  : https://akounta-backend.onrender.com

let currentTraderId = 1;
let mediaRecorder;
let audioChunks = [];

async function initTrader() {
  try {
    const res = await fetch(`${API_BASE_URL}/traders/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phone_number: '+22890001122', name: 'Afiya Marché Assigamé' })
    });
    const trader = await res.json();
    currentTraderId = trader.id;
    updateTraderUI(trader);
    loadTransactions();
  } catch (err) {
    console.error("Erreur d'initialisation :", err);
  }
}

function updateTraderUI(trader) {
  document.getElementById('trader-name').innerText = `${trader.name} (${trader.phone_number})`;
  document.getElementById('score-val').innerHTML = `${trader.credit_score} <span class="text-xs font-normal text-slate-400">/ 1000 pts</span>`;
  document.getElementById('score-bar').style.width = `${Math.min(100, (trader.credit_score / 1000) * 100)}%`;
  
  const badgeEl = document.getElementById('badge-pill');
  badgeEl.innerText = trader.badge;
  if (trader.badge === 'Or') {
    badgeEl.className = 'px-3 py-1 rounded-full text-xs font-bold bg-yellow-500 text-slate-900';
  } else if (trader.badge === 'Argent') {
    badgeEl.className = 'px-3 py-1 rounded-full text-xs font-bold bg-slate-300 text-slate-900';
  } else {
    badgeEl.className = 'px-3 py-1 rounded-full text-xs font-bold bg-amber-800 text-amber-200';
  }

  document.getElementById('loan-val').innerText = `${trader.eligible_loan_xof.toLocaleString()} FCFA`;
}

async function loadTransactions() {
  try {
    const res = await fetch(`${API_BASE_URL}/traders/${currentTraderId}/transactions`);
    const list = await res.json();
    const container = document.getElementById('transaction-list');
    
    if (list.length === 0) {
      container.innerHTML = '<p class="text-slate-500 text-center py-4">Aucune transaction.</p>';
      return;
    }

    container.innerHTML = list.map(tx => `
      <div class="flex justify-between items-center bg-slate-700/50 p-2.5 rounded-xl border border-slate-700">
        <div>
          <div class="font-bold uppercase text-[11px] text-amber-300">${tx.type_transaction} - ${tx.produit} (x${tx.quantite})</div>
          <div class="text-[10px] text-slate-400">${new Date(tx.timestamp).toLocaleTimeString()} ${tx.client_nom ? '• Client: ' + tx.client_nom : ''}</div>
        </div>
        <div class="text-right">
          <div class="font-bold">${tx.montant_total_xof.toLocaleString()} XOF</div>
          <span class="text-[9px] px-1.5 py-0.5 rounded font-bold ${tx.status_antifraude === 'VALIDÉ' ? 'bg-emerald-900 text-emerald-300' : 'bg-rose-900 text-rose-300'}">
            ${tx.status_antifraude} (${tx.score_impact >= 0 ? '+' : ''}${tx.score_impact})
          </span>
        </div>
      </div>
    `).join('');
  } catch (err) {
    console.error(err);
  }
}

const recordBtn = document.getElementById('record-btn');
const statusText = document.getElementById('record-status');
const alertBox = document.getElementById('fraud-alert');

recordBtn.addEventListener('click', async () => {
  if (mediaRecorder && mediaRecorder.state === "recording") {
    mediaRecorder.stop();
    recordBtn.classList.remove('bg-rose-600', 'animate-pulse');
    recordBtn.classList.add('bg-amber-500');
    statusText.innerText = "Traitement IA par Groq...";
  } else {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioChunks = [];
      mediaRecorder = new MediaRecorder(stream);
      
      mediaRecorder.ondataavailable = (e) => audioChunks.push(e.data);
      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
        const formData = new FormData();
        formData.append('trader_id', currentTraderId);
        formData.append('file', audioBlob, 'voice_input.webm');

        try {
          const res = await fetch(`${API_BASE_URL}/transactions/voice-audio`, {
            method: 'POST',
            body: formData
          });
          const result = await res.json();

          alertBox.classList.remove('hidden');
          if (result.status_antifraude === 'VALIDÉ') {
            alertBox.className = "p-3 rounded-xl text-xs font-semibold text-center bg-emerald-900/60 text-emerald-300 border border-emerald-700";
            alertBox.innerText = `Opération validée ! Impact : +${result.score_impact} pts`;
          } else {
            alertBox.className = "p-3 rounded-xl text-xs font-semibold text-center bg-rose-900/60 text-rose-300 border border-rose-700";
            alertBox.innerText = `Alerte Anti-Fraude : Prix hors marché Lomé ! Impact : ${result.score_impact} pts`;
          }

          const traderRes = await fetch(`${API_BASE_URL}/traders/${currentTraderId}`);
          updateTraderUI(await traderRes.json());
          loadTransactions();
        } catch (err) {
          statusText.innerText = "Erreur lors de l'envoi";
        } finally {
          statusText.innerText = "Appuyez pour parler";
        }
      };

      mediaRecorder.start();
      recordBtn.classList.remove('bg-amber-500');
      recordBtn.classList.add('bg-rose-600', 'animate-pulse');
      statusText.innerText = "Écoute en cours... Ré-appuyez pour valider";
    } catch (e) {
      alert("Accès microphone requis !");
    }
  }
});

window.addEventListener('DOMContentLoaded', initTrader);
