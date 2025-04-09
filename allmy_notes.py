# -*- coding: utf-8 -*-
import json
import os
import logging
import copy
from datetime import datetime, timedelta
from pathlib import Path
import re
import time

from langchain_core.messages import HumanMessage, SystemMessage
from dotenv import load_dotenv, find_dotenv

# --- Load Environment Variables ---
load_dotenv(find_dotenv())
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").lower()
MODEL_NAME = os.environ.get("MODEL_NAME") # Required for both providers

# --- Provider Specific Configuration & Availability ---
OLLAMA_AVAILABLE = False
GEMINI_AVAILABLE = False
OLLAMA_BASE_URL = ""
GEMINI_API_KEY = ""

# Attempt to import provider-specific modules and check configuration
try:
    if LLM_PROVIDER == "ollama":
        from langchain_ollama import ChatOllama # Updated import
        OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        if not OLLAMA_BASE_URL:
             logging.warning("LLM_PROVIDER is 'ollama', but 'OLLAMA_BASE_URL' is missing in .env. Using default.")
             # Default is already set above, just logging the warning.
        OLLAMA_AVAILABLE = True # Mark as potentially available

    elif LLM_PROVIDER == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        # HarmCategory/HarmBlockThreshold needed for safety settings
        try:
            from langchain_google_vertexai import HarmCategory, HarmBlockThreshold
        except ImportError:
            # Fallback if vertexai is not installed but genai is
            from google.generativeai.types import HarmCategory, HarmBlockThreshold
            logging.warning("Imported HarmCategory/HarmBlockThreshold from google.generativeai.types (fallback). Consider installing langchain-google-vertexai.")

        GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
        if not GEMINI_API_KEY:
            logging.error("LLM_PROVIDER is 'gemini', but 'GEMINI_API_KEY' is missing in .env.")
            # Keep GEMINI_AVAILABLE False
        else:
             GEMINI_AVAILABLE = True # Mark as potentially available

except ImportError as e:
    logging.error(f"Import Error for provider '{LLM_PROVIDER}': {e}. Please ensure the required package is installed.")
    if LLM_PROVIDER == "ollama":
        logging.error("-> For Ollama, run: pip install langchain-ollama")
        OLLAMA_AVAILABLE = False
    if LLM_PROVIDER == "gemini":
        logging.error("-> For Gemini, run: pip install langchain-google-genai google-generativeai")
        GEMINI_AVAILABLE = False


# --- Konstanten ---
INPUT_JSON_FILE = 'allmystery.json'
INTERMEDIATE_JSON_FILE = 'allmy_llm_input.json'
SYSTEM_PROMPT_FILE = 'allmy_prompt.md'
LOG_FILE = 'allmy_log.log'

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, mode='w', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# --- Core Functions (File I/O, Input Handling, Parsing, Sanitizing) ---
def load_data(filename):
    filepath = Path(filename)
    if not filepath.exists():
        logging.error(f"Fehler: Datei '{filename}' nicht gefunden.")
        return None
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        logging.info(f"'{filename}' erfolgreich geladen.")
        return data
    except json.JSONDecodeError as e:
        logging.error(f"Fehler beim Parsen von JSON in '{filename}': {e}")
        return None
    except Exception as e:
        logging.error(f"Allgemeiner Fehler beim Laden von '{filename}': {e}")
        return None

def save_data(data, filename):
    filepath = Path(filename)
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        logging.info(f"Daten erfolgreich in '{filepath}' gespeichert.")
        return True
    except Exception as e:
        logging.error(f"Fehler beim Speichern in '{filepath}': {e}")
        return False

def get_int_threshold(prompt, default=0):
    while True:
        try:
            user_input = input(prompt + f" (Standard: {default}): ")
            if not user_input:
                return default
            value = int(user_input)
            if value >= 0:
                return value
            else:
                print("Bitte geben Sie eine nicht-negative Zahl ein.")
        except ValueError:
            print("Ungültige Eingabe. Bitte geben Sie eine ganze Zahl ein.")

def get_date_input(prompt):
    while True:
        try:
            user_input = input(prompt + " (Format DD.MM.YYYY, leer lassen für keine Grenze): ").strip()
            if not user_input:
                return None
            # Use datetime.strptime to parse and then .date() to get only the date part
            return datetime.strptime(user_input, '%d.%m.%Y').date()
        except ValueError:
            print("Ungültiges Datumsformat. Bitte verwenden Sie DD.MM.YYYY oder lassen Sie das Feld leer.")

def get_comma_separated_list(prompt):
    user_input = input(prompt).strip()
    if user_input.lower() == '*alle*':
        return ['*alle*']
    # Split by comma, strip whitespace from each item, filter out empty strings
    return [item.strip() for item in user_input.split(',') if item.strip()] if user_input else []

def parse_date_safe(date_str):
    """Safely parses a date string in DD.MM.YYYY format."""
    if not isinstance(date_str, str): return None # Handle non-string inputs
    try:
        return datetime.strptime(date_str, '%d.%m.%Y').date()
    except (ValueError, TypeError):
        return None # Return None if parsing fails or input is invalid type

def sanitize_filename(filename):
    """Removes invalid characters for filenames and limits length."""
    # Remove characters forbidden in Windows/Linux filenames and control characters
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', filename)
    # Limit length to prevent issues with file systems
    max_len = 200
    if len(sanitized) > max_len:
        sanitized = sanitized[:max_len].rsplit(' ', 1)[0] # Try to cut at last space
        if not sanitized: # Fallback if rsplit removes everything
             sanitized = sanitized[:max_len]
    # Replace multiple spaces/dots with single ones
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    sanitized = re.sub(r'\.+', '.', sanitized).strip('.')

    return sanitized if sanitized else "unbenanntes_thema"

