"""Real publisher feeds used by the 8search Trending News feed.

Every URL in this file is an official public RSS/Atom feed. They are fetched
server-side only (never from user input), so the feed list is the complete
SSRF boundary. Adding a source here is the only way to add one.

Categories are deliberately broad: a story may be top news in India while a
world publisher covers the same event. Clustering merges those duplicates.
"""

from dataclasses import dataclass

CATEGORIES = ("all", "india", "world", "technology", "business", "science", "sports")
CATEGORY_LABELS = {
    "all": "Top news",
    "india": "India",
    "world": "World",
    "technology": "Technology",
    "business": "Business",
    "science": "Science",
    "sports": "Sports",
}


@dataclass(frozen=True)
class FeedSource:
    name: str
    url: str
    category: str
    weight: float = 0.8


FEEDS: tuple[FeedSource, ...] = (
    # India
    FeedSource("The Hindu", "https://www.thehindu.com/news/national/feeder/default.rss", "india", 0.96),
    FeedSource("The Hindu", "https://www.thehindu.com/news/international/feeder/default.rss", "world", 0.96),
    FeedSource("The Hindu", "https://www.thehindu.com/business/feeder/default.rss", "business", 0.94),
    FeedSource("The Hindu", "https://www.thehindu.com/sci-tech/science/feeder/default.rss", "science", 0.92),
    FeedSource("The Hindu", "https://www.thehindu.com/sport/feeder/default.rss", "sports", 0.90),
    FeedSource("Times of India", "https://timesofindia.indiatimes.com/rssfeedstopstories.cms", "india", 0.90),
    FeedSource("Times of India", "https://timesofindia.indiatimes.com/rssfeeds/296589292.cms", "world", 0.88),
    FeedSource("Times of India", "https://timesofindia.indiatimes.com/rssfeeds/1898055.cms", "business", 0.88),
    FeedSource("Times of India", "https://timesofindia.indiatimes.com/rssfeeds/66949542.cms", "technology", 0.86),
    FeedSource("Times of India", "https://timesofindia.indiatimes.com/rssfeeds/4719148.cms", "sports", 0.86),
    FeedSource("Hindustan Times", "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml", "india", 0.90),
    FeedSource("Hindustan Times", "https://www.hindustantimes.com/feeds/rss/world-news/rssfeed.xml", "world", 0.88),
    FeedSource("Hindustan Times", "https://www.hindustantimes.com/feeds/rss/business/rssfeed.xml", "business", 0.86),
    FeedSource("Hindustan Times", "https://www.hindustantimes.com/feeds/rss/technology/rssfeed.xml", "technology", 0.84),
    FeedSource("Hindustan Times", "https://www.hindustantimes.com/feeds/rss/sports/rssfeed.xml", "sports", 0.84),
    FeedSource("NDTV", "https://feeds.feedburner.com/ndtvnews-top-stories", "india", 0.86),
    FeedSource("NDTV", "https://feeds.feedburner.com/ndtvnews-world-news", "world", 0.84),
    FeedSource("NDTV", "https://feeds.feedburner.com/ndtvprofit-latest", "business", 0.82),
    FeedSource("NDTV", "https://feeds.feedburner.com/ndtv-sports", "sports", 0.82),
    FeedSource("The Indian Express", "https://indianexpress.com/section/india/feed/", "india", 0.94),
    FeedSource("The Indian Express", "https://indianexpress.com/section/world/feed/", "world", 0.92),
    FeedSource("The Indian Express", "https://indianexpress.com/section/business/feed/", "business", 0.90),
    FeedSource("The Indian Express", "https://indianexpress.com/section/technology/feed/", "technology", 0.88),
    FeedSource("The Indian Express", "https://indianexpress.com/section/sports/feed/", "sports", 0.88),

    # World
    FeedSource("BBC News", "https://feeds.bbci.co.uk/news/world/rss.xml", "world", 0.99),
    FeedSource("BBC News", "https://feeds.bbci.co.uk/news/technology/rss.xml", "technology", 0.97),
    FeedSource("BBC News", "https://feeds.bbci.co.uk/news/business/rss.xml", "business", 0.97),
    FeedSource("BBC News", "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml", "science", 0.96),
    FeedSource("BBC Sport", "https://feeds.bbci.co.uk/sport/rss.xml?edition=uk", "sports", 0.92),
    FeedSource("The Guardian", "https://www.theguardian.com/world/rss", "world", 0.97),
    FeedSource("The Guardian", "https://www.theguardian.com/world/india/rss", "india", 0.95),
    FeedSource("The Guardian", "https://www.theguardian.com/uk/technology/rss", "technology", 0.94),
    FeedSource("The Guardian", "https://www.theguardian.com/uk/business/rss", "business", 0.94),
    FeedSource("The Guardian", "https://www.theguardian.com/science/rss", "science", 0.94),
    FeedSource("The Guardian", "https://www.theguardian.com/uk/sport/rss", "sports", 0.92),
    FeedSource("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml", "world", 0.94),
    FeedSource("NPR", "https://feeds.npr.org/1001/rss.xml", "world", 0.94),
    FeedSource("NPR", "https://feeds.npr.org/1006/rss.xml", "business", 0.90),
    FeedSource("NPR", "https://feeds.npr.org/1007/rss.xml", "science", 0.90),
    FeedSource("NPR", "https://feeds.npr.org/1055/rss.xml", "sports", 0.88),

    # Technology
    FeedSource("TechCrunch", "https://techcrunch.com/feed/", "technology", 0.84),
    FeedSource("The Verge", "https://www.theverge.com/rss/index.xml", "technology", 0.88),
    FeedSource("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index", "technology", 0.88),
    FeedSource("How-To Geek", "https://www.howtogeek.com/feed/", "technology", 0.70),

    # Science and sport
    FeedSource("ScienceDaily", "https://www.sciencedaily.com/rss/top/science.xml", "science", 0.78),
    FeedSource("Nature", "https://www.nature.com/nature.rss", "science", 0.95),
    FeedSource("ESPN", "https://www.espn.com/espn/rss/news", "sports", 0.86),
)

# Optional licensed API. The feed works fully without a key.
GNEWS_ENDPOINT = "https://gnews.io/api/v4/top-headlines"
GNEWS_CATEGORIES = (
    ("general", "world"),
    ("nation", "india"),
    ("business", "business"),
    ("technology", "technology"),
    ("science", "science"),
    ("sports", "sports"),
)
GNEWS_WEIGHT = 0.82
