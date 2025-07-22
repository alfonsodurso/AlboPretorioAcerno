# check_albo.py (versione finale con gestione della paginazione)

import requests
from bs4 import BeautifulSoup
import time
from urllib.parse import urljoin
import os
import json
import re

# --- CONFIGURAZIONE ---
# Leggi i segreti dalle variabili d'ambiente di GitHub Actions
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
GIST_ID = os.getenv('GIST_ID')
GIST_SECRET_TOKEN = os.getenv('GIST_SECRET_TOKEN')

# Nome del file all'interno del Gist
GIST_FILENAME = 'processed_ids.txt'

# URL dell'Albo Pretorio
BASE_URL = "https://www.halleyweb.com/c065001/mc/"
START_URL = urljoin(BASE_URL, "mc_p_ricerca.php?noHeaderFooter=1&multiente=c065001")
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}


def get_gist_content():
    """Recupera il contenuto del file dal Gist."""
    headers = {'Authorization': f'token {GIST_SECRET_TOKEN}'}
    url = f'https://api.github.com/gists/{GIST_ID}'
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        gist_data = response.json()
        # Gestisce il caso in cui il file non esista ancora nel Gist
        if GIST_FILENAME in gist_data['files']:
            return gist_data['files'][GIST_FILENAME]['content']
        return ""
    except Exception as e:
        print(f"❌ Errore nel recuperare il Gist: {e}. Parto con una lista vuota.")
        return ""

def update_gist_content(new_content):
    """Aggiorna il contenuto del file nel Gist."""
    headers = {
        'Authorization': f'token {GIST_SECRET_TOKEN}',
        'Accept': 'application/vnd.github.v3+json'
    }
    url = f'https://api.github.com/gists/{GIST_ID}'
    payload = {'files': {GIST_FILENAME: {'content': new_content}}}
    try:
        response = requests.patch(url, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        print("✅ Gist aggiornato con successo.")
    except Exception as e:
        print(f"❌ Errore nell'aggiornare il Gist: {e}")

def send_telegram_notification(publication):
    """Invia una notifica tramite il bot di Telegram, gestendo link opzionali."""
    message_parts = [
        f"🔔 *Nuova Pubblicazione*",
        f"\n*Oggetto:* {publication['oggetto']}",
        f"\n*Tipo Atto:* {publication['tipo']}",
        f"*Numero:* {publication['numero_pubblicazione']} del {publication['data_inizio']}"
    ]
    if publication['url_documento']:
        message_parts.append(f"\n[Scarica Documento Principale]({publication['url_documento']})")
    message_parts.append(f"\n[Vedi Dettagli e Allegati]({publication['url_dettaglio']})")
    
    final_message = "\n".join(message_parts)
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': final_message, 'parse_mode': 'Markdown'}
    try:
        response = requests.post(url, data=payload)
        response.raise_for_status()
        if response.json().get('ok'):
            print(f"✅ Notifica inviata per l'atto n. {publication['numero_pubblicazione']}")
        else:
            print(f"❌ Errore API Telegram: {response.json().get('description')}")
    except Exception as e:
        print(f"❌ Eccezione durante l'invio della notifica: {e}")

def check_for_new_publications():
    """Funzione principale che controlla, confronta e notifica, gestendo la paginazione."""
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GIST_ID, GIST_SECRET_TOKEN]):
        print("❌ ERRORE: Una o più credenziali (Secrets) non sono state impostate.")
        return

    print("--- Avvio controllo nuove pubblicazioni ---")
    gist_content = get_gist_content()
    processed_ids = set(gist_content.splitlines())
    print(f"Caricati {len(processed_ids)} ID già processati dal Gist.")
    
    new_publications_to_notify = []
    current_page_url = START_URL
    page_num = 1

    # Inizia il ciclo di paginazione
    while current_page_url:
        print(f"--- Analizzo la Pagina {page_num} ---")
        
        try:
            response = requests.get(current_page_url, headers=HEADERS)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')
        except requests.exceptions.RequestException as e:
            print(f"Errore: Impossibile scaricare la pagina {page_num}. {e}")
            break # Interrompi il ciclo se una pagina non è raggiungibile

        rows = [r for r in soup.select('#table-albo tbody tr') if len(r.find_all('td')) > 1]
        
        if not rows:
            print("Nessuna riga trovata in questa pagina. Interruzione.")
            break
            
        for row in rows:
            act_id = row.select_one('td.visible-xs')['data-id'] if row.select_one('td.visible-xs') else None
            if not act_id or act_id in processed_ids:
                continue
            
            print(f"TROVATO NUOVO ATTO! ID: {act_id}")
            cells = row.find_all('td')
            # ... (logica di estrazione invariata)
            lines_c1 = cells[0].get_text('\n', strip=True).split('\n')
            oggetto_link = cells[1].find('a')
            lines_c5 = cells[4].get_text('\n', strip=True).split('\n')
            doc_link_tag = cells[5].find('a', onclick=lambda val: 'mc_attachment.php' in val if val else False)
            
            publication_details = {
                'id': act_id,
                'numero_pubblicazione': lines_c1[1] if len(lines_c1) > 1 else '',
                'tipo': lines_c1[5] if len(lines_c1) > 5 else '',
                'oggetto': oggetto_link.get_text(strip=True) if oggetto_link else 'N/D',
                'url_dettaglio': urljoin(BASE_URL, oggetto_link['href']) if oggetto_link else '',
                'data_inizio': lines_c5[1] if len(lines_c5) > 1 else '',
                'url_documento': urljoin(BASE_URL, re.search(r"window\.open\('([^']*)'\)", doc_link_tag['onclick']).group(1)) if doc_link_tag else ""
            }
            new_publications_to_notify.append(publication_details)

        # Cerca il link alla pagina successiva
        next_page_link = soup.find('a', title="Pagina successiva")
        if next_page_link and next_page_link.has_attr('href'):
            current_page_url = urljoin(BASE_URL, next_page_link['href'])
            page_num += 1
            time.sleep(1) # Piccola pausa prima di caricare la pagina successiva
        else:
            current_page_url = None # Fine della paginazione

    # Ora, dopo aver scansionato tutte le pagine, invia le notifiche e aggiorna il Gist
    if not new_publications_to_notify:
        print("Nessuna nuova pubblicazione trovata in totale.")
    else:
        print(f"\nTrovati {len(new_publications_to_notify)} nuovi atti in totale. Invio notifiche...")
        for publication in reversed(new_publications_to_notify): # Notifica i più vecchi prima
            send_telegram_notification(publication)
            time.sleep(2)
        
        new_ids_found = [p['id'] for p in new_publications_to_notify]
        final_content = gist_content + "\n" + "\n".join(new_ids_found)
        update_gist_content(final_content.strip())

    print("--- Controllo terminato ---")

if __name__ == "__main__":
    check_for_new_publications()