# --- Filterfunktionen ---
def filter_by_total_article_length(data, threshold):
    if threshold <= 0: return data
    threads_to_delete = []
    original_count = len(data)
    logging.info(f"Filtere Artikelgesamtlänge (< {threshold} Zeichen)...")
    for thread_id, thread_data in data.items():
        # Ensure 'diary' exists and is a dictionary
        diary = thread_data.get('diary')
        if not isinstance(diary, dict): continue # Skip if diary is missing or not a dict

        total_length = sum(len(p.get('article', '')) for p in diary.values() if isinstance(p, dict))
        if total_length < threshold:
            threads_to_delete.append(thread_id)

    for thread_id in threads_to_delete:
        logging.info(f"LÖSCHE Thema '{thread_id}' ({data[thread_id].get('title', 'Unbekannt')}): Artikellänge ({sum(len(p.get('article', '')) for p in data[thread_id].get('diary', {}).values())}) < {threshold}")
        del data[thread_id]
    logging.info(f"Artikelgesamtlänge: {len(threads_to_delete)} von {original_count} Themen entfernt.")
    return data

def filter_by_memberquote_length(data, threshold):
    if threshold <= 0: return data
    logging.info(f"Filtere Mitgliedszitatlänge (< {threshold} Zeichen)...")
    deleted_quotes_count = 0
    for thread_id, thread_data in data.items():
        diary = thread_data.get('diary')
        if isinstance(diary, dict):
            for post_key, post_data in diary.items():
                 if isinstance(post_data, dict) and 'memberquotes' in post_data and isinstance(post_data['memberquotes'], dict):
                    quotes_to_delete = []
                    for k, v in post_data['memberquotes'].items():
                         # Ensure value is a string before checking length
                         if isinstance(v, str) and len(v) < threshold:
                              quotes_to_delete.append(k)
                    for key in quotes_to_delete:
                        logging.debug(f"LÖSCHE Mitgliedszitat '{key}' in Post '{post_key}', Thema '{thread_id}': Länge < {threshold}")
                        del post_data['memberquotes'][key]
                        deleted_quotes_count += 1
                    # Remove 'memberquotes' dict if it becomes empty
                    if not post_data['memberquotes']:
                        del post_data['memberquotes']
    logging.info(f"Mitgliedszitatlänge: {deleted_quotes_count} Zitate entfernt.")
    return data

def filter_by_date_range(data, start_date, end_date):
    if start_date is None and end_date is None: return data
    start_str = start_date.strftime('%d.%m.%Y') if start_date else "Anfang"
    end_str = end_date.strftime('%d.%m.%Y') if end_date else "Ende"
    logging.info(f"Filtere Beiträge außerhalb des Zeitraums: {start_str} bis {end_str}...")
    deleted_posts_count = 0
    threads_potentially_empty = []

    for thread_id, thread_data in data.items():
        diary = thread_data.get('diary')
        if isinstance(diary, dict):
            posts_to_delete = []
            for post_key, post_data in diary.items():
                if not isinstance(post_data, dict): continue # Skip invalid post data
                post_date_str = post_data.get('date')
                post_date = parse_date_safe(post_date_str)
                delete_post = False
                reason = ""

                if post_date is None:
                    logging.warning(f"Ungültiges oder fehlendes Datum '{post_date_str}' in Post '{post_key}', Thema '{thread_id}'. Beitrag wird beibehalten.")
                    continue # Keep posts with invalid dates

                if start_date and post_date < start_date:
                    delete_post = True
                    reason = f"vor {start_str}"
                elif end_date and post_date > end_date:
                    delete_post = True
                    reason = f"nach {end_str}"

                if delete_post:
                    posts_to_delete.append(post_key)
                    logging.debug(f"Markiere Post '{post_key}' in Thema '{thread_id}' zum Löschen (Datum: {post_date_str}, Grund: {reason}).")

            if posts_to_delete:
                for key in posts_to_delete:
                     if key in data[thread_id]['diary']: # Check existence before deleting
                         del data[thread_id]['diary'][key]
                         deleted_posts_count += 1
                         logging.info(f"LÖSCHE Post '{key}' in '{thread_id}' - Außerhalb {start_str}-{end_str}")
                # If posts were deleted, mark the thread for potential emptiness check
                if not data[thread_id]['diary']:
                     threads_potentially_empty.append(thread_id)

    # Check threads marked as potentially empty and remove them if they are truly empty
    deleted_empty_threads_count = 0
    for thread_id in threads_potentially_empty:
        # Ensure the thread still exists and its diary is empty
        if thread_id in data and isinstance(data[thread_id].get('diary'), dict) and not data[thread_id]['diary']:
           logging.info(f"LÖSCHE Thema '{thread_id}' ({data[thread_id].get('title', 'Unbekannt')}): Keine Posts nach Datumsfilter.")
           del data[thread_id]
           deleted_empty_threads_count +=1

    logging.info(f"Datumsfilter: {deleted_posts_count} Beiträge entfernt. {deleted_empty_threads_count} Themen wurden dadurch geleert und entfernt.")
    return data

