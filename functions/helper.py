# LIST OF COMMON HELPER FUNCTIONS FOR ALL FUNCTIONS

# Dependencies
import requests
from google import genai
import os
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Function to be used for logging and debugging
def log(message: str):
    if True:
        print(f"[LOG] {message}")

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
    
# Parses data for user creation
def parse_data(key: str, response: dict):
    if key in response.keys():
        return response[key]
    return None
    
# Returns cored creds
def get_credentials(key: str) -> str:
    client = genai.Client(api_key=os.getenv("GOOGLE_GENAI_API_KEY"))
    news_api_key = os.getenv("NEWS_API_KEY")
    news_extra_api_key = os.getenv("NEWS_EXTRA_API_KEY")
    stocks_api_key = os.getenv("STOCKS_API_KEY")
    market_api_keys = (os.getenv("MARKET_API_KEY"), os.getenv("MARKET_API_SECRET"))
    market_api_keys_dev = (os.getenv("MARKET_API_KEY_DEV"), os.getenv("MARKET_API_SECRET_DEV"))
    twitter_api_keys = (os.getenv("TWITTER_API_KEY"), os.getenv("TWITTER_API_SECRET"))
    twitter_access_tokens = (os.getenv("TWITTER_ACCESS_TOKEN"), os.getenv("TWITTER_ACCESS_TOKEN_SECRET"))
    creds = {
        "client": client,
        "news_api_key": news_api_key,
        "news_extra_api_key": news_extra_api_key,
        "stocks_api_key": stocks_api_key,
        "market_api_keys": market_api_keys,
        "market_api_keys_dev": market_api_keys_dev,
        "twitter_api_keys": twitter_api_keys,
        "twitter_access_tokens": twitter_access_tokens
    }
    return creds[key]

# Gets data from alpaca
def get_data_alpaca(url: str) -> tuple[bool, dict | str]:
    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": get_credentials("market_api_keys")[0],
        "APCA-API-SECRET-KEY": get_credentials("market_api_keys")[1]
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
        "APCA-API-KEY-ID": get_credentials("market_api_keys")[0],
        "APCA-API-SECRET-KEY": get_credentials("market_api_keys")[1]
    }
    response = requests.delete(f"https://paper-api.alpaca.markets/{url}", headers=headers)
    response_object = response.json()
    if "message" in response_object:
        return False, response_object["message"]
    else:
        return True, response_object
    
# Posts data to alpaca
def post_data_alpaca(url: str, payload: dict, dev=False) -> tuple[bool, dict | str]:
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "APCA-API-KEY-ID": get_credentials("market_api_keys")[0] if not dev else get_credentials("market_api_keys_dev")[0],
        "APCA-API-SECRET-KEY": get_credentials("market_api_keys")[1] if not dev else get_credentials("market_api_keys_dev")[1]
    }
    response = requests.post(f"https://paper-api.alpaca.markets/{url}", headers=headers, json=payload)
    response_object = response.json()
    if "message" in response_object:
        return False, response_object["message"]
    else:
        return True, response_object