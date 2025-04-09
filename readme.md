#  Dokumentation: allmy_notes

Dieses Python-Skript dient dazu, exportierte Beitragsdaten aus Allmystery (im JSON-Format) aufzubereiten, optional zu filtern und anschließend mithilfe eines Large Language Models (LLM) – entweder über die Google Gemini API oder einen lokalen Ollama-Server (via LangChain) – zu einem zusammenhängenden Text pro Thema zu synthetisieren. Die Ergebnisse werden als Markdown-Dateien gespeichert.

**Inhaltsverzeichnis:**

1.  [Zweck](#zweck)
2.  [Abhängigkeiten & Installation](#abhängigkeiten--installation)
3.  [Konfiguration](#konfiguration)
    *   [`.env`-Datei](#env-datei)
    *   [Skript-Konstanten](#skript-konstanten)
4.  [Benötigte Dateien & Dateistruktur](#benötigte-dateien--dateistruktur)
5.  [Datensammlung mit Tampermonkey (allmy\_monkey.js)](#datensammlung-mit-tampermonkey-allmy_monkeyjs)
6.  [Funktionsweise / Workflow](#funktionsweise--workflow)
7.  [Beschreibung der Kernfunktionen](#beschreibung-der-kernfunktionen)
8.  [Anwendung / Ausführung](#anwendung--ausführung)

---

## 1. Zweck

Das Hauptziel des Skripts ist die Transformation von fragmentierten Forenbeiträgen zu einem bestimmten Thema in einen oder mehrere kohärente, gut lesbare Texte. Dies umfasst:

*   **Einlesen** der exportierten Allmystery-Daten (`allmystery.json`).
*   **Optionale Filterung** der Daten basierend auf Benutzerkriterien (Gesamtlänge, Zitatlänge, Datum, Themenauswahl für Aufteilung).
*   **Optionale Aufteilung** von langen Themen in mehrere Teile, wenn zwischen den Beiträgen große Zeitlücken bestehen.
*   **Zwischenspeicherung** der gefilterten/aufgeteilten Daten (`allmy_llm_input.json`), um wiederholte Filterung zu vermeiden.
*   **Aufbereitung** der relevanten Daten (Titel, Beiträge, Kontext-Zitate) in einem strukturierten Format als Prompt für ein LLM.
*   **Aufruf** eines konfigurierten LLM (Google Gemini API oder Ollama) über das LangChain-Framework zur Textgenerierung.
*   **Speicherung** der vom LLM generierten Texte als einzelne Markdown-Dateien im übergeordneten Verzeichnis, inklusive Metadaten (Kategorie) und gesammelten Links.

---

## 2. Abhängigkeiten & Installation

Das Skript benötigt Python 3 und mehrere externe Bibliotheken.

1.  **Python:** Stellen Sie sicher, dass Python 3 installiert ist (Version 3.9 oder höher empfohlen).
2.  **Bibliotheken installieren:** Öffnen Sie Ihr Terminal oder Ihre Eingabeaufforderung und installieren Sie die benötigten Pakete mit pip:

    ```bash
    # Kernbibliotheken + Gemini + Ollama + Hilfsprogramme
    pip install langchain python-dotenv langchain-google-genai langchain-google-vertexai google-generativeai langchain-ollama requests
    ```

    *   `langchain`: Das Kern-Framework für die LLM-Interaktion.
    *   `python-dotenv`: Zum Laden von Umgebungsvariablen (wie API-Schlüssel, Provider) aus einer `.env`-Datei.
    *   `langchain-google-genai`: Spezifische Integration für Google Generative AI Modelle (wie Gemini).
    *   `langchain-google-vertexai`: Wird hier für die `HarmCategory` und `HarmBlockThreshold` Enums benötigt.
    *   `google-generativeai`: Die zugrundeliegende Google AI SDK, oft als Abhängigkeit benötigt.
    *   `langchain-ollama`: Spezifische Integration für die Interaktion mit lokalen LLMs über Ollama.
    *   `requests`: Wird zur optionalen Prüfung der Ollama-Server-Erreichbarkeit verwendet.

3.  **Ollama (Optional):** Wenn Sie Ollama verwenden möchten (`LLM_PROVIDER="ollama"`), stellen Sie sicher, dass Ollama installiert ist, läuft und das gewünschte Modell (z.B. mit `ollama pull <modellname>`) heruntergeladen wurde. Siehe [ollama.com](https://ollama.com/).
4.  **Tampermonkey (für Datensammlung):** Siehe Abschnitt [Datensammlung mit Tampermonkey](#datensammlung-mit-tampermonkey-allmy_monkeyjs).

---

## 3. Konfiguration

Die Konfiguration erfolgt über eine `.env`-Datei und einige Konstanten am Anfang des Skripts.

### `.env`-Datei

Erstellen Sie im selben Verzeichnis wie das Skript (`.allmystery/`) eine Datei namens `.env`. 

*   **`LLM_PROVIDER`**: Legt fest, ob `gemini` oder `ollama` verwendet wird.
*   **`MODEL_NAME`**: Das spezifische Modell, das für den gewählten Provider genutzt werden soll. Stellen Sie sicher, dass das Modell für den Provider verfügbar ist (bei Ollama: ggf. `ollama pull <modellname>` ausführen).
*   **`GEMINI_API_KEY`**: (Nur für Gemini) Ihr persönlicher API-Schlüssel für die Google AI / Gemini API.
*   **`OLLAMA_BASE_URL`**: (Nur für Ollama) Die Adresse Ihres laufenden Ollama-Servers.

### Skript-Konstanten

Am Anfang des Python-Skripts sind folgende Dateinamen definiert:

*   **`INPUT_JSON_FILE`**: Name der Eingabedatei mit den Allmystery-Daten (Standard: `allmystery.json`).
*   **`INTERMEDIATE_JSON_FILE`**: Name der Datei, in der die gefilterten Daten zwischengespeichert werden (Standard: `allmy_llm_input.json`).
*   **`SYSTEM_PROMPT_FILE`**: Name der Datei, die die allgemeinen Anweisungen (System Prompt) für das LLM enthält (Standard: `allmy_prompt.md`).
*   **`LOG_FILE`**: Name der Log-Datei, in die detaillierte Informationen über den Skriptablauf geschrieben werden (Standard: `allmy_log.log`).

---

## 4. Benötigte Dateien & Dateistruktur

Für die Ausführung des Skripts wird folgende Struktur im Verzeichnis `Zettelkasten/` erwartet:

```
Zettelkasten/
├── .allmystery/             # Verzeichnis für das Skript und seine Daten
│   ├── allmy_notes.py         # Dieses Python-Skript
│   ├── allmy_monkey.js      # (Optional) Tampermonkey-Skript zur Datensammlung
│   ├── allmystery.json      # Ihre exportierten Allmystery-Daten (von allmy_monkey.js erzeugt)
│   ├── allmy_prompt.md      # Ihr System-Prompt für das LLM
│   ├── .env                 # Ihre LLM-Konfiguration (NICHT einchecken!)
│   ├── allmy_llm_input.json # (Wird vom Skript erstellt/verwendet)
│   └── allmy_log.log        # (Wird vom Skript erstellt/überschrieben)
│
└── (Hier werden die .md Output-Dateien gespeichert)
```

*   Das Python-Skript (`allmy_notes.py`), die Eingabe-JSON (`allmystery.json`), der System-Prompt (`allmy_prompt.md`), die `.env`-Datei und optional das Tampermonkey-Skript (`allmy_monkey.js`) sollten sich im Unterordner `.allmystery` befinden.
*   Die vom LLM generierten Markdown-Dateien werden im übergeordneten Ordner (`Zettelkasten/`) gespeichert.

---

## 5. Datensammlung mit Tampermonkey (`allmy_monkey.js`)

Die Eingabedatei `allmystery.json` enthält Ihre persönlichen Beiträge aus dem Allmystery-Forum. Um diese Daten zu sammeln, können Sie das bereitgestellte Userskript `allmy_monkey.js` in Verbindung mit der Browser-Erweiterung **Tampermonkey** verwenden.

**Voraussetzungen:**

*   Ein Webbrowser, der Tampermonkey unterstützt (z.B. Firefox, Chrome, Edge, Opera). Getestet mit Firefox.
*   Die Tampermonkey Browser-Erweiterung muss installiert sein. Sie finden sie über die Add-on-/Erweiterungs-Stores Ihres Browsers oder auf [tampermonkey.net](https://www.tampermonkey.net/).
*   Fügen Sie `allmy_monkey.js` Tampermonkey hinzu (z.B. über das Tampermonkey-Dashboard -> Utilities -> Import -> Datei auswählen). Stellen Sie sicher, dass das Skript aktiviert ist.

**Datensammlung:**

1.  Navigieren Sie zu Ihrer persönlichen Beitragsübersicht auf Allmystery: `https://www.allmystery.de/ng/mposts`
2.  Unten rechts auf der Webseite erscheint ein **grüner Button**, der vom Tampermonkey-Skript hinzugefügt wurde.
3.  Klicken Sie auf diesen grünen Button, um den Sammelvorgang zu starten.
4.  Das Skript wird nun automatisch Ihre Beiträge sammeln. Dieser Vorgang kann einige Zeit dauern.
5.  Ist der Vorgang beendet, erscheint ein **Fenster mit dem gesammelten Text im JSON-Format**.
6.  **Kopieren Sie den gesamten Text** aus diesem Fenster (z.B. Strg+A, Strg+C).
7.  Erstellen Sie eine neue Textdatei im Verzeichnis `.allmystery/`.
8.  Fügen Sie den kopierten Text in diese neue Datei ein (Strg+V).
9.  Speichern Sie die Datei unter dem exakten Namen `allmystery.json`.

Jetzt haben Sie die benötigte Eingabedatei für das Python-Skript `allmy_llm.py` erstellt.

---

## 6. Funktionsweise / Workflow

Das Python-Skript (`allmy_notes.py`) führt die folgenden Schritte aus:

1.  **Initialisierung:**
    *   Lädt notwendige Bibliotheken.
    *   Konfiguriert das Logging.
    *   Lädt Konfiguration aus `.env`.
    *   Prüft Konfiguration und Paketverfügbarkeit. Bricht bei Fehlern ab.

2.  **Prüfung auf Zwischendatei:**
    *   Sucht nach `INTERMEDIATE_JSON_FILE`.
    *   Fragt Benutzer: verwenden (`v`), ersetzen/neu filtern (`e`), abbrechen (`b`).

3.  **Daten laden:** Lädt `allmystery.json` oder `allmy_llm_input.json`.

4.  **Hauptschleife (für Neustart 'n'):** Ermöglicht erneutes Filtern.
    *   Erstellt tiefe Kopie der Daten.

5.  **Filterung (falls nicht übersprungen):**
    *   Filterabfragen für: Datum, Zeitlücke für Split, Artikellänge, Zitatlänge.
    *   Anwendung der Filter.
    *   Speichert Ergebnis in `INTERMEDIATE_JSON_FILE`.

6.  **Zusammenfassung & LLM-Vorbereitung:**
    *   Zeigt Anzahl verbleibender Themen.
    *   Lädt System-Prompt (`allmy_prompt.md`).
    *   Ruft `prepare_llm_requests` auf, um Anfragen zu erstellen.

7.  **Benutzeraktion (LLM Senden?):**
    *   Fragt: Senden (`j`/`y`), Neu filtern (`n`), Abbrechen (`b`).

8.  **LLM-Verarbeitung (falls `j`/`y`):**
    *   Bestimmt Zielverzeichnis (`Zettelkasten/`).
    *   Iteriert durch Anfragen.
    *   **Existenzprüfung:** Überspringt, wenn Zieldatei existiert.
    *   **API/Server-Aufruf:** Ruft `invoke_langchain_llm` auf.
    *   **Fehlerprüfung:** Prüft LLM-Antwort.
    *   **Speichern:** Ruft `save_llm_output` auf.
    *   Aktualisiert Zähler.

9.  **Abschluss:**
    *   Zeigt Ergebnisstatistik.
    *   Skript endet.

---

## 7. Beschreibung der Kernfunktionen

*   **`load_data`, `save_data`, `get_int_threshold`, `get_date_input`, `get_comma_separated_list`, `parse_date_safe`, `sanitize_filename`:** Hilfsfunktionen für Datei-I/O, Benutzereingaben, Datumsverarbeitung und Dateinamenbereinigung.
*   **`filter_by_...`-Funktionen:** Implementieren die jeweilige Filterlogik.
*   **`split_threads_by_time_gap`:** Teilt Themen bei großen Zeitlücken auf.
*   **`load_system_prompt`:** Lädt den System-Prompt.
*   **`prepare_llm_requests`:** Bereitet die Daten für die LLM-Anfragen auf (formatiert User-Prompts, sammelt Metadaten).
*   **`invoke_langchain_llm(system_prompt, user_prompt)`:** Zentrale Funktion für die LLM-Interaktion mit dem konfigurierten Provider (Gemini oder Ollama).
*   **`save_llm_output`:** Speichert die LLM-Ausgabe als Markdown-Datei.
*   **`main()`:** Hauptfunktion, steuert den Ablauf, prüft Konfiguration, sammelt Benutzereingaben, orchestriert Funktionsaufrufe.

---

## 8. Anwendung / Ausführung

1.  **Datensammlung (einmalig/bei Bedarf):** Sammeln Sie Ihre Beitragsdaten mit Tampermonkey und `allmy_monkey.js` wie in [Abschnitt 5](#datensammlung-mit-tampermonkey-allmy_monkeyjs) beschrieben und speichern Sie sie als `allmystery.json` im `.allmystery`-Ordner.
2.  **Voraussetzungen erfüllen:** Python und Bibliotheken installieren (siehe [Abschnitt 2](#abhängigkeiten--installation)). Ggf. Ollama einrichten.
3.  **Dateien vorbereiten:** Stellen Sie sicher, dass `allmystery.json` und `allmy_prompt.md` im Ordner `.allmystery` vorhanden sind.
4.  **Konfiguration anpassen:** Erstellen/bearbeiten Sie die `.env`-Datei im `.allmystery`-Ordner (siehe [Abschnitt 3](#konfiguration)). Passen Sie `allmy_prompt.md` an.
5.  **Skript starten:** Im Terminal in das Verzeichnis `.allmystery` navigieren und ausführen:
    ```bash
    python allmy_notes.py
    ```
6.  **Anweisungen folgen:** Das Skript führt durch:
    *   Entscheidung über Zwischendatei (`v`/`e`/`b`).
    *   Eingabe der Filter-Schwellenwerte.
    *   Eingabe des Datumsbereichs.
    *   Auswahl der Themen für Aufteilung.
    *   Eingabe der Zeitlücke.
    *   Bestätigung zum Senden an LLM (`j`/`n`/`b`).
7.  **Ergebnisse prüfen:** Generierte `.md`-Dateien im übergeordneten Ordner (`Zettelkasten/`) prüfen. `allmy_log.log` im `.allmystery`-Ordner enthält Details und Fehler.