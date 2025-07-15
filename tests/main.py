
import requests

# update_status = requests.get("https://update-stocks-ovr4mzor3q-uc.a.run.app")
# update_status_res = update_status.text
# print(update_status_res)

market_api_keys = ("PKI5WDQQCSEKVAL3MYRP", "BGId9iziU8kQ54JqloXe3zbxasLbEHt5YgP0I8AC")

def paper_trade(symbol: str):

    # Liquadates positions in case of bearish signal
    def liquadate_position(percent: int):
        # Gets open position of symbol
        headers = {
            "accept": "application/json",
            "APCA-API-KEY-ID": market_api_keys[0],
            "APCA-API-SECRET-KEY": market_api_keys[1]
        }
        open_positions_request = requests.get(url=f"https://paper-api.alpaca.markets/v2/positions/{symbol}", headers=headers)
        open_positions_object = open_positions_request.json()
        if "message" in open_positions_object:
            print(open_positions_object["message"])
        else:
            # Takes sell action on stock
            sell_request = requests.delete(url=f"https://paper-api.alpaca.markets/v2/positions/{symbol}?percentage={percent}", headers=headers)
            sell_object = sell_request.json()
            print(sell_object)

    # Buys stock in case of bullish signal
    def buy_stock(amount: int):
        # Gets available money in account
        url = "https://paper-api.alpaca.markets/v2/account"
        headers = {
            "accept": "application/json",
            "APCA-API-KEY-ID": "PKI5WDQQCSEKVAL3MYRP",
            "APCA-API-SECRET-KEY": "BGId9iziU8kQ54JqloXe3zbxasLbEHt5YgP0I8AC"
        }
        account_request = requests.get(url=url, headers=headers)
        account_object = account_request.json()
        if account_object["non_marginable_buying_power"] > amount:
            # Buys stock
            url = "https://paper-api.alpaca.markets/v2/orders"
            payload = {
                "type": "market",
                "time_in_force": "day",
                "symbol": symbol,
                "notional": amount,
                "side": "buy"
            }
            headers = {
                "accept": "application/json",
                "content-type": "application/json",
                "APCA-API-KEY-ID": "PKI5WDQQCSEKVAL3MYRP",
                "APCA-API-SECRET-KEY": "BGId9iziU8kQ54JqloXe3zbxasLbEHt5YgP0I8AC"
            }
            response = requests.post(url, json=payload, headers=headers)
            return response.json()
        
    # 


paper_trade("AAPL")