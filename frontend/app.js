const API_BASE_URL = window.location.hostname === 'localhost' 
  ? 'http://localhost:8000' 
: https://akounta-backend.onrender.com;
let userToken = localStorage.getItem('akounta_token');
let selectedPaymentMethod = 'TMONEY';
let mediaRecorder;
let audioChunks = [];

function checkAuth() {
  if (userToken) {
    document.getElementById('auth-screen').classList.add('hidden');
    document.getElementById('main-app').classList.remove('hidden');
    fetchProfile();
    refreshAccountingData();
  } else {
    document.getElementById('auth-screen').classList.remove('hidden');
    document.getElementById('main-app').classList.add('hidden');
  }
}

// Connexion / Inscription
document.getElementById('login-btn').addEventListener('click', async () => {
  const phone = document.getElementById('login-phone').value.trim();
  const name = document.getElementById('login-name').value.trim() || 'Commerçant Lomé';
  const pin = document.getElementById('login-pin').value.trim();

  if (!phone || !pin) {
    alert("Veuillez renseigner votre numéro et votre code PIN.");
    return;
  }

  try {
    const res = await fetch(`${API_BASE_URL}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phone_number: phone, name: name, pin_code: pin })
    });
    const data = await res.json();
    if (!res.ok) {
      alert(data.detail || "Erreur de connexion.");
      return;
    }

    userToken = data.token;
    localStorage.setItem('akounta_token', userToken);
    checkAuth();
  } catch (e) {
    alert("Erreur de connexion au serveur.");
  }
});

// Déconnexion
document.getElementById('logout-btn').addEventListener('click', () => {
  localStorage.removeItem('akounta_token');
  userToken = null;
  checkAuth();
});

async function fetchProfile() {
  try {
    const res = await fetch(`${API_BASE_URL}/traders/me`, {
      headers: { 'Authorization': `Bearer ${userToken}` }
    });
    if (res.status === 401 || res.status === 402) {
      if (res.status === 402) {
        alert("Votre abonnement a expiré. Veuillez le renouveler pour continuer.");
        document.getElementById('sub-modal').classList.remove('hidden');
      }
      return;
    }
    const trader = await res.json();
    document.getElementById('trader-name').innerText = trader.name;
    document.getElementById('trader-phone').innerText = trader.phone_number;
    document.getElementById('score-val').innerHTML = `${trader.credit_score} <span class="text-xs font-normal text-slate-400">/ 1000 pts</span>`;
    document.getElementById('score-bar').style.width = `${Math.min(100, (trader.credit_score / 1000) * 100)}%`;
    document.getElementById('loan-val').innerText = `${trader.eligible_loan_xof.toLocaleString()} FCFA`;
    document.getElementById('sub-plan-name').innerText = trader.subscription_plan;
    document.getElementById('sub-expiry-date').innerText = trader.subscription_expires_at;

    const badgeEl = document.getElementById('badge-pill');
    badgeEl.innerText = trader.badge;
    if (trader.badge === 'Or') {
      badgeEl.className = 'px-2.5 py-1 rounded-full text-[10px] font-black uppercase tracking-wider bg-yellow-500 text-slate-950 border border-yellow-300';
    } else if (trader.badge === 'Argent') {
      badgeEl.className = 'px-2.5 py-1 rounded-full text-[10px] font-black uppercase tracking-wider bg-slate-300 text-slate-950 border border-white';
    } else {
      badgeEl.className = 'px-2.5 py-1 rounded-full text-[10px] font-black uppercase tracking-wider bg-amber-950 text-amber-300 border border-amber-700/50';
    }
  } catch (err) {
    console.error(err);
  }
}

async function refreshAccountingData() {
  try {
    const resSum = await fetch(`${API_BASE_URL}/traders/me/accounting-summary`, {
      headers: { 'Authorization': `Bearer ${userToken}` }
    });
    if (resSum.ok) {
      const sum = await resSum.json();
      document.getElementById('compta-ventes').innerText = `${sum.total_ventes.toLocaleString()} FCFA`;
      document.getElementById('compta-achats').innerText = `${sum.total_achats.toLocaleString()} FCFA`;
      document.getElementById('compta-benefice').innerText = `${sum.benefice_net.toLocaleString()} FCFA`;
      document.getElementById('compta-dettes').innerText = `${sum.total_dettes.toLocaleString()} FCFA`;
      document.getElementById('tx-count').innerText = `${sum.nb_transactions} écriture(s)`;
    }

    const resTx = await fetch(`${API_BASE_URL}/traders/me/transactions`, {
      headers: { 'Authorization': `Bearer ${userToken}` }
    });
    if (resTx.ok) {
      const list = await resTx.json();
      const container = document.getElementById('transaction-list');
      if (list.length === 0) {
        container.innerHTML = '<p class="text-slate-500 text-center py-6">Aucune écriture comptable. Cliquez sur le micro pour dicter.</p>';
        return;
      }

      container.innerHTML = list.map(tx => {
        const isVente = tx.type_transaction === 'vente';
        const isAchat = tx.type_transaction === 'achat';
        const colorSign = isVente ? 'text-emerald-400' : (isAchat ? 'text-rose-400' : 'text-amber-400');
        const prefix = isVente ? '+ ' : (isAchat ? '- ' : '');

        return `
          <div class="flex justify-between items-start bg-slate-950/60 p-3 rounded-xl border border-slate-800/80">
            <div class="space-y-0.5">
              <div class="font-bold text-slate-200">
                <span class="px-1.5 py-0.5 rounded text-[9px] font-black uppercase ${isVente ? 'bg-emerald-950 text-emerald-300 border border-emerald-800' : (isAchat ? 'bg-rose-950 text-rose-300 border border-rose-800' : 'bg-amber-950 text-amber-300 border border-amber-800')}">
                  ${tx.type_transaction}
                </span>
                <span class="ml-1 uppercase text-slate-100">${tx.produit} (x${tx.quantite})</span>
              </div>
              <div class="text-[10px] text-slate-400">
                ${new Date(tx.timestamp).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })}
                ${tx.client_nom ? ' • Client: <strong class="text-slate-300">' + tx.client_nom + '</strong>' : ''}
              </div>
              ${tx.note_vocale ? '<div class="text-[10px] text-slate-500 italic">« ' + tx.note_vocale + ' »</div>' : ''}
            </div>
            <div class="text-right">
              <div class="font-black text-sm ${colorSign}">${prefix}${tx.montant_total_xof.toLocaleString()} XOF</div>
              <span class="text-[9px] px-1.5 py-0.5 rounded font-black ${tx.status_antifraude === 'VALIDÉ' ? 'bg-emerald-950 text-emerald-300' : 'bg-rose-950 text-rose-300'}">
                ${tx.status_antifraude} (${tx.score_impact >= 0 ? '+' : ''}${tx.score_impact} pts)
              </span>
            </div>
          </div>
        `;
      }).join('');
    }
  } catch (err) {
    console.error(err);
  }
}

// Téléchargement du journal CSV
document.getElementById('export-btn').addEventListener('click', () => {
  window.open(`${API_BASE_URL}/traders/me/export-journal?token=${userToken}`, '_blank');
});

// Gestion de la modale d'abonnement
document.getElementById('open-sub-modal').addEventListener('click', () => {
  document.getElementById('sub-modal').classList.remove('hidden');
});
document.getElementById('close-sub-modal').addEventListener('click', () => {
  document.getElementById('sub-modal').classList.add('hidden');
});

document.querySelectorAll('.pay-method-btn').forEach(btn => {
  btn.addEventListener('click', (e) => {
    document.querySelectorAll('.pay-method-btn').forEach(b => {
      b.classList.remove('bg-amber-500', 'text-slate-950');
      b.classList.add('bg-slate-800', 'text-slate-300');
    });
    btn.classList.add('bg-amber-500', 'text-slate-950');
    btn.classList.remove('bg-slate-800', 'text-slate-300');
    selectedPaymentMethod = btn.getAttribute('data-method');
  });
});

document.getElementById('confirm-sub-btn').addEventListener('click', async () => {
  const plan = document.querySelector('input[name="sub-plan"]:checked').value;
  try {
    const res = await fetch(`${API_BASE_URL}/subscription/subscribe`, {
      method: 'POST',
      headers: { 
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${userToken}`
      },
      body: JSON.stringify({
        plan: plan,
        payment_method: selectedPaymentMethod,
        phone_payment: 'Paiement direct'
      })
    });
    const data = await res.json();
    alert(data.message || "Abonnement validé !");
    document.getElementById('sub-modal').classList.add('hidden');
    fetchProfile();
  } catch (e) {
    alert("Erreur lors de la validation du paiement.");
  }
});

