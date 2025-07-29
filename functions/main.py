# MAIN BACKEND CODE FOR FIREBASE FUNCTIONS

# Dependencies
from firebase_functions import https_fn, options, scheduler_fn, tasks_fn
from firebase_functions.firestore_fn import on_document_created, Event, DocumentSnapshot
from firebase_functions.options import RetryConfig, RateLimits, SupportedRegion
from firebase_admin import initialize_app, firestore, functions
import google.auth
from google.auth.transport.requests import AuthorizedSession
import google.cloud.firestore
import requests
import google
import json
from requests_oauthlib import OAuth1Session
from fred_ai import get_stock_updates
from helper import get_data_finnhub, get_credentials, parse_data, post_data_alpaca, get_data_alpaca, del_data_alpaca, log, get_timestamp
from datetime import datetime, timedelta


# Initializes firebase app
initialize_app()

# FRED AI BACKEND FUNCTIONS
    
# Indexes stock on first mention (one time)
@https_fn.on_request()
def index_stock(req: https_fn.Request) -> https_fn.Response:

    # Request params
    symbol = req.args.get("symbol").lower()

    # Gets general info from finnhub
    def get_gen_info():
        params ={
            "symbol": symbol,
            "token": get_credentials("stocks_api_key"),
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
def update_stocks(req: https_fn.Request) -> https_fn.Response:

    # Gets stocks in collection
    firestore_client: google.cloud.firestore.Client = firestore.client()
    indexed_stocks = firestore_client.collection('stocks').stream()
    updated_stocks = []
    for stock in indexed_stocks:
        
        # Parses through stocks and looks for updates
        stock_data = stock.to_dict()
        status, res = get_stock_updates(symbol=stock_data["symbol"], name=stock_data["name"])
        if status == True:

            if "live_stance" not in stock_data:
                stock_data["live_stance"] = "neutral"

            # Create stock update
            _, update_ref = firestore_client.collection("updates").add(
                {
                    "symbol": stock_data["symbol"],
                    "name": stock_data["name"],
                    "summary": res["summary"],
                    "prev_stance": stock_data["live_stance"],
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
def update_stocks_auto(event: scheduler_fn.ScheduledEvent) -> None:

    # Gets market status when run
    params = {
        "exchange": "US",
        "token": get_credentials("stocks_api_key"),
    }
    status, market_status = get_data_finnhub(url="api/v1/stock/market-status", params=params)
    if status == True:
        if market_status["isOpen"] == True:
            update_status = requests.get("https://update-stocks-ovr4mzor3q-uc.a.run.app")
            log(update_status.status_code)
            log(update_status.text)
        else:
            log("Market is closed")
    else:
        log("Failed to get market status")

# USER FUNCTIONS

# Runs on user sign-up
@https_fn.on_request(cors=options.CorsOptions(cors_origins="*", cors_methods=["post"]))
def addUser(req: https_fn.Request) -> https_fn.Response:

    # Retrieves relevant clerk data
    request_body = req.get_json()["data"]

    # Define User object according to schema
    user = {
        "id": parse_data("id", request_body),
        "first_name": parse_data("first_name", request_body),
        "last_name": parse_data("last_name", request_body),
        "created": parse_data("updated_at", request_body),
        "active_at": [parse_data("last_sign_in_at", request_body)],
        "email_address": parse_data("email_address", request_body["email_addresses"][0]) if (parse_data("email_addresses", request_body) != None) else None,
        "avatar": parse_data("profile_image_url", request_body),
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
    user_id = parse_data("user_id", request_body)
    active_at = parse_data("last_active_at", request_body)

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

# Utilizes post sentiments about stocks to paper trade
@on_document_created(document="updates/{updateId}")
def paper_trade(event: Event[DocumentSnapshot]) -> None:

    # Makes update readable
    firestore_client: google.cloud.firestore.Client = firestore.client()
    update = event.data.to_dict()

    # Sells stock if not already owned
    def sell_stock(symbol: str, amount: int) -> None:
        # Sells stock
        payload = {
            "type": "market",
            "time_in_force": "day",
            "symbol": symbol,
            "notional": amount,
            "side": "sell"
        }
        status, buy_stock_res = post_data_alpaca(url="v2/orders", payload=payload)
        if status == True:
            log("Stock bought successfully")
            if "associated_actions" not in update:
                update["assocaited_actions"] = []
            assoc_action = {
                "type": "order",
                "action": "sell",
                "alpaca_order_id": buy_stock_res["id"],
                "timestamp": firestore.SERVER_TIMESTAMP
            }
            if "associated_actions" not in update:
                update["associated_actions"] = []
            update["associated_actions"].append(assoc_action)
            update_ref = firestore_client.collection("updates").document(event.data.id)
            update_ref.set(update)
            order_ref = firestore_client.collection("orders")
            order_ref.add(assoc_action)
        else:
            log(buy_stock_res)

    # Liquadates positions in case of bearish signal
    def liquadate_position(symbol: str, percent: int) -> None:
        # Gets open position of symbol
        status, open_pos_res = get_data_alpaca(url=f"v2/positions/{symbol}")
        log(open_pos_res)
        if (status == True):
            # Sells stock
            status, sell_request = del_data_alpaca(url=f"v2/positions/{symbol}?percentage={percent}")
            if status == True:
                log("Stock sold successfully")
                if "associated_actions" not in update:
                    update["assocaited_actions"] = []
                assoc_action = {
                    "type": "order",
                    "action": "sell",
                    "alpaca_order_id": sell_request["id"],
                    "timestamp": firestore.SERVER_TIMESTAMP
                }
                if "associated_actions" not in update:
                    update["associated_actions"] = []
                update["associated_actions"].append(assoc_action)
                update_ref = firestore_client.collection("updates").document(event.data.id)
                update_ref.set(update)
                order_ref = firestore_client.collection("orders")
                order_ref.create(assoc_action)
            else:
                log(sell_request)
        else:
            log("No open position found for symbol:", symbol)
            # If no open position, sells shorts on stock
            sell_stock(symbol=symbol, amount=100)

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
                    log("Stock bought successfully")
                    if "associated_actions" not in update:
                        update["associated_actions"] = []
                    assoc_action = {
                        "type": "order",
                        "action": "sell",
                        "alpaca_order_id": buy_stock_res["id"],
                        "timestamp": firestore.SERVER_TIMESTAMP
                    }
                    update["associated_actions"].append(assoc_action)
                    update_ref = firestore_client.collection("updates").document(event.data.id)
                    update_ref.set(update)
                    order_ref = firestore_client.collection("orders")
                    order_ref.add(assoc_action)
                else:
                    log(buy_stock_res)
            else:
                log("Insufficient funds")
        else:
            log(account_res)
        
    # Reads update and runs correct function
    symbol, signal = update["symbol"], update["stance"]
    if signal == "bullish":
        buy_stock(symbol=symbol, amount=100)
    elif signal == "bearish":
        liquadate_position(symbol=symbol, percent=100)

# TWITTER INTEGRATION

# Utilizes post sentiments about stocks to post to twitter
@on_document_created(document="updates/{updateId}")
def create_tweet(event: Event[DocumentSnapshot]) -> None:

    # Makes update readable
    firestore_client: google.cloud.firestore.Client = firestore.client()
    update = event.data.to_dict()

    # Summarizes summary even further via AI
    summary = get_credentials("client").models.generate_content(
        model="gemini-2.5-flash",
        contents=f"Summarize the following summary of stock news into an objective, engaging 240 character tweet. The word limit is very strict and cannot go over 240 characters but can be below. Summary: {update['summary']}",
    )

    # Defines tweet body
    poll = {
        "options": ["Bearish", "Bullish", "Neutral"],
        "duration_minutes": 60 * 24
    }
    payload = {
        "text": f"{summary.text}\nHow does this news make you feel?",
        "poll": poll
    }

    # Make the request
    oauth = OAuth1Session(
        get_credentials("twitter_api_keys")[0],
        client_secret=get_credentials("twitter_api_keys")[1],
        resource_owner_key=get_credentials("twitter_access_tokens")[0],
        resource_owner_secret=get_credentials("twitter_access_tokens")[1],
    )

    # Making the request
    response = oauth.post(
        "https://api.twitter.com/2/tweets",
        json=payload,
    )

    if response.status_code != 201:
        raise Exception(
            "Request returned an error: {} {}".format(response.status_code, response.text)
        )

    log("Response code: {}".format(response.status_code))

    # Parses response for tweet id
    tweet_id = response.json()["data"]["id"]
    update["associated_tweet_id"] = tweet_id
    update["associated_tweet_summary"] = summary.text
    update_ref = firestore_client.collection("updates").document(event.data.id)
    update_ref.set(update)
