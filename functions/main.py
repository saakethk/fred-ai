
# DEPENDENCIES
from firebase_functions import https_fn, options, scheduler_fn
from firebase_functions.firestore_fn import on_document_created, Event, DocumentSnapshot
from firebase_admin import initialize_app, firestore
from datetime import datetime, timezone, timedelta
import google.cloud.firestore
from google import genai
import requests
import google
import json

# Initializes firebase app
initialize_app()

# BACKEND FUNCTIONS

# Retrieves secret keys
client = genai.Client(api_key="AIzaSyAkl3rImltcSRA3FzcBSZuVkpDZ64t6BKg")
news_api_key = "Jzmw6TMctEZN073SFitfu5cQEIQfwviZZjews9ZD"
stocks_api_key = "d10s3c9r01qse6ldmv0gd10s3c9r01qse6ldmv10"
market_api_keys = ("PKI5WDQQCSEKVAL3MYRP", "BGId9iziU8kQ54JqloXe3zbxasLbEHt5YgP0I8AC")

# Gets timestamp in accesible format
def get_timestamp(with_date=False, delta=1) -> str:
    now = datetime.now(timezone.utc) - timedelta(hours=delta)
    if with_date == False:
        return now.strftime("%Y-%m-%d")
    return now.strftime("%Y-%m-%dT%H")

# Gets data from finnhub
def get_data_finnhub(url: str, params: dict) -> tuple[bool, dict | str]:
    response = requests.get(f"https://finnhub.io/{url}", params=params)
    response_object = response.json()
    if "message" in response_object:
        return False, response_object["message"]
    else:
        return True, response_object
    
# Gets updates regarding stock (recurring)
def get_stock_updates(symbol: str, name: str):

    # Gets stock price from finnhub
    def get_stock_price() -> tuple[bool, list]:
        params = {
            "symbol": symbol,
            "token": stocks_api_key
        }
        return get_data_finnhub(url="api/v1/quote", params=params)

    # Gets news from a news api
    def get_news_elsewhere() -> tuple[bool, list]:
        params = {
            "api_token": news_api_key,
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
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=f"Review the following list of articles which mention {symbol} and write a concise 100-150 word summary of all the articles combined without mentioning 'the articles'. Also choose one of the following stances (bearish, bullish, neutral) and defend it. Return the response in a structured json output which matches the following: {{ summary: __________, stance: ______________, defense: ______________ }}. Articles: {articles}",
            )
            response = response.text
            parsed_response = json.loads(response[response.index("{"): response.index("}")+1])
            parsed_response["sources"] = sources

            # Gets stock price at time
            status, stock_price_res = get_stock_price()
            if status == True:
                parsed_response["price"] = get_stock_price()
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

# Indexes stock on first mention (one time)
@https_fn.on_request()
def index_stock(req: https_fn.Request) -> https_fn.Response:

    # Request params
    symbol = req.args.get("symbol").lower()

    # Gets general info from finnhub
    def get_gen_info():
        params ={
            "symbol": symbol,
            "token": stocks_api_key
        }
        status, info_object = get_data_finnhub(url="api/v1/stock/profile2", params=params)
        if status == True:
            firestore_client: google.cloud.firestore.Client = firestore.client()
            firestore_client.collection("stocks").document(symbol).set(
                {
                    "symbol": info_object["ticker"],
                    "name": info_object["name"],
                    "logo": info_object["logo"],
                    "industry": info_object["finnhubIndustry"],
                    "exchange": info_object["exchange"],
                    "market_cap": info_object["marketCapitalization"],
                    "timestamp": firestore.SERVER_TIMESTAMP
                }
            )
            return https_fn.Response(f"{symbol} was indexed.", status=200)
        return https_fn.Response(f"{symbol} failed to be indexed.", status=400)
    return get_gen_info()

# Updates stock entry on recurring basis
@https_fn.on_request()
def update_stocks() -> https_fn.Response:

    # Gets stocks in collection
    firestore_client: google.cloud.firestore.Client = firestore.client()
    indexed_stocks = firestore_client.collection('stocks').stream()
    updated_stocks = []
    for stock in indexed_stocks:
        
        # Parses through stocks and looks for updates
        stock_data = stock.to_dict()
        status, res = get_stock_updates(symbol=stock_data["symbol"], name=stock_data["name"])
        if status == True:

            # Create stock update
            _, update_ref = firestore_client.collection("updates").add(
                {
                    "symbol": stock_data["symbol"],
                    "name": stock_data["name"],
                    "summary": res["summary"],
                    "stance": res["stance"] if (res["stance"] == "bearish" or res["stance"] == "bullish") else "neutral",
                    "defense": res["defense"],
                    "sources": res["sources"],
                    "price": res["price"],
                    "timestamp": firestore.SERVER_TIMESTAMP
                }
            )

            # Update stock index and stance
            stock_data["live_stance"] = res["stance"] if (res["stance"] == "bearish" or res["stance"] == "bullish") else "neutral"
            if "updates" not in stock_data:
                stock_data["updates"] = []
            stock_data["updates"].insert(0, update_ref.id)
            updated_stocks.append(stock.id)
            firestore_client.collection("stocks").document(stock.id).set(stock_data)

    if len(updated_stocks) != 0:
        return https_fn.Response(f"Updated Stocks: {updated_stocks}", status=200)
    return https_fn.Response(f"No stock updated. Insufficient information.", status=400)

