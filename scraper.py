import os
import json
import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from google import genai
from google.genai import types

# 1. YOUR PERSONAL WATCHLIST (Add names of local contractors, MLAs, builders, or towns)
# Any match gets an automatic 10/10 score and bypasses the AI filter.
WATCHLIST = [
    "kundapura", "kundapur", "ಕುಂದಾಪುರ",
    "udupi", "ಉಡುಪಿ", "byndoor", "ಬೈಂದೂರು",
    "nh-66", "nh 66", "pwd", "ಪಿಡಬ್ಲ್ಯೂಡಿ",
    "contractor", "ಗುತ್ತಿಗೆದಾರ", "sand mining", "ಮರಳು"
]

# 2. FREE RSS NEWS SOURCES (English + Kannada Coastal Karnataka + Business + India/World)
RSS_FEEDS = [
    # Local & Coastal Karnataka (English + Kannada)
    ("Daijiworld", "https://www.daijiworld.com/rss/rssfeed.xml"),
    ("Google News - Kundapura/Udupi EN", "https://news.google.com/rss/search?q=Kundapura+OR+Udupi+OR+Mangaluru+infrastructure+OR+PWD&hl=en-IN&gl=IN&ceid=IN:en"),
    ("Google News - Kundapura/Udupi KN", "https://news.google.com/rss/search?q=%E0%B2%95%E0%B3%81%E0%B2%82%E0%B2%A6%E0%B2%BE%E0%B2%AA%E0%B3%81%E0%B2%B0+OR+%E0%B2%89%E0%B2%A1%E0%B3%81%E0%B2%AA%E0%B2%BF&hl=kn&gl=IN&ceid=IN:kn"),
    ("Deccan Herald - Karnataka", "https://www.deccanherald.com/rss/state.rss"),
    # Building Materials, Tax & Trade
    ("Google News - Steel/Cement/GST", "https://news.google.com/rss/search?q=steel+OR+cement+OR+paint+prices+OR+GST+OR+RBI+India&hl=en-IN&gl=IN&ceid=IN:en"),
    ("Economic Times - Economy", "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms"),
    # India & World
    ("The Hindu - National", "https://www.thehindu.com/news/national/feeder/default.rss"),
    ("The Hindu - World", "https://www.thehindu.com/news/international/feeder/default.rss"),
]

def get_og_image(url):
    """Fetches the original article photo (og:image) safely."""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, "html.parser")
        tag = soup.find("meta", property="og:image")
        if tag and tag.get("content") and tag["content"].startswith("http"):
            return tag["content"]
    except Exception:
        pass
    return ""

def fetch_articles():
    """Pulls latest headlines from all RSS feeds and flags Watchlist matches."""
    articles = []
    seen_titles = set()

    for source_name, url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:15]:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                summary = entry.get("summary", "").strip()
                if not title or title.lower() in seen_titles:
                    continue
                seen_titles.add(title.lower())

                combined_text = f"{title} {summary}".lower()
                matched_terms = [w for w in WATCHLIST if w in combined_text]

                articles.append({
                    "source": source_name,
                    "title": title,
                    "summary": BeautifulSoup(summary, "html.parser").get_text()[:400],
                    "link": link,
                    "watchlist_match": len(matched_terms) > 0,
                    "matched_terms": matched_terms[:3]
                })
        except Exception as e:
            print(f"Skipping {source_name}: {e}")

    print(f"Fetched {len(articles)} raw articles.")
    return articles

def curate_with_gemini(articles):
    """Uses Gemini 3.8 Flash to score, translate Kannada->English, deduplicate, and write cards."""
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    # Send up to 80 freshest/watchlist-prioritized articles to stay fast & within free limits
    articles.sort(key=lambda x: x["watchlist_match"], reverse=True)
    batch = articles[:80]

    prompt = f"""
You are the chief editor of 'Notasaara', a personal current affairs briefing for a hardware & building-materials businessman in Kundapura, Karnataka.

Review the following {len(batch)} news items (some are in Kannada—translate and write ALL output in simple, clear English).

RULES:
1. Score each story 1-10 for relevance. KEEP every story scoring 7 or above.
2. WATCHLIST BYPASS: Any item with "watchlist_match": true MUST be kept with score 10.
3. DISCARD celebrity gossip, sports scores, routine political speeches, and petty crime.
4. MERGE duplicates: If multiple items cover the same event, combine them into ONE card and set "verified": true. Otherwise "verified": false.
5. Assign each kept card to ONE of these exact categories (in priority order):
   - "Local" (Kundapura, Udupi, Mangaluru, NH-66, coastal weather/tenders)
   - "People & Risk" (Watchlist matches, PWD/RDPR contractors, pending bills, raids, insolvency, actionable MLA/official news)
   - "Building & Trade" (Steel, cement, paint, PVC, copper, RBI rates, GST, Karnataka real estate)
   - "India & Economy" (Major national policies, Supreme Court, infrastructure)
   - "World & Tech" (Global oil/supply chains, major geopolitics, big AI/tech)
6. Write:
   - "headline": Clear, non-clickbait English headline (max 15 words).
   - "body": 60-80 words in simple, everyday English with key numbers/context.
   - "impact_label": Either "⚠️ Risk / Opportunity", "📌 How This Impacts You", or "💡 Why It Matters".
   - "impact_text": 1-2 crisp sentences. NEVER force a fake hardware connection—if it's general news, use "💡 Why It Matters".

Return ONLY a valid JSON array of objects with these exact keys:
"category", "headline", "body", "impact_label", "impact_text", "source", "link", "watchlist_match", "verified"

NEWS ITEMS:
{json.dumps(batch, ensure_ascii=False)}
"""

    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json"
        )
    )

    cards = json.loads(response.text)

    # Sort cards into the exact 5-category priority order
    order = {"Local": 1, "People & Risk": 2, "Building & Trade": 3, "India & Economy": 4, "World & Tech": 5}
    cards.sort(key=lambda c: (order.get(c.get("category", ""), 99), not c.get("watchlist_match", False)))

    # Fetch original source images for the final shortlisted cards
    for card in cards:
        card["image"] = get_og_image(card.get("link", ""))

    return cards

def main():
    ist = timezone(timedelta(hours=5, minutes=30))
    now_str = datetime.now(ist).strftime("%d %b %Y, %I:%M %p IST")

    raw_articles = fetch_articles()
    cards = curate_with_gemini(raw_articles)

    output = {
        "updated_at": now_str,
        "total_scanned": len(raw_articles),
        "total_cards": len(cards),
        "cards": cards
    }

    with open("briefing.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Done! Saved {len(cards)} cards to briefing.json.")

if __name__ == "__main__":
    main()