// Enregistrement vocal
const recordBtn = document.getElementById('record-btn');
const statusText = document.getElementById('record-status');
const alertBox = document.getElementById('fraud-alert');

recordBtn.addEventListener('click', async () => {
  if (mediaRecorder && mediaRecorder.state === "recording") {
    mediaRecorder.stop();
    recordBtn.classList.remove('bg-rose-600', 'animate-pulse');
    recordBtn.classList.add('bg-amber-500');
    statusText.innerText = "⏳ L'Agent IA tient le livre...";
  } else {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioChunks = [];
      mediaRecorder = new MediaRecorder(stream);
      mediaRecorder.ondataavailable = (e) => audioChunks.push(e.data);
      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
        const formData = new FormData();
        formData.append('file', audioBlob, 'voice_input.webm');

        try {
          const res = await fetch(`${API_BASE_URL}/transactions/voice-audio`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${userToken}` },
            body: formData
          });
          if (res.status === 402) {
            alert("Abonnement requis : veuillez renouveler votre forfait.");
            document.getElementById('sub-modal').classList.remove('hidden');
            return;
          }
          const result = await res.json();
          alertBox.classList.remove('hidden');
          if (result.status_antifraude === 'VALIDÉ') {
            alertBox.className = "p-3 rounded-xl text-xs font-bold text-center bg-emerald-950/80 text-emerald-300 border border-emerald-700";
            alertBox.innerText = `Écriture enregistrée par l'IA ! Impact : +${result.score_impact} pts`;
          } else {
            alertBox.className = "p-3 rounded-xl text-xs font-bold text-center bg-rose-950/80 text-rose-300 border border-rose-700";
            alertBox.innerText = `⚠️ Prix hors marché Lomé ! Écriture suspecte (${result.score_impact} pts)`;
          }

          fetchProfile();
          refreshAccountingData();
        } catch (err) {
          statusText.innerText = "Erreur de connexion";
        } finally {
          statusText.innerText = "Appuyez pour parler";
        }
      };

      mediaRecorder.start();
      recordBtn.classList.remove('bg-amber-500');
      recordBtn.classList.add('bg-rose-600', 'animate-pulse');
      statusText.innerText = "🔴 Écoute en cours... Ré-appuyez pour valider";
    } catch (e) {
      alert("Accès microphone requis !");
    }
  }
});

window.addEventListener('DOMContentLoaded', checkAuth);
