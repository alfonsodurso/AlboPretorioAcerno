# check_albo.py

import requests
from bs4 import BeautifulSoup
import time
from urllib.parse import urljoin
import os
import json
import re

# --- CONFIGURAZIONE ---
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
GIST_ID = os.getenv('GIST_ID')
GIST_SECRET_TOKEN = os.getenv('GIST_SECRET_TOKEN')

GIST_FILENAME = 'processed_ids.txt'
ALBO_URL = "https://www.halleyweb.com/c065001/mc/mc_p_ricerca.php?noHeaderFooter=1&multiente=c065001"
BASE_URL = "https://www.halleyweb.com/c065001/mc/"
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}

# --- FUNZIONI GIST (invariate) ---
def get_gist_content():
    """Recupera il contenuto del file dal Gist."""
    headers = {'Authorization': f'token {GIST_SECRET_TOKEN}'}
    url = f'https://api.github.com/gists/{GIST_ID}'
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        gist_data = response.json()
        return gist_data['files'][GIST_FILENAME]['content']
    except Exception as e:
        print(f"❌ Errore nel recuperare il Gist: {e}. Parto con una lista vuota.")
        return ""

def update_gist_content(new_content):
    """Aggiorna il contenuto del file nel Gist."""
    headers = {'Authorization': f'token {GIST_SECRET_TOKEN}', 'Accept': 'application/vnd.github.v3+json'}
    url = f'https://api.github.com/gists/{GIST_ID}'
    payload = {'files': {GIST_FILENAME: {'content': new_content}}}
    try:
        response = requests.patch(url, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        print("✅ Gist aggiornato con successo.")
    except Exception as e:
        print(f"❌ Errore nell'aggiornare il Gist: {e}")

# --- NUOVA FUNZIONE DI NOTIFICA ---
def send_telegram_notification(publication):
    """Invia una notifica Telegram con un formato moderno e gestione allegati."""
    
    # Costruisce il messaggio in modo modulare
    message_parts = [
        f"🔔 *Nuova Pubblicazione all'Albo Pretorio*",
        f"\n📄 *Oggetto:* {publication['oggetto']}",
        f"\n🏷️ *Tipo Atto:* {publication['tipo']}",
        f"🔢 *Numero:* {publication['numero_pubblicazione']} del {publication['data_inizio']}",
        "\n---",
        "🔗 *Link Utili:*"
    ]
    
    # Aggiunge il link al documento principale SOLO se esiste
    if publication['url_documento']:
        message_parts.append(f"▸ [Scarica Documento Principale]({publication['url_documento']})")
    
    # Gestisce la lista degli allegati
    attachments = publication.get('allegati', [])
    if attachments:
        message_parts.append(f"\n📎 *Allegati ({len(attachments)}):*")
        
        MAX_ATTACHMENTS_TO_LIST = 3 # Mostra max 3 link diretti
        for i, att in enumerate(attachments[:MAX_ATTACHMENTS_TO_LIST]):
            message_parts.append(f"{i+1}. [{att['name']}]({att['url']})")
        
        if len(attachments) > MAX_ATTACHMENTS_TO_LIST:
            remaining = len(attachments) - MAX_ATTACHMENTS_TO_LIST
            message_parts.append(f"▸ _e altri {remaining}. [Visualizzali tutti qui]({publication['url_dettaglio']})_")
    else:
        # Se non ci sono allegati, mettiamo comunque un link generico ai dettagli
        message_parts.append(f"▸ [Vedi Dettagli sulla Pagina]({publication['url_dettaglio']})")

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

# --- FUNZIONE PRINCIPALE (aggiornata per fetch allegati) ---
def check_for_new_publications():
    """Funzione principale che controlla, confronta e notifica."""
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GIST_ID, GIST_SECRET_TOKEN]):
        print("❌ ERRORE: Una o più credenziali (Secrets) non sono state impostate.")
        return

    print("--- Avvio controllo nuove pubblicazioni ---")
    gist_content = get_gist_content()
    processed_ids = set(gist_content.splitlines())
    print(f"Caricati {len(processed_ids)} ID già processati dal Gist.")

    try:
        response = requests.get(ALBO_URL, headers=HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'lxml')
    except requests.exceptions.RequestException as e:
        print(f"Errore: Impossibile scaricare la pagina dell'Albo. {e}")
        return

    rows = [r for r in soup.select('#table-albo tbody tr') if len(r.find_all('td')) > 1]
    new_publications_to_notify = []
    
    for row in rows:
        act_id = row.select_one('td.visible-xs')['data-id'] if row.select_one('td.visible-xs') else None
        if not act_id or act_id in processed_ids:
            continue
            
        print(f"TROVATO NUOVO ATTO! ID: {act_id}")
        
        cells = row.find_all('td')
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
            'url_documento': urljoin(BASE_URL, re.search(r"window\.open\('([^']*)'\)", doc_link_tag['onclick']).group(1)) if doc_link_tag else "",
            'allegati': [] # Lista per gli allegati
        }

        # **NUOVA LOGICA: Visita la pagina di dettaglio per cercare allegati**
        if publication_details['url_dettaglio']:
            try:
                print(f"  -> Visito la pagina di dettaglio per l'atto n. {act_id}...")
                detail_res = requests.get(publication_details['url_dettaglio'], headers=HEADERS)
                if detail_res.ok:
                    detail_soup = BeautifulSoup(detail_res.text, 'lxml')
                    # Cerca i link degli allegati nella sezione specifica
                    allegati_section = detail_soup.select('.cms-table-allegati a[href*="mc_attachment.php"]')
                    for link in allegati_section:
                        publication_details['allegati'].append({
                            'name': link.get_text(strip=True),
                            'url': urljoin(BASE_URL, link['href'])
                        })
                time.sleep(0.5) # Piccola pausa per non sovraccaricare il server
            except Exception as e:
                print(f"  -> Errore nel recuperare gli allegati per l'atto {act_id}: {e}")

        new_publications_to_notify.append(publication_details)

    if not new_publications_to_notify:
        print("Nessuna nuova pubblicazione trovata.")
    else:
        for publication in reversed(new_publications_to_notify):
            send_telegram_notification(publication)
            time.sleep(2)
        
        new_ids_found = [p['id'] for p in new_publications_to_notify]
        final_content = gist_content + "\n" + "\n".join(new_ids_found)
        update_gist_content(final_content.strip())

    print("--- Controllo terminato ---")

if __name__ == "__main__":
    check_for_new_publications()