def split_threads_by_time_gap(data, filter_list, days_threshold):
    if days_threshold <= 0 or not filter_list: return data

    split_all = '*alle*' in filter_list
    if split_all:
        logging.info(f"Prüfe *ALLE* Themen auf Aufteilung bei Zeitlücken > {days_threshold} Tage...")
        # Create a list of all valid thread IDs to iterate over if '*alle*' is selected
        target_thread_ids = list(data.keys())
    else:
        # Separate categories and IDs from the user input
        filter_categories = {item.lower() for item in filter_list if not item.replace('_','').isalnum() or not any(char.isdigit() for char in item)} # Allow underscore in IDs
        filter_ids = {item for item in filter_list if item not in filter_categories}
        logging.info(f"Prüfe Themen (IDs: {filter_ids}, Kategorien: {filter_categories}) auf Aufteilung bei Zeitlücken > {days_threshold} Tage...")
        # Determine target threads based on IDs or categories
        target_thread_ids = [
            tid for tid, tdata in data.items()
            if tid in filter_ids or tdata.get('category', '').lower() in filter_categories
        ]

    split_count = 0
    newly_created_threads = {} # Store newly created parts here temporarily

    # Iterate only over the target threads
    for thread_id in target_thread_ids:
        if thread_id not in data: continue # Thread might have been deleted by previous filters

        thread_data = data[thread_id]
        title = thread_data.get('title', 'Unbekannt')
        category = thread_data.get('category', 'Unkategorisiert')
        diary = thread_data.get('diary')

        # Check if splitting is feasible
        if not isinstance(diary, dict) or len(diary) < 2:
            continue # Skip if no diary or less than 2 posts

        logging.debug(f"Prüfe '{thread_id}' ({title}) auf Zeitlücken...")

        # Sort posts by date
        valid_posts = []
        for item in diary.items():
             post_key, post_data = item
             if isinstance(post_data, dict):
                  post_date = parse_date_safe(post_data.get('date'))
                  if post_date:
                       valid_posts.append((post_key, post_data, post_date))
                  else:
                       logging.warning(f"Post '{post_key}' in Thema '{thread_id}' hat ungültiges Datum, wird beim Sortieren ignoriert.")
             else:
                  logging.warning(f"Ungültiger Post-Eintrag (kein dict) bei Schlüssel '{post_key}' in Thema '{thread_id}'.")


        if len(valid_posts) < 2:
             logging.debug(f"Thema '{thread_id}' hat weniger als 2 Posts mit gültigem Datum. Überspringe Split.")
             continue # Not enough valid posts to compare dates

        sorted_posts = sorted(valid_posts, key=lambda item: item[2]) # Sort by the parsed date (item[2])

        # --- Splitting Logic ---
        current_part_index = 1
        original_thread_id_base = thread_id # Keep track of the original ID
        current_part_posts = {} # Dictionary to hold posts for the current part
        last_post_date = sorted_posts[0][2] # Date of the first post in the current part
        current_part_posts[sorted_posts[0][0]] = sorted_posts[0][1] # Add first post

        current_part_thread_id = original_thread_id_base # ID for the first part

        for i in range(1, len(sorted_posts)):
            post_key, post_data, current_post_date = sorted_posts[i]
            time_diff = current_post_date - last_post_date

            if time_diff.days > days_threshold:
                # --- GAP DETECTED - Finalize the previous part ---
                split_count += 1
                part_title = f"{title} Teil {current_part_index}"
                logging.info(f"SPLIT in '{original_thread_id_base}' nach Post vom {last_post_date.strftime('%d.%m.%Y')} vor Post vom {current_post_date.strftime('%d.%m.%Y')}: {time_diff.days} Tage Lücke. Erstelle '{part_title}'.")

                # Update the diary and title of the *previous* part
                if current_part_thread_id == original_thread_id_base:
                    # This is the original thread ID, update it directly in 'data'
                    if current_part_thread_id in data:
                         data[current_part_thread_id]['title'] = part_title
                         data[current_part_thread_id]['diary'] = current_part_posts
                else:
                    # This part was newly created, update it in 'newly_created_threads'
                     if current_part_thread_id in newly_created_threads:
                          newly_created_threads[current_part_thread_id]['title'] = part_title
                          newly_created_threads[current_part_thread_id]['diary'] = current_part_posts

                # --- Start the NEW part ---
                current_part_index += 1
                new_thread_id = f"{original_thread_id_base}_part{current_part_index}"
                new_title_placeholder = f"{title} Teil {current_part_index} (Platzhalter)"
                logging.debug(f"Erstelle neuen Teil: '{new_thread_id}' für '{new_title_placeholder}'")

                # Add the new part structure to the temporary dict
                newly_created_threads[new_thread_id] = {
                    "title": new_title_placeholder, # Placeholder title for now
                    "category": category,
                    "diary": {} # Start with empty diary for the new part
                }

                # Reset for the new part
                current_part_posts = {post_key: post_data} # Start with the current post
                current_part_thread_id = new_thread_id # Update the ID we are working on
            else:
                # No gap, add post to the current part's diary
                current_part_posts[post_key] = post_data

            # Update last_post_date for the next iteration
            last_post_date = current_post_date

        # --- Finalize the LAST part ---
        # After the loop, assign the collected posts to the last part's diary and set its final title
        final_part_title = f"{title} Teil {current_part_index}" if current_part_index > 1 else title # Only add "Teil X" if split occurred
        if current_part_thread_id == original_thread_id_base:
             if current_part_thread_id in data:
                  data[current_part_thread_id]['title'] = final_part_title
                  data[current_part_thread_id]['diary'] = current_part_posts
        else:
             if current_part_thread_id in newly_created_threads:
                  newly_created_threads[current_part_thread_id]['title'] = final_part_title
                  newly_created_threads[current_part_thread_id]['diary'] = current_part_posts


    # Add all newly created thread parts to the main data dictionary
    if newly_created_threads:
         logging.info(f"Füge {len(newly_created_threads)} neu erstellte Thread-Teile hinzu.")
         data.update(newly_created_threads)

    logging.info(f"Themenaufteilung abgeschlossen: {split_count} Aufteilungen durchgeführt.")
    return data


