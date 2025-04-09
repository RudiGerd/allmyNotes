// ==UserScript==
// @name         Allmystery Beiträge nach JSON
// @namespace    http://tampermonkey.net/
// @version      1.7
// @description  Extrahiert Beiträge von Allmystery /ng/mposts und wandelt sie in JSON um, inkl. Paginierung, korrekter Gruppierung und HTML-Bereinigung (Spoiler, Mentions, korrekte Quote-Zusammenführung).
// @author       Deine Wenigkeit (angepasst von AI)
// @match        https://www.allmystery.de/ng/mposts*
// @grant        GM_xmlhttpRequest
// @grant        GM_addStyle
// @connect      www.allmystery.de
// ==/UserScript==

(function() {
    'use strict';

    // --- Konfiguration ---
    const BASE_URL = "https://www.allmystery.de";

    // --- Stil für den Button und das Ausgabefenster ---
    GM_addStyle(`
        /* Stile bleiben unverändert - hier gekürzt */
        #extract-json-button { position: fixed; bottom: 10px; right: 10px; z-index: 9999; padding: 10px 15px; background-color: #4CAF50; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 14px; }
        #extract-json-button:disabled { background-color: #cccccc; cursor: not-allowed; }
        #json-output-container { position: fixed; top: 50px; left: 50%; transform: translateX(-50%); width: 80%; max-width: 800px; height: 70%; max-height: 600px; background-color: #f9f9f9; border: 1px solid #ccc; z-index: 10000; display: none; flex-direction: column; padding: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.2); border-radius: 5px; }
        #json-output-container h3 { margin: 0 0 10px 0; padding-bottom: 5px; border-bottom: 1px solid #ccc; }
        #json-output-textarea { width: 98%; height: calc(100% - 70px); margin: 5px auto; font-family: monospace; font-size: 12px; resize: none; white-space: pre; overflow-wrap: normal; overflow-x: scroll; }
        #json-output-controls { margin-top: 10px; text-align: right; }
        #json-output-controls button { margin-left: 10px; padding: 5px 10px; }
    `);

    // --- Hilfsfunktionen ---
    function getFullUrl(href) {
        if (!href || href.startsWith('#') || href.startsWith('javascript:')) return null;
        if (href.startsWith('http://') || href.startsWith('https://')) return href;
        if (href.startsWith('/')) return BASE_URL + href;
        return BASE_URL + '/' + href;
    }

    /**
     * Bereinigt HTML-String von spezifischen unerwünschten Tags und @Mentions.
     * @param {string} html - Der zu bereinigende HTML-String.
     * @returns {string} - Der bereinigte HTML-String.
     */
    function cleanupHtml(html) {
        if (!html) return '';
    
        // 1. Use DOM manipulation for reliable tag removal first
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = html;
        tempDiv.querySelectorAll('img, i, a[rel]').forEach(el => el.remove());
        let cleanedHtml = tempDiv.innerHTML; // Kann browser-spezifischen Whitespace enthalten
    
        // 2. Remove @Mentions using Regex
        cleanedHtml = cleanedHtml.replace(/@[\w.-]+/g, ''); // Matches @ followed by letters, numbers, _, ., -
    
        // --- Verfeinerte <br> und Whitespace-Behandlung ---
    
        // 3. Normalisieren: <br> Tags und Whitespace darum herum konsistent machen
        //    Ersetzt z.B. "  <br />  " durch ein einfaches "<br>"
        //    Das macht die nachfolgenden Schritte zuverlässiger.
        cleanedHtml = cleanedHtml.replace(/\s*<br\s*\/?>\s*/gi, '<br>');
    
        // 4. Optional: Reduziere 3 oder mehr aufeinanderfolgende <br> auf zwei (falls gewünscht)
        //    Dieser Schritt ist spezifisch für die Formatierung.
        cleanedHtml = cleanedHtml.replace(/(<br>){3,}/gi, '<br><br>');
    
        // 5. Entferne ALLE <br> am Anfang und Ende (iterativ, falls mehrere)
        //    Benötigt danach trim(), um evtl. übrige Leerzeichen zu entfernen
        while (cleanedHtml.toLowerCase().startsWith('<br>')) {
             cleanedHtml = cleanedHtml.substring(4); // Entfernt '<br>' am Anfang
        }
        while (cleanedHtml.toLowerCase().endsWith('<br>')) {
             cleanedHtml = cleanedHtml.substring(0, cleanedHtml.length - 4); // Entfernt '<br>' am Ende
        }
        // Entferne Leerzeichen, die evtl. um die entfernten <br> standen oder generell am Rand sind
        cleanedHtml = cleanedHtml.trim();
    
    
        // 6. Ersetze nun alle VERBLEIBENDEN (inneren) <br> durch ein Leerzeichen.
        //    Dies geschieht NACHDEM die äußeren entfernt wurden.
        cleanedHtml = cleanedHtml.replace(/<br>/gi, ' ');
    
        // 7. Bereinige Whitespace: Kollabiere mehrere Leerzeichen (auch die eben aus <br> erzeugten)
        //    zu einem einzigen und trimme das Endergebnis.
        cleanedHtml = cleanedHtml.replace(/\s+/g, ' ').trim();
    
        return cleanedHtml;
    }

    function extractDataFromNode(doc) {
        const postsData = {};
        const postElements = doc.querySelectorAll('div.main > div.in, div#sftarget > div.in');

        postElements.forEach((postEl, postIndex) => {
            // --- Start: Basic Element Extraction ---
            const enaL = postEl.querySelector('span.ena_l');
            const enaR = postEl.querySelector('span.ena_r');
            const linkEl = enaL ? enaL.querySelector('a') : null;
            const clearBr = postEl.querySelector('br[clear="all"]');
            if (!linkEl || !enaR || !clearBr) {
                console.warn("Skipping post: structure mismatch:", postEl.innerHTML.substring(0, 100));
                return;
            }
            // --- End: Basic Element Extraction ---

            // --- Start: Core Info Extraction ---
            const href = linkEl.getAttribute('href');
            const title = linkEl.textContent.trim();
            const enaRText = enaR.textContent.trim();
            const threadMatch = href.match(/\/themen\/([a-z]+\d+)/i);
            if (!threadMatch) {
                 console.warn("Skipping post: Cannot extract BASE thread ID:", href);
                 return;
            }
            const threadId = threadMatch[1];
            let postKey = href;
            if (postKey && postKey.startsWith('/')) postKey = postKey.substring(1);
            if (!postKey || !postKey.includes('#id')) {
                 console.warn("Skipping post: Cannot determine valid post key:", href);
                 return;
            }
            const metaMatch = enaRText.match(/^([\w\s\/]+?)\s+\/\s*von.*am\s*([\d\.]+)/);
            if (!metaMatch) {
                 console.warn("Skipping post: Cannot extract category/date:", enaRText, "in", postKey);
                 return;
            }
            const category = metaMatch[1].trim();
            const date = metaMatch[2].trim();
            // --- End: Core Info Extraction ---

            // --- Start: Initialize/Update Thread Data ---
            if (!postsData[threadId]) {
                postsData[threadId] = { title: title, category: category, diary: {} };
            } else {
                postsData[threadId].title = title; // Use latest title/cat found
                postsData[threadId].category = category;
            }
            // --- End: Initialize/Update Thread Data ---

            // --- Start: Content Processing Setup ---
            const contentClone = postEl.cloneNode(true);
            contentClone.querySelector('span.ena_l')?.remove();
            contentClone.querySelector('span.ena_r')?.remove();
            contentClone.querySelector('br[clear="all"]')?.remove();
            const links = [];
            const memberquotes = {}; // Reset for each post element!
            const quotes = [];       // Reset for each post element!
            const imageLinkPlaceholders = [];
            // --- End: Content Processing Setup ---

            // --- Step 0: Handle Spoilers ---
            contentClone.querySelectorAll('span.spoiler').forEach(spoiler => {
                const contentSpan = spoiler.querySelector('span.spoilercontent');
                if (spoiler.parentNode) {
                    if (contentSpan) {
                        const fragment = document.createDocumentFragment();
                        while (contentSpan.firstChild) fragment.appendChild(contentSpan.firstChild);
                        spoiler.parentNode.replaceChild(fragment, spoiler);
                    } else { spoiler.remove(); }
                } else { console.warn("Spoiler without parentNode"); }
            });

            // --- Step 1a: Extract <img class="bild"> ---
            contentClone.querySelectorAll('img.bild[src]').forEach(img => {
                const fullUrl = getFullUrl(img.getAttribute('src'));
                if (fullUrl && !links.includes(fullUrl)) links.push(fullUrl);
                img.remove();
            });

            // --- Step 1b: Extract <a> links & handle img-preview ---
            contentClone.querySelectorAll('a[href]').forEach(a => {
                const linkHref = a.getAttribute('href');
                const fullUrl = getFullUrl(linkHref);
                if (a.classList.contains('img-preview') && a.querySelector('img')) {
                    if (fullUrl && !links.includes(fullUrl)) links.push(fullUrl);
                    const placeholderText = `%%IMAGELINK_${postIndex}_${imageLinkPlaceholders.length}%%`;
                    const placeholderNode = document.createTextNode(placeholderText);
                    if (a.parentNode) {
                        a.parentNode.replaceChild(placeholderNode, a);
                        imageLinkPlaceholders.push(placeholderText);
                    } else { console.warn("img-preview link without parentNode"); }
                } else if (fullUrl && !a.closest('blockquote > cite') && !links.includes(fullUrl)) {
                    links.push(fullUrl);
                }
            });

            // --- Step 2: Process blockquotes ---
             // *** Important: Use temporary objects to store quotes for THIS post element ***
             const currentPostMemberQuotes = {};
             const currentPostSimpleQuotes = [];

            contentClone.querySelectorAll('blockquote').forEach(bq => {
                const parentId = bq.dataset.parentId;
                const citationLink = bq.querySelector('cite a.bnu');
                const citeElement = bq.querySelector('cite');
                let quoteContentHtml = bq.innerHTML;
                if (citeElement) quoteContentHtml = quoteContentHtml.replace(citeElement.outerHTML, '').trim();
                else quoteContentHtml = quoteContentHtml.trim();

                const cleanedQuoteContent = cleanupHtml(quoteContentHtml); // Apply cleanup

                if (parentId && citationLink) { // Member Quote
                    let quoteKey = citationLink.getAttribute('href');
                    if (quoteKey && quoteKey.startsWith('/')) quoteKey = quoteKey.substring(1);

                    if (quoteKey && quoteKey.includes('#id')) {
                        // --- MODIFICATION START ---
                        if (cleanedQuoteContent) { // Only process if there's content
                            if (currentPostMemberQuotes[quoteKey]) {
                                // Key exists IN THIS POST'S TEMP OBJECT: append with a space
                                currentPostMemberQuotes[quoteKey] += " " + cleanedQuoteContent;
                            } else {
                                // Key doesn't exist IN THIS POST'S TEMP OBJECT: assign new
                                currentPostMemberQuotes[quoteKey] = cleanedQuoteContent;
                            }
                        }
                        // --- MODIFICATION END ---
                    } else {
                        console.warn("Cannot key member quote:", citationLink.getAttribute('href'));
                        if (cleanedQuoteContent && !currentPostSimpleQuotes.includes(cleanedQuoteContent)) currentPostSimpleQuotes.push(cleanedQuoteContent);
                    }
                } else { // Simple Quote
                    if (cleanedQuoteContent && !currentPostSimpleQuotes.includes(cleanedQuoteContent)) currentPostSimpleQuotes.push(cleanedQuoteContent);
                }
                bq.remove(); // Remove the processed blockquote
            });

            // --- Step 3: Get remaining article HTML ---
            let articleHtml = contentClone.innerHTML.trim();

            // --- Step 4: Replace image placeholders ---
            imageLinkPlaceholders.forEach(placeholder => {
                articleHtml = articleHtml.split(placeholder).join(''); // Replace with nothing
            });

            // --- Step 5: Apply final cleanup to article ---
            const article = cleanupHtml(articleHtml);

            // --- Build Post Entry ---
            const postEntry = { date: date };
            if (article) postEntry.article = article;
            // Add collected quotes from this post element
            if (Object.keys(currentPostMemberQuotes).length > 0) postEntry.memberquotes = currentPostMemberQuotes;
            if (currentPostSimpleQuotes.length > 0) postEntry.quotes = currentPostSimpleQuotes;
            if (links.length > 0) postEntry.links = links;


            // --- Add post to final diary ---
            // Check if the post entry actually contains any data after processing
            if (postEntry.article || postEntry.memberquotes || postEntry.quotes || postEntry.links) {
                if (!postsData[threadId].diary[postKey]) {
                    postsData[threadId].diary[postKey] = postEntry;
                } else {
                    // This case (duplicate postKey) should be rare if keys are unique, but overwrite if needed.
                    console.warn(`Duplicate post key: ${threadId} -> ${postKey}. Overwriting.`);
                    postsData[threadId].diary[postKey] = postEntry;
                }
            } else {
                 console.log(`Skipping empty post after cleanup: ${postKey}`);
            }
        });

        return postsData;
    }

    // --- processAllPages, fetchPage, displayJsonOutput, createUI ---
    // (Diese Funktionen bleiben unverändert)

     async function fetchPage(url) { /* ... unverändert ... */
        console.log("Fetching:", url);
        return new Promise((resolve, reject) => {
            GM_xmlhttpRequest({
                method: "GET", url: url,
                onload: response => {
                    if (response.status >= 200 && response.status < 300) {
                        const parser = new DOMParser();
                        resolve(parser.parseFromString(response.responseText, "text/html"));
                    } else {
                         console.error(`Fetch failed ${url}: ${response.status}`, response);
                         reject(`Fetch failed ${url}: ${response.status}`);
                    }
                },
                onerror: error => { console.error(`Fetch error ${url}`, error); reject(`Fetch error ${url}: ${error}`); },
                ontimeout: () => { console.error(`Fetch timeout ${url}`); reject(`Fetch timeout ${url}`); }
            });
        });
    }

    async function processAllPages(startButton) { /* ... unverändert ... */
        startButton.disabled = true; startButton.textContent = "Verarbeite...";
        let allData = {};
        let currentPageUrl = window.location.href;
        let pageCount = 1;
        const processedUrls = new Set();

        try {
             while (currentPageUrl && !processedUrls.has(currentPageUrl)) {
                 processedUrls.add(currentPageUrl);
                 startButton.textContent = `Verarbeite Seite ${pageCount}...`;
                 console.log(`Processing page ${pageCount}: ${currentPageUrl}`);
                 const doc = pageCount === 1 ? document : await fetchPage(currentPageUrl);
                 const pageData = extractDataFromNode(doc);

                 for (const baseThreadId in pageData) {
                     if (!allData[baseThreadId]) {
                         allData[baseThreadId] = pageData[baseThreadId];
                     } else {
                         Object.assign(allData[baseThreadId].diary, pageData[baseThreadId].diary);
                         allData[baseThreadId].title = pageData[baseThreadId].title;
                         allData[baseThreadId].category = pageData[baseThreadId].category;
                     }
                 }

                const nextLink = doc.querySelector('div.resultpages a[rel="next"]');
                if (nextLink) {
                    currentPageUrl = getFullUrl(nextLink.getAttribute('href'));
                    if (!currentPageUrl) console.log("Next link URL resolution failed:", nextLink.getAttribute('href'));
                    pageCount++;
                    // await new Promise(resolve => setTimeout(resolve, 300)); // Optional delay
                } else {
                    currentPageUrl = null;
                }
            }
             if (currentPageUrl && processedUrls.has(currentPageUrl)) console.warn("Loop detected:", currentPageUrl);

            console.log("Extraction complete. Pages processed:", processedUrls.size);
            startButton.textContent = "Erfolgreich!";
            displayJsonOutput(allData);
        } catch (error) {
            console.error("Extraction process error:", error);
            startButton.textContent = "Fehler!";
            alert("Fehler: " + error);
            startButton.disabled = false; // Re-enable on error
            startButton.textContent = "Beiträge extrahieren";
        } finally {
            // Keep disabled on success, enable on error (handled in catch)
        }
     }

     function displayJsonOutput(data) { /* ... unverändert ... */
        const container = document.getElementById('json-output-container');
        const textarea = document.getElementById('json-output-textarea');
        if (!container || !textarea) { console.error("Output UI not found!"); return; }
         try {
            textarea.value = JSON.stringify(data, null, 2);
            container.style.display = 'flex';
         } catch(e) {
             console.error("JSON stringify error:", e);
             textarea.value = "JSON Error. See console."; container.style.display = 'flex';
         }
    }

    function createUI() { /* ... unverändert ... */
        const button = document.createElement('button');
        button.id = 'extract-json-button'; button.textContent = 'Beiträge extrahieren';
        button.addEventListener('click', () => processAllPages(button));
        document.body.appendChild(button);

        const outputContainer = document.createElement('div');
        outputContainer.id = 'json-output-container';
        const header = document.createElement('h3');
        header.textContent = 'Extrahierte JSON Daten';
        outputContainer.appendChild(header);
        const textarea = document.createElement('textarea');
        textarea.id = 'json-output-textarea'; textarea.readOnly = true;
        outputContainer.appendChild(textarea);
        const controlsDiv = document.createElement('div');
        controlsDiv.id = 'json-output-controls';
        const copyButton = document.createElement('button');
        copyButton.textContent = 'Kopieren';
        copyButton.addEventListener('click', () => {
            textarea.select();
            try {
                copyButton.textContent = document.execCommand('copy') ? 'Kopiert!' : 'Fehler!';
            } catch (err) { copyButton.textContent = 'Fehler!'; console.error('Copy failed', err); }
            textarea.selectionStart = textarea.selectionEnd;
            setTimeout(() => { copyButton.textContent = 'Kopieren'; }, 2000);
        });
        controlsDiv.appendChild(copyButton);
        const closeButton = document.createElement('button');
        closeButton.textContent = 'Schließen';
        closeButton.addEventListener('click', () => { outputContainer.style.display = 'none'; });
        controlsDiv.appendChild(closeButton);
        outputContainer.appendChild(controlsDiv);
        document.body.appendChild(outputContainer);
     }

    // --- Start ---
    if (document.readyState === "complete" || document.readyState === "interactive") {
        createUI();
    } else {
        window.addEventListener('DOMContentLoaded', createUI);
    }

})();