# Runs update stock function when market conditions satisfied
@scheduler_fn.on_schedule(schedule="0 */1 * * *")
def update_stocks_auto() -> https_fn.Response:

    # Gets market status when run
    params = {
        "exchange": "US",
        "token": stocks_api_key
    }
    status, market_status = get_data_finnhub(url="api/v1/stock/market-status", params=params)
    if status == True:
        if market_status["isOpen"] == True:
            update_status = requests.get("https://update-stocks-ovr4mzor3q-uc.a.run.app")
            print(update_status.status_code, update_status.text)
        else:
            print("Market is closed")
    else:
        print("Failed to get market status")

# USER FUNCTIONS

# Parses data for user creation
def parseData(key: str, response: dict):
    if key in response.keys():
        return response[key]
    return None

# Runs on user sign-up
@https_fn.on_request(cors=options.CorsOptions(cors_origins="*", cors_methods=["post"]))
def addUser(req: https_fn.Request) -> https_fn.Response:

    # Retrieves relevant clerk data
    request_body = req.get_json()["data"]

    # Define User object according to schema
    user = {
        "id": parseData("id", request_body),
        "first_name": parseData("first_name", request_body),
        "last_name": parseData("last_name", request_body),
        "created": parseData("updated_at", request_body),
        "active_at": [parseData("last_sign_in_at", request_body)],
        "email_address": parseData("email_address", request_body["email_addresses"][0]) if (parseData("email_addresses", request_body) != None) else None,
        "avatar": parseData("profile_image_url", request_body),
        "watchlist": [],
        "searched": []
    }

    # Adds to firestore
    firestore_client: google.cloud.firestore.Client = firestore.client()
    firestore_client.collection("users").document(user["id"]).set(user)

    # Send back a message that we've successfully updated user
    return https_fn.Response(f"User with ID {user["id"]} added.")

# Runs on user sign-in
@https_fn.on_request(cors=options.CorsOptions(cors_origins="*", cors_methods=["post"]))
def updateUser(req: https_fn.Request) -> https_fn.Response:

    # Retrieves relevant clerk data
    request_body = req.get_json()["data"]
    user_id = parseData("user_id", request_body)
    active_at = parseData("last_active_at", request_body)

    if active_at != None:

        # Gets data from firestore
        firestore_client: google.cloud.firestore.Client = firestore.client()
        doc_ref = firestore_client.collection("users").document(user_id)
        user = doc_ref.get().to_dict()

        # Updates relevant part of user
        user["active_at"] = user["active_at"] + [active_at]

        # Pushes update to firestore
        doc_ref.set(user)

    # Send back a message that we've successfully updated user
    return https_fn.Response(f"User with ID {user["id"]} updated.")

# ALPACA INTEGRATION

# Gets data from alpaca
def get_data_alpaca(url: str) -> tuple[bool, dict | str]:
    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": market_api_keys[0],
        "APCA-API-SECRET-KEY": market_api_keys[1]
    }
    response = requests.get(f"https://paper-api.alpaca.markets/{url}", headers=headers)
    response_object = response.json()
    if "message" in response_object:
        return False, response_object["message"]
    else:
        return True, response_object
    
# Delete data from Alpaca
def del_data_alpaca(url: str) -> tuple[bool, dict | str]:
    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": market_api_keys[0],
        "APCA-API-SECRET-KEY": market_api_keys[1]
    }
    response = requests.delete(f"https://paper-api.alpaca.markets/{url}", headers=headers)
    response_object = response.json()
    if "message" in response_object:
        return False, response_object["message"]
    else:
        return True, response_object
    
# Posts data to alpaca
def post_data_alpaca(url: str, payload: dict) -> tuple[bool, dict | str]:
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "APCA-API-KEY-ID": market_api_keys[0],
        "APCA-API-SECRET-KEY": market_api_keys[1]
    }
    response = requests.post(f"https://paper-api.alpaca.markets/{url}", headers=headers, json=payload)
    response_object = response.json()
    if "message" in response_object:
        return False, response_object["message"]
    else:
        return True, response_object

# Utilizes post sentiments about stocks to paper trade
@on_document_created(document="updates/{updateId}")
def paper_trade(event: Event[DocumentSnapshot]):

    # Liquadates positions in case of bearish signal
    def liquadate_position(symbol: str, percent: int) -> None:
        # Gets open position of symbol
        status, open_pos_res = get_data_alpaca(url=f"v2/positions/{symbol}")
        print(open_pos_res)
        if status == True:
            # Sells stock
            status, sell_request = del_data_alpaca(url=f"v2/positions/{symbol}?percentage={percent}")
            if status == True:
                print("Stock sold successfully")
            else:
                print(sell_request)

    # Buys stock in case of bullish signal
    def buy_stock(symbol: str, amount: int) -> None:
        # Gets available money in account
        status, account_res = get_data_alpaca(url="v2/account")
        if status == True:
            if float(account_res["non_marginable_buying_power"]) > amount:
                # Buys stock
                payload = {
                    "type": "market",
                    "time_in_force": "day",
                    "symbol": symbol,
                    "notional": amount,
                    "side": "buy"
                }
                status, buy_stock_res = post_data_alpaca(url="v2/orders", payload=payload)
                if status == True:
                    print("Stock bought successfully")
                else:
                    print(buy_stock_res)
            else:
                print("Insufficient funds")
        else:
            print(account_res)
        
    # Reads update and runs correct function
    update = event.data.to_dict()
    symbol, signal = update["symbol"], update["stance"]
    if signal == "bullish":
        buy_stock(symbol=symbol, amount=100)
    elif signal == "bearish":
        liquadate_position(symbol=symbol, percent=100)