# --- LLM-Vorbereitung & Speicherung ---
def load_system_prompt(filename=SYSTEM_PROMPT_FILE):
    filepath = Path(filename)
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
         logging.warning(f"System-Prompt-Datei '{filename}' nicht gefunden. Verwende leeren Prompt.")
         return ""
    except Exception as e:
        logging.warning(f"Fehler beim Lesen des System-Prompts '{filename}': {e}. Verwende leeren Prompt.")
        return ""

def prepare_llm_requests(data, system_prompt):
    requests = []
    logging.info("Bereite Daten für LLM-Anfragen vor...")
    for thread_id, thread_data in data.items():
        title = thread_data.get('title', 'Unbekanntes Thema')
        category = thread_data.get('category', 'Unkategorisiert')
        diary = thread_data.get('diary', {})

        if not isinstance(diary, dict) or not diary:
            logging.debug(f"Überspringe Thema '{thread_id}' ({title}): Kein 'diary' oder leer.")
            continue

        user_prompt_parts = [f"# Thema: {title}\n"]
        links = set()
        post_counter = 0 # Zählt nur Posts mit tatsächlichem 'article' Inhalt

        # Sort posts by date before processing
        valid_posts_for_prompt = []
        for item in diary.items():
             post_key, post_data = item
             if isinstance(post_data, dict):
                  post_date = parse_date_safe(post_data.get('date'))
                  # Include posts even without valid date for prompt generation, sort invalids last
                  valid_posts_for_prompt.append((post_key, post_data, post_date if post_date else datetime.max.date()))
             else:
                  logging.warning(f"Ignoriere ungültigen Post-Eintrag '{post_key}' in Thema '{thread_id}' für Prompt-Erstellung.")

        sorted_posts_for_prompt = sorted(valid_posts_for_prompt, key=lambda item: item[2])

        # --- Build the prompt content ---
        last_thought_number = 0 # Track the last thought number assigned
        for post_key, post_data, post_date_obj in sorted_posts_for_prompt:
            article = post_data.get('article', '').strip()
            member_quotes = post_data.get('memberquotes', {})
            simple_quotes = post_data.get('quotes', []) # Assuming quotes is a list of strings
            post_links = post_data.get('links', [])

            current_post_content = []
            has_article_in_this_post = False
            current_thought_number = last_thought_number # Use last number unless article bumps it

            # 1. Add "Mein Gedanke" section if article exists
            if article:
                post_counter += 1
                current_thought_number = post_counter # Assign new number
                date_str = post_date_obj.strftime('%d.%m.%Y') if post_date_obj != datetime.max.date() else post_data.get('date', 'Datum unbekannt')
                current_post_content.append(f"## Mein Gedanke {current_thought_number} ({date_str})\n{article}")
                has_article_in_this_post = True
                last_thought_number = current_thought_number # Update last assigned number

            # 2. Add "Kontext" section if quotes exist
            context_parts = []
            if isinstance(member_quotes, dict):
                context_parts.extend([f"- Zitat von Mitglied: {text.strip()}" for text in member_quotes.values() if isinstance(text, str) and text.strip()])
            if isinstance(simple_quotes, list): # Handle potential simple quotes list
                 context_parts.extend([f"- Zitat: {text.strip()}" for text in simple_quotes if isinstance(text, str) and text.strip()])

            if context_parts:
                 # Refer to the last relevant thought number
                 context_header = f"\n### Kontext zu Gedanke {last_thought_number}" if last_thought_number > 0 else "\n### Kontext (ohne direkten Gedankenzuordnung)"
                 current_post_content.append(context_header + "\n" + "\n".join(context_parts))


            # 3. Add the collected content for this post if any
            if current_post_content:
                 user_prompt_parts.extend(current_post_content)
                 user_prompt_parts.append("\n---\n") # Separator between posts

            # 4. Collect links
            if isinstance(post_links, list):
                 links.update(link for link in post_links if isinstance(link, str) and link.strip())


        # Clean up the final prompt
        if user_prompt_parts and user_prompt_parts[-1] == "\n---\n":
            user_prompt_parts.pop() # Remove trailing separator

        final_user_prompt = "".join(user_prompt_parts).strip()

        # Check if the prompt has meaningful content beyond the title
        # Count lines excluding the title line and empty lines
        meaningful_lines = [line for line in final_user_prompt.splitlines()[1:] if line.strip()]
        if not meaningful_lines:
            logging.warning(f"Thema '{thread_id}' ({title}) hat keinen substantiellen Inhalt für den LLM-Prompt (nur Titel oder leer). Überspringe.")
            continue

        requests.append({
            "thread_id": thread_id,
            "title": title,
            "category": category,
            "system_prompt": system_prompt,
            "user_prompt": final_user_prompt,
            "links": sorted(list(links))
        })

    logging.info(f"{len(requests)} LLM-Anfragen vorbereitet.")
    return requests

def save_llm_output(title, category, output_text, links, base_dir):
    """Saves the LLM output to a Markdown file."""
    sanitized_title = sanitize_filename(title)
    output_path = base_dir / (sanitized_title + '.md')

    # Check for existence *before* attempting to write
    if output_path.exists():
        logging.warning(f"Datei '{output_path}' existiert bereits. Überspringe Speichern.")
        return False # Indicate skipped due to existence

    try:
        # Ensure the output directory exists
        base_dir.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            # Write the main LLM output
            f.write(output_text if output_text else "[Leere LLM Antwort erhalten]")
            f.write("\n\n---\n") # Separator

            # Write metadata (category)
            f.write(f"\n#{category}\n") # Add category as a tag

            # Write collected links
            if links:
                f.write("\n## Links\n")
                for link in links:
                    f.write(f"- {link}\n")

        logging.info(f"Ausgabe für '{title}' erfolgreich gespeichert in '{output_path}'.")
        return True # Indicate successful save

    except IOError as e:
         logging.error(f"E/A-Fehler beim Speichern von '{output_path}': {e}")
         return False
    except Exception as e:
        logging.error(f"Allgemeiner Fehler beim Speichern der Ausgabe für '{title}' in '{output_path}': {e}")
        return False # Indicate failed save

