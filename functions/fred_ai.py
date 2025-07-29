# MAIN BACKEND CODE FOR CORE FRED AI FUNCTIONALITY

# Dependencies
import requests
import json
from helper import get_timestamp, get_data_finnhub, get_credentials

# Gets updates regarding stock (recurring)
def get_stock_updates(symbol: str, name: str):

    # Gets stock price from finnhub
    def get_stock_price() -> tuple[bool, list]:
        params = {
            "symbol": symbol,
            "token": get_credentials("stocks_api_key"),
        }
        return get_data_finnhub(url="api/v1/quote", params=params)

    # Gets news from a news api
    def get_news_elsewhere() -> tuple[bool, list]:
        params = {
            "api_token": get_credentials("news_api_key"),
            "search": f"{symbol} | {name}",
            "search_fields": "title,description,keywords,main_text",
            "language": "en",
            "published_on": get_timestamp(),
            "published_after": get_timestamp(with_date=True, delta=1),
            "categories": "business"
        }
        response = requests.get("https://api.thenewsapi.com/v1/news/all", params=params)
        response_object = response.json()
        if "data" in response_object:
            return True, response.json()["data"]
        return False, "Failed to retrieve articles"

    # Analyzes articles to summarize
    def analyze_news(articles: list) -> tuple[bool, dict]:

        # Calculates mean relevance of articles to identify whether or not to post the data
        sources = []
        parsed_articles = []
        for article in articles:
            if article["relevance_score"] > 15:
                parsed_articles.append(article)
                sources.append(article["url"])

        # Generates AI summary
        if len(parsed_articles) != 0:
            response = get_credentials("client").models.generate_content(
                model="gemini-2.5-flash",
                contents=f"Review the following list of articles which mention {symbol} and write a concise 100-150 word summary of all the articles combined without mentioning 'the articles'. Also choose one of the following stances (bearish, bullish, neutral) and defend it. Return the response in a structured json output which matches the following: {{ summary: __________, stance: ______________, defense: ______________ }}. Articles: {articles}",
            )
            response = response.text
            parsed_response = json.loads(response[response.index("{"): response.index("}")+1])
            parsed_response["sources"] = sources

            # Gets stock price at time
            status, stock_price_res = get_stock_price()
            if status == True:
                parsed_response["price"] = stock_price_res
                return True, parsed_response
            else:
                return False, stock_price_res
        return False, "Insufficient number of relevant articles"

    # Returns relevant data
    status, news_articles_res = get_news_elsewhere()
    if status == True:
        return analyze_news(articles=news_articles_res)
    else:
        return False, news_articles_res