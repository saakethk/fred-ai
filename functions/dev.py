# CODE THAT IS BEING DEVELOPED FOR FRED AI FUNCTIONALITY
from helper import get_credentials, get_timestamp, get_data_finnhub, log, post_data_alpaca
import requests
import json
import google.cloud.firestore
import google
from firebase_admin import firestore
from firebase_functions.options import RetryConfig, RateLimits, SupportedRegion
from firebase_functions import tasks_fn

# Task queue function to handle stock ipo buys
@tasks_fn.on_task_dispatched(retry_config=RetryConfig(max_attempts=5, min_backoff_seconds=60),
                             rate_limits=RateLimits(max_concurrent_dispatches=10))
def execute_ipo_order(req: tasks_fn.CallableRequest) -> str:

    # Gets request data
    symbol = req.data["symbol"]
    firestore_client: google.cloud.firestore.Client = firestore.client()
    ipo_ref = firestore_client.collection('ipo_updates').document(symbol)
    ipo = ipo_ref.get().to_dict()
    
    # Checks IPO status
    if ipo["status"] == "ordered":

        # Adds associated action list to IPO object if it doesn't exist
        if "associated_actions" not in ipo:
            ipo["associated_actions"] = []

        # Determines bracket order prices
        expected_price = float(ipo["shares_value"]) / float(ipo["shares_num"])
        profit_price, stop_price, limit_price = expected_price * 1.50, expected_price * 0.75, expected_price * 0.70

        # Executes Alpaca order
        payload = {
            "side": "buy",
            "symbol": ipo["symbol"],
            "type": "market",
            "notional": "100",
            "time_in_force": "gtc",
            "order_class": "bracket",
            "take_profit": {
                "limit_price": profit_price
            },
            "stop_loss": {
                "stop_price": stop_price,
                "limit_price": limit_price
            }
        }
        status, stock_order_res = post_data_alpaca(url="v2/orders", payload=payload, dev=True)
        if status == True:

            # Updates firestore document
            assoc_action = {
                "type": "order",
                "action": "bracket_order",
                "alpaca_order_id": stock_order_res["id"],
                "timestamp": firestore.SERVER_TIMESTAMP
            }
            ipo["associated_actions"].append(assoc_action)
            ipo["status"] = "executed"
            ipo_ref.set(ipo)
            return f"IPO order for {symbol} executed successfully."
        
        else:
            return f"Failed to execute order for {symbol}"
    else:
        return f"IPO order for {symbol} is already executed or not in 'ordered' status."


# Finds possible IPOs to invest in
@scheduler_fn.on_schedule(schedule="0 */1 * * *")
def investigate_upcoming_ipos(event: scheduler_fn.ScheduledEvent) -> https_fn.Response:

    # Gets stocks in collection
    firestore_client: google.cloud.firestore.Client = firestore.client()

    # Gets open ipo orders
    def get_open_ipo_orders() -> tuple[bool, list | str]:

        # Gets existing IPO orders from Firestore
        collection_ref = firestore_client.collection('ipo_updates')
        docs = collection_ref.stream()
        document_ids = []
        for doc in docs:
            document_ids.append(doc.id)
        return document_ids
    
    # Gets news from newsapi.org
    def get_news_extra(name: str, symbol: str) -> dict:
        params = {
            "searchIn": "title",
            "q": f"{name} OR {symbol}",
            "apiKey": get_credentials("news_extra_api_key"),
            "sortBy": "relevancy",
            "language": "en",
            "from": get_timestamp(with_date=False, delta=240),
            "pageSize": 10
        }
        response = requests.get(f"https://newsapi.org/v2/everything", params=params)
        return response.json()

    # Gets list of upcoming IPOs
    def get_upcoming_ipos() -> tuple[bool, list | str]:
        params = {
            "token": get_credentials("stocks_api_key"),
            "from": get_timestamp(with_date=False, delta=24),  # Adjusted to get the current date
            "to": get_timestamp(with_date=False, delta=-240)  # Adjusted to get the date 240 hours in future
        }
        status, upcoming_ipos_obj = get_data_finnhub(url="api/v1/calendar/ipo", params=params)
        return status, upcoming_ipos_obj["ipoCalendar"] if status else upcoming_ipos_obj

    # Get open IPO orders
    ipo_orders = get_open_ipo_orders()
    status, upcoming_ipos = get_upcoming_ipos()
    
    if status:
        try:
            for ipo in upcoming_ipos:

                if ipo["symbol"] not in ipo_orders:

                    # Get news articles related to the IPO
                    sources = []
                    articles = get_news_extra(ipo['name'], ipo['symbol'])['articles']
                    for article in articles:
                        sources.append(article['url'])

                    # Summarize the articles using Google GenAI
                    response = get_credentials("client").models.generate_content(
                        model="gemini-2.5-flash",
                        contents=f"Review the following list of articles which mention {ipo['name']} and write a concise 100-150 word summary of all the articles combined without mentioning 'the articles'. Also choose one of the following stances (bearish, bullish, neutral) and defend it. Return the response in a structured json output which matches the following: {{ summary: __________, stance: ______________, defense: ______________ }}. Articles: {articles}",
                    )
                    response = response.text
                    parsed_response = json.loads(response[response.index("{"): response.index("}")+1])
                    parsed_response["sources"] = sources
                    parsed_response["expected_price"] = ipo["price"]
                    parsed_response["status"] = "ordered"
                    parsed_response["timestamp"] = firestore.SERVER_TIMESTAMP
                    parsed_response["buy_date"] = ipo["date"]
                    parsed_response["symbol"] = ipo["symbol"]
                    parsed_response["name"] = ipo["name"]
                    parsed_response["shares_value"] = ipo["totalSharesValue"]
                    parsed_response["shares_num"] = ipo["numberOfShares"]

                    # Add the IPO data to Firestore
                    firestore_client.collection('ipo_updates').document(ipo["symbol"]).set(parsed_response)

        except Exception as e:
            log(f"An error occurred while processing IPOs: {e}")
    else:
        log(f"Error fetching IPOs: {upcoming_ipos}")