# --- Angepasste LLM-Aufruffunktion ---
def invoke_langchain_llm(system_prompt, user_prompt):
    """Ruft das konfigurierte LLM (Gemini oder Ollama) über LangChain auf."""
    global LLM_PROVIDER, MODEL_NAME, GEMINI_API_KEY, OLLAMA_BASE_URL, GEMINI_AVAILABLE, OLLAMA_AVAILABLE

    # --- Pre-checks ---
    if not MODEL_NAME:
        logging.error("FEHLER: Umgebungsvariable 'MODEL_NAME' ist nicht gesetzt.")
        return "[FEHLER: Modellname fehlt in .env]"

    logging.info(f"Versuche LLM-Aufruf mit Provider: {LLM_PROVIDER}, Modell: {MODEL_NAME}")
    llm = None
    temperature = 0.7 # Standard-Temperatur, kann angepasst werden

    try:
        # --- Gemini Pfad ---
        if LLM_PROVIDER == "gemini":
            if not GEMINI_AVAILABLE: # Checks if API key was loaded and module imported
                logging.error("FEHLER: Gemini ist konfiguriert, aber nicht verfügbar (API-Schlüssel fehlt oder Importfehler).")
                return "[FEHLER: Gemini nicht verfügbar]"

            generation_config = {"temperature": temperature, "top_p": 0.95} # Example config
            # Configure safety settings to be less restrictive if needed
            safety_settings = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }
            llm = ChatGoogleGenerativeAI(
                model=MODEL_NAME,
                google_api_key=GEMINI_API_KEY,
                generation_config=generation_config,
                safety_settings=safety_settings,
                # Optional: Set request options like timeout
                # client_options={"api_endpoint": "generativelanguage.googleapis.com"},
                # request_options={"timeout": 600} # Example: 10 minute timeout
            )
            logging.info(f"Verwende Gemini ({MODEL_NAME}) via LangChain.")

        # --- Ollama Pfad ---
        elif LLM_PROVIDER == "ollama":
            if not OLLAMA_AVAILABLE: # Checks if module was imported
                 logging.error("FEHLER: Ollama ist konfiguriert, aber nicht verfügbar (langchain-ollama fehlt oder Importfehler).")
                 return "[FEHLER: Ollama-Modul nicht verfügbar]"
            if not OLLAMA_BASE_URL:
                 # Should not happen due to default, but check anyway
                 logging.error("FEHLER: Ollama ist konfiguriert, aber 'OLLAMA_BASE_URL' fehlt!")
                 return "[FEHLER: Ollama Base URL fehlt]"

            llm = ChatOllama(
                base_url=OLLAMA_BASE_URL,
                model=MODEL_NAME,
                temperature=temperature,
                # Optional: Add other Ollama parameters if needed
                # num_ctx=4096, # Example context window size
                # request_timeout=300.0 # Example: 5 minute timeout
            )
            logging.info(f"Verwende Ollama ({MODEL_NAME}) unter {OLLAMA_BASE_URL} via LangChain.")

        # --- Unbekannter Provider ---
        else:
            logging.error(f"FEHLER: Unbekannter LLM_PROVIDER '{LLM_PROVIDER}' in .env konfiguriert.")
            return f"[FEHLER: Unbekannter Provider '{LLM_PROVIDER}']"

        # --- Gemeinsamer Aufruf ---
        messages = []
        if system_prompt and system_prompt.strip():
             messages.append(SystemMessage(content=system_prompt))
        # Ensure user_prompt is not empty before adding
        if user_prompt and user_prompt.strip():
             messages.append(HumanMessage(content=user_prompt))
        else:
            logging.error("FEHLER: User-Prompt ist leer. Kann LLM nicht aufrufen.")
            return "[FEHLER: Leerer User-Prompt]"

        if not messages:
             logging.error("FEHLER: Keine Nachrichten (System oder User) für den LLM-Aufruf vorhanden.")
             return "[FEHLER: Keine Nachrichten für LLM]"


        logging.info(f"Sende Anfrage an {LLM_PROVIDER} ({MODEL_NAME})...")
        start_time = time.time()
        response = llm.invoke(messages)
        end_time = time.time()
        duration = end_time - start_time
        logging.info(f"Antwort von {LLM_PROVIDER} erhalten (Dauer: {duration:.2f}s).")


        # Extract content safely
        generated_text = getattr(response, 'content', '')

        if not generated_text or not generated_text.strip():
            logging.warning(f"LangChain LLM ({LLM_PROVIDER}) hat leeren oder nur Whitespace-Text zurückgegeben.")
            return "" # Return empty string for empty/whitespace response
        else:
             # Log only a preview of the response
             log_preview = (generated_text[:150] + '...') if len(generated_text) > 150 else generated_text
             logging.info(f"LLM-Antwort (Vorschau): {log_preview.replace(os.linesep, ' ')}") # Replace newlines for compact log
             return generated_text.strip() # Return stripped text

    except Exception as e:
        logging.error(f"Schwerwiegender Fehler beim Aufruf des LangChain LLM ({LLM_PROVIDER}): {e}", exc_info=True)
        # Provide more specific hints based on provider and error type
        error_message = f"[FEHLER bei LLM-Aufruf ({LLM_PROVIDER}): {type(e).__name__}]"
        if LLM_PROVIDER == "ollama":
             if "Connection refused" in str(e) or "failed to connect" in str(e).lower():
                 logging.error(f"-> Ollama Fehler: Kann keine Verbindung zu '{OLLAMA_BASE_URL}' herstellen. Läuft der Ollama-Server?")
                 error_message += " (Connection refused)"
             elif "404" in str(e) and "model" in str(e).lower():
                 logging.error(f"-> Ollama Fehler: Modell '{MODEL_NAME}' nicht gefunden. Wurde es mit 'ollama pull {MODEL_NAME}' heruntergeladen?")
                 error_message += " (Model not found)"
             elif "timeout" in str(e).lower():
                  logging.error(f"-> Ollama Fehler: Zeitüberschreitung bei der Anfrage. Modell könnte sehr beschäftigt sein oder Anfrage zu komplex.")
                  error_message += " (Timeout)"
        elif LLM_PROVIDER == "gemini":
             if "API key not valid" in str(e):
                 logging.error("-> Gemini Fehler: API-Schlüssel ist ungültig. Bitte GEMINI_API_KEY in .env prüfen.")
                 error_message += " (Invalid API Key)"
             elif "permission denied" in str(e).lower() or "quota" in str(e).lower():
                 logging.error("-> Gemini Fehler: Möglicherweise Berechtigungsproblem oder API-Kontingent überschritten.")
                 error_message += " (Permission/Quota Issue)"
             elif "DeadlineExceeded" in str(e) or "timeout" in str(e).lower():
                 logging.error(f"-> Gemini Fehler: Zeitüberschreitung bei der Anfrage. Netzwerkproblem oder Anfrage zu komplex?")
                 error_message += " (Timeout/Deadline Exceeded)"
             elif "Safety feedback" in str(e) or "blocked" in str(e).lower():
                  logging.error(f"-> Gemini Fehler: Inhalt wurde aufgrund von Sicherheitseinstellungen blockiert. Safety Settings im Skript sind auf BLOCK_NONE, prüfe Prompt-Inhalt oder API-Einstellungen.")
                  error_message += " (Blocked by Safety Filter)"


        return error_message # Return specific error message


# --- Hauptfunktion (main) ---
def main():
    """Hauptfunktion des Skripts."""
    global LLM_PROVIDER, MODEL_NAME, GEMINI_API_KEY, OLLAMA_BASE_URL, GEMINI_AVAILABLE, OLLAMA_AVAILABLE

    # --- Initial Configuration Check ---
    print("\n--- LLM Konfigurationsprüfung ---")
    print(f"Provider (.env): {LLM_PROVIDER}")
    if not MODEL_NAME:
        print("FEHLER: 'MODEL_NAME' fehlt in der .env Datei!")
        logging.error("FEHLER: Umgebungsvariable 'MODEL_NAME' fehlt!")
        return
    print(f"Modell (.env):   {MODEL_NAME}")

    config_ok = False
    if LLM_PROVIDER == "gemini":
        if not GEMINI_API_KEY:
            print("FEHLER: Provider ist 'gemini', aber 'GEMINI_API_KEY' fehlt in .env!")
            # Error already logged during import check
        elif not GEMINI_AVAILABLE:
             print("FEHLER: Provider ist 'gemini', aber benötigte Pakete fehlen (langchain-google-genai?). Siehe Log.")
        else:
            print("API Key:      Vorhanden (Gemini)")
            print("Pakete:       OK (Gemini)")
            config_ok = True
    elif LLM_PROVIDER == "ollama":
        if not OLLAMA_AVAILABLE:
             print("FEHLER: Provider ist 'ollama', aber benötigtes Paket 'langchain-ollama' fehlt oder konnte nicht importiert werden.")
             print("        -> Bitte installieren: pip install langchain-ollama")
             # Error already logged during import check
        else:
            print(f"Basis URL:    {OLLAMA_BASE_URL} (Ollama)")
            print("Pakete:       OK (Ollama)")
            # Zusätzlich prüfen, ob Ollama Server läuft (optional, einfacher Test)
            try:
                 import requests
                 response = requests.get(OLLAMA_BASE_URL, timeout=2)
                 if response.status_code == 200:
                      print("Server Status: Erreichbar")
                      config_ok = True
                 else:
                      print(f"Server Status: Nicht erreichbar (Status: {response.status_code})")
                      logging.warning(f"Ollama Server unter {OLLAMA_BASE_URL} antwortet nicht wie erwartet (Status: {response.status_code}).")

            except ImportError:
                 print("Server Status: 'requests' Paket nicht installiert, kann Status nicht prüfen.")
                 config_ok = True # Assume ok if requests isn't available for check
            except requests.exceptions.ConnectionError:
                 print(f"Server Status: Nicht erreichbar (Verbindungsfehler zu {OLLAMA_BASE_URL})")
                 logging.warning(f"Ollama Server unter {OLLAMA_BASE_URL} nicht erreichbar.")
            except requests.exceptions.Timeout:
                 print(f"Server Status: Zeitüberschreitung bei Verbindung zu {OLLAMA_BASE_URL}")
                 logging.warning(f"Zeitüberschreitung bei Verbindung zu Ollama Server {OLLAMA_BASE_URL}.")
            except Exception as e:
                 print(f"Server Status: Fehler beim Prüfen ({type(e).__name__})")
                 logging.warning(f"Fehler beim Prüfen des Ollama Servers: {e}")


    else:
        print(f"FEHLER: Unbekannter LLM_PROVIDER '{LLM_PROVIDER}' in .env konfiguriert!")
        # Error already logged during import check

    print("---------------------------------")
    if not config_ok:
         print("Konfiguration unvollständig oder fehlerhaft. Skript wird beendet.")
         return


    # --- Intermediate File Handling ---
    skip_filtering = False
    data_source_file = INPUT_JSON_FILE # Default source
    intermediate_file_path = Path(INTERMEDIATE_JSON_FILE)

    if intermediate_file_path.exists():
        print(f"\nZwischendatei '{INTERMEDIATE_JSON_FILE}' gefunden.")
        while True:
            # Updated choices for clarity
            choice = input("Aktion? [(v)erwenden, (e)rsetzen & neu filtern, (b)eenden]: ").lower()
            if choice == 'v':
                data_source_file = INTERMEDIATE_JSON_FILE
                skip_filtering = True
                logging.info(f"Verwende vorhandene Zwischendatei: {INTERMEDIATE_JSON_FILE}")
                break
            elif choice == 'e':
                data_source_file = INPUT_JSON_FILE
                skip_filtering = False
                logging.info(f"Ersetze Zwischendatei. Lade Originaldaten: {INPUT_JSON_FILE}")
                try: # Attempt to delete the old intermediate file
                     intermediate_file_path.unlink()
                     logging.info(f"Alte Zwischendatei '{INTERMEDIATE_JSON_FILE}' gelöscht.")
                except OSError as e:
                     logging.warning(f"Konnte alte Zwischendatei '{INTERMEDIATE_JSON_FILE}' nicht löschen: {e}")
                break
            elif choice == 'b':
                print("Skript beendet.")
                logging.info("Benutzer hat Skript über Zwischendatei-Auswahl beendet.")
                return
            else:
                print("Ungültige Wahl. Bitte 'v', 'e' oder 'b' eingeben.")
    else:
        logging.info(f"Keine Zwischendatei '{INTERMEDIATE_JSON_FILE}' gefunden. Lade Originaldaten: {INPUT_JSON_FILE}")
        data_source_file = INPUT_JSON_FILE
        skip_filtering = False

    # --- Load Initial Data ---
    initial_data = load_data(data_source_file)
    if initial_data is None:
        print(f"Konnte Daten aus '{data_source_file}' nicht laden. Skript wird beendet.")
        return # Exit if loading failed

    # --- Main Processing Loop (allows restarting filtering) ---
    while True:
        processed_data = copy.deepcopy(initial_data) # Work on a copy

        # --- Filtering Stage ---
        if not skip_filtering:
            print("\n--- Datenfilterung ---")
            original_thread_count = len(processed_data)

            # 1. Date Range Filter (Applied First - potentially removes most posts)
            print("Datumsbereich (leer lassen für keine Grenze):")
            start_date = get_date_input("  Startdatum (einschließlich DD.MM.YYYY): ")
            end_date = get_date_input("  Enddatum (einschließlich DD.MM.YYYY):   ")
            processed_data = filter_by_date_range(processed_data, start_date, end_date)
            logging.info(f"Nach Datumsfilter: {len(processed_data)} von {original_thread_count} Themen übrig.")

            # 2. Split by Time Gap Filter
            print("\nThemen für Zeitlückenprüfung (kommasepariert: Kategorie/IDs ODER '*alle*'):")
            filter_list = get_comma_separated_list("  Auswahl (leer=kein Split): ")
            days_threshold = 0
            if filter_list:
                days_threshold = get_int_threshold("  Max. Tage Lücke für Split (0=kein Split): ", 0)
                if days_threshold > 0:
                    processed_data = split_threads_by_time_gap(processed_data, filter_list, days_threshold)
                    logging.info(f"Nach Zeitlücken-Split: {len(processed_data)} Themen vorhanden.")
                else:
                     logging.info("Zeitlücken-Split übersprungen (Schwellenwert=0).")

            # 3. Total Article Length Filter
            length_threshold = get_int_threshold("Min. Artikel-Gesamtlänge pro Thema (0=kein Filter): ", 0)
            processed_data = filter_by_total_article_length(processed_data, length_threshold)
            logging.info(f"Nach Artikellängenfilter: {len(processed_data)} Themen übrig.")

            # 4. Member Quote Length Filter
            memberquote_threshold = get_int_threshold("Min. Länge einzelner Mitgliedszitate (0=kein Filter): ", 0)
            processed_data = filter_by_memberquote_length(processed_data, memberquote_threshold)
            logging.info(f"Nach Zitatlängenfilter: {len(processed_data)} Themen übrig.")


            print("----------------------")
            logging.info("Filterung abgeschlossen.")

            # --- Save Intermediate Results ---
            if save_data(processed_data, INTERMEDIATE_JSON_FILE):
                logging.info(f"Gefilterte Daten erfolgreich in '{INTERMEDIATE_JSON_FILE}' gespeichert.")
            else:
                 # Warn if saving fails, but continue processing
                 logging.warning(f"Konnte gefilterte Daten nicht in '{INTERMEDIATE_JSON_FILE}' speichern. Verarbeitung geht weiter.")

        else: # skip_filtering == True
            print(f"\nFilterung übersprungen, '{INTERMEDIATE_JSON_FILE}' wird verwendet.")
            logging.info(f"Filterung übersprungen, verwende Daten aus {INTERMEDIATE_JSON_FILE}.")

        # --- Prepare for LLM ---
        final_thread_count = len(processed_data)
        print(f"\n--- Zusammenfassung nach Filterung ---")
        print(f"Themen zur LLM-Verarbeitung: {final_thread_count}")

        if final_thread_count == 0:
            print("Keine Themen nach Filterung übrig.")
            while True:
                action_empty = input("Aktion? [(n)eu filtern, (b)eenden]: ").lower()
                if action_empty == 'n':
                    # Reset state to re-filter from original file
                    skip_filtering = False
                    data_source_file = INPUT_JSON_FILE
                    initial_data = load_data(data_source_file)
                    if initial_data is None: return # Exit if reload fails
                    break # Break inner loop, outer loop will restart filtering
                elif action_empty == 'b':
                    print("Skript beendet.")
                    return
                else: print("Ungültige Wahl.")
            if action_empty == 'n': continue # Restart outer loop for filtering

        # --- Load System Prompt & Prepare Requests ---
        system_prompt = load_system_prompt()
        llm_requests = prepare_llm_requests(processed_data, system_prompt)

        if not llm_requests:
            print("Keine LLM-Anfragen vorbereitet (möglicherweise nur leere Themen oder Fehler bei Vorbereitung).")
            while True:
                action_empty_req = input("Aktion? [(n)eu filtern, (b)eenden]: ").lower()
                if action_empty_req == 'n':
                    skip_filtering = False; data_source_file = INPUT_JSON_FILE
                    initial_data = load_data(data_source_file)
                    if initial_data is None: return
                    break # Break inner loop, outer loop will restart
                elif action_empty_req == 'b':
                    print("Skript beendet."); return
                else: print("Ungültige Wahl.")
            if action_empty_req == 'n': continue # Restart outer loop

        print(f"{len(llm_requests)} LLM-Anfragen bereit zum Senden.")

        # --- User Confirmation to Send to LLM ---
        while True:
            action_send = input("Anfragen an LLM senden? [(j)a, (n)eu filtern, (b)eenden]: ").lower()
            if action_send == 'j':
                # --- LLM Processing Stage ---
                print("\n--- Starte LLM-Verarbeitung ---")
                script_dir = Path(__file__).parent
                output_dir = script_dir.parent # Output in the parent directory (e.g., Zettelkasten/)
                logging.info(f"Ausgaben werden in das Verzeichnis '{output_dir}' gespeichert.")

                processed_count, skipped_exist_count, error_count = 0, 0, 0
                total_requests = len(llm_requests)

                for i, request in enumerate(llm_requests):
                    req_title = request.get('title', 'Unbekannter Titel')
                    req_id = request.get('thread_id', 'Unbekannte ID')
                    print(f"\n[{i+1}/{total_requests}] Verarbeite: '{req_title}' ({req_id})")
                    logging.info(f"Starte Verarbeitung für Request {i+1}/{total_requests}: '{req_title}' ({req_id})")

                    # Check if output file already exists
                    output_path_check = output_dir / (sanitize_filename(req_title) + '.md')
                    if output_path_check.exists():
                        skipped_exist_count += 1
                        logging.warning(f"Datei '{output_path_check}' existiert bereits für Titel '{req_title}'. Überspringe LLM-Aufruf und Speichern.")
                        print(f"  -> ÜBERSPRUNGEN (Datei existiert bereits)")
                        continue # Skip to the next request

                    # --- Invoke LLM ---
                    llm_output = invoke_langchain_llm(request['system_prompt'], request['user_prompt'])
                    # --- End LLM Invocation ---

                    # Check for errors or empty output from LLM
                    if not llm_output or llm_output.startswith("[FEHLER"):
                        error_count += 1
                        # Error message already logged by invoke_langchain_llm
                        print(f"  -> FEHLER oder leere Antwort vom LLM. Nicht gespeichert. Siehe Log für Details.")
                        logging.error(f"Fehler oder leere Antwort vom LLM für '{req_title}'. Ergebnis: {llm_output}")
                        # Optional: Add a longer delay after errors?
                        time.sleep(2) # Slightly longer pause after an error
                    else:
                        # --- Save LLM Output ---
                        save_success = save_llm_output(
                            req_title,
                            request['category'],
                            llm_output,
                            request['links'],
                            output_dir
                        )
                        if save_success:
                            processed_count += 1
                            print(f"  -> ERFOLGREICH gespeichert in '{output_path_check.name}'.")
                        else:
                            error_count += 1
                            # Error message already logged by save_llm_output
                            print(f"  -> FEHLER beim Speichern der LLM-Antwort. Siehe Log.")
                            time.sleep(1) # Pause after save error

                    # --- Delay between requests ---
                    # Add a small delay to avoid overwhelming APIs or local server
                    delay_seconds = 1.5
                    logging.debug(f"Warte {delay_seconds}s vor der nächsten Anfrage...")
                    time.sleep(delay_seconds)


                # --- Processing Finished ---
                print("\n--- LLM-Verarbeitung abgeschlossen ---")
                print(f"Erfolgreich verarbeitet & gespeichert: {processed_count}")
                print(f"Übersprungen (Datei existierte):     {skipped_exist_count}")
                print(f"Fehler (LLM oder Speichern):         {error_count}")
                print("--------------------------------------")
                return # Exit script successfully after processing

            elif action_send == 'n':
                print("\nFilterung wird neu gestartet...")
                skip_filtering = False; data_source_file = INPUT_JSON_FILE
                initial_data = load_data(data_source_file)
                if initial_data is None: return # Exit if reload fails
                break # Exit inner loop, outer loop restarts filtering

            elif action_send == 'b':
                print("Skript vor LLM-Verarbeitung beendet.")
                logging.info("Benutzer hat Skript vor dem Senden an LLM beendet.")
                return # Exit script

            else:
                print("Ungültige Wahl. Bitte 'j', 'n' oder 'b' eingeben.")
        # End of 'action_send' loop

        # If 'n' was chosen in action_send, the 'continue' jumps here to restart outer loop
        if action_send == 'n':
            continue
        else:
            # Should only be reached if 'j' or 'b' was chosen, which include returns.
            # Added as a safeguard.
            break

# --- Script Entry Point ---
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nSkript durch Benutzer unterbrochen (Strg+C).")
        logging.info("Skript durch Benutzer unterbrochen (KeyboardInterrupt).")
    except Exception as e:
        logging.exception("Ein unerwarteter Fehler ist im Hauptprogramm aufgetreten:")
        print(f"\nFATALER FEHLER: {e}")
        print("Siehe Logdatei '{LOG_FILE}' für Details.")
