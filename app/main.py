import time

import pyupbit
import requests
import datetime
from config import Config

# data = pyupbit.get_ohlcv(ticker="KRW-BTC", interval="day", count=200, to=None, period=0.1) # 데이터 가져오기

# data = pyupbit.get_ohlcv(ticker="KRW-BTC", interval="minute1", count=500, to=None, period=0.1) # 데이터 가져오기
# pyupbit.get_current_price(ticker="KRW-BTC") # 현재가 조회

class AutoTrading:
    def __init__(self):
        self.upbit = None
        self.config = Config()
        self.shopping_basket = []
        self.total_score = 0
        self.target_ticker = []
        self.buy_ticker = []
        self.target_ticker_buy_price = {}
        self.min_ratio = {}
        self.max_ratio = {}
        self.fail_list = []
        self.worker_count = 3

    def send_slack(self, text):
        url = self.config.slack_channel

        payload = {"text": text}

        requests.post(url, json=payload)

    def get_target_price(self, ticker, k):
        """변동성 돌파 전략으로 매수 목표가 조회"""
        df = pyupbit.get_ohlcv(ticker, interval="day", count=2)
        target_price = df.iloc[0]['close'] + (df.iloc[0]['high'] - df.iloc[0]['low']) * k
        return target_price

    def get_start_time(self, ticker):
        """시작 시간 조회"""
        df = pyupbit.get_ohlcv(ticker, interval="day", count=1)
        start_time = df.index[0]
        return start_time

    def get_ma15(self, ticker):
        """15일 이동 평균선 조회"""
        df = pyupbit.get_ohlcv(ticker, interval="day", count=15)
        ma15 = df['close'].rolling(15).mean().iloc[-1]
        return ma15

    def get_balance(self, ticker):
        """잔고 조회"""
        balances = self.upbit.get_balances()
        for b in balances:
            if b['currency'] == ticker:
                if b['balance'] is not None:
                    return float(b['balance'])
                else:
                    return 0
        return 0

    def login(self):
        self.upbit = pyupbit.Upbit(self.config.upbit_access_key, self.config.upbit_secret_key)

    def get_current_price(self, ticker):
        """현재가 조회"""
        return pyupbit.get_orderbook(ticker=ticker)["orderbook_units"][0]["ask_price"]

    def select_best_ticker(self):
        score_dict = {}

        for ticker in self.shopping_basket:
            data = pyupbit.get_ohlcv(ticker=ticker, interval="minute1", count=500, to=None, period=0.1)
            first_data = data.iloc[0]
            last_data = data.iloc[-1]

            open_price_score = (last_data['open'] - first_data['open']) / first_data['open'] * 100
            volume_score = last_data['volume'] - first_data['volume']

            if open_price_score < 0:
                open_price_score = 0
            elif open_price_score >= 10:
                open_price_score = 10

            if volume_score < 0:
                volume_score = 0
            elif volume_score >= 100000:
                volume_score = 100000

            total_score = (open_price_score * 10000) + volume_score

            if total_score < 5000:
                continue

            score_dict[ticker] = total_score

        score_dict = sorted(score_dict.items(), key = lambda item: item[1], reverse=True)

        for i in range(0, min(len(score_dict), self.worker_count)):
            if score_dict[i][0] in self.buy_ticker:
                continue
            self.target_ticker.append(score_dict[i][0])

        if self.target_ticker:
            self.send_slack(f'상승 예측 ticker - {self.shopping_basket}\n구매 예정 ticker - {self.target_ticker} | '
                            f'score : {self.total_score}')
        self.shopping_basket = []

    def buy_target_ticker(self):
        for ticker in self.target_ticker:
            if ticker in self.buy_ticker:
                continue

            krw = self.get_balance("KRW") / self.worker_count
            buy_result = self.upbit.buy_market_order(ticker, krw * 0.9995)
            self.send_slack(f'구매 ticker - {ticker} | 구매정보 : {buy_result}')
            self.target_ticker_buy_price[ticker] = self.get_current_price(ticker)
            self.buy_ticker.append(ticker)
            self.worker_count -= 1

    def sell_target_ticker(self):
        remove_ticker_list = []
        for ticker in self.target_ticker:
            current_price = self.get_current_price(ticker)
            rate_ratio = (current_price - self.target_ticker_buy_price[ticker]) / self.target_ticker_buy_price[ticker] * 100
            coin_valume = self.get_balance(ticker.replace("KRW-", ""))

            if rate_ratio < self.min_ratio.get(ticker, -5):
                if rate_ratio < 0:
                    self.fail_list.append(ticker)
                    self.send_slack(f'{ticker} 손절 | 손절금 : {coin_valume} | 손실률 : {rate_ratio}')
                else:
                    self.send_slack(f'{ticker} 익절 | 익절금 : {coin_valume} | 수익률 : {rate_ratio}')

                self.upbit.sell_market_order(ticker, coin_valume)
                self.worker_count += 1
                self.min_ratio.pop(ticker, None)
                self.max_ratio.pop(ticker, None)
                self.buy_ticker.remove(ticker)
                remove_ticker_list.append(ticker)

            if rate_ratio >= self.max_ratio.get(ticker, 5):
                auto_trading_class.send_slack(f'{ticker}의 현재 수익률 : {rate_ratio} | 목표 수익률 : {self.max_ratio.get(ticker, 5)}, 손절 예정금 : {self.min_ratio.get(ticker, 0)}')
                self.min_ratio[ticker] = self.min_ratio.get(ticker, 0) + 5
                self.max_ratio[ticker] = self.max_ratio.get(ticker, 5) + 5
            if rate_ratio >= 20:
                self.send_slack(f'{ticker} 익절 | 익절금 : {coin_valume} | 수익률 : {rate_ratio}')
                self.upbit.sell_market_order(self.target_ticker, coin_valume)
                self.worker_count += 1
                self.min_ratio.pop(ticker, None)
                self.max_ratio.pop(ticker, None)
                self.buy_ticker.remove(ticker)
                remove_ticker_list.append(ticker)

        for remove_ticker in remove_ticker_list:
            self.target_ticker.remove(remove_ticker)


auto_trading_class = AutoTrading()
auto_trading_class.login()
auto_trading_class.send_slack(f'자동매매 시작 일시 - {datetime.datetime.now()}')
auto_trading_class.send_slack(f'자동매매 대상 리스트 - {auto_trading_class.config.target_ticker_list}')

while True:
    if auto_trading_class.worker_count:
        for target_ticker in auto_trading_class.config.target_ticker_list:
            if target_ticker in auto_trading_class.target_ticker:
                continue

            if target_ticker in auto_trading_class.fail_list:
                continue

            try:
                now = datetime.datetime.now()
                start_time = auto_trading_class.get_start_time(target_ticker)
                end_time = start_time + datetime.timedelta(days=1)

                target_price = auto_trading_class.get_target_price(target_ticker, 0.5)
                ma15 = auto_trading_class.get_ma15(target_ticker)
                current_price = auto_trading_class.get_current_price(target_ticker)
                if target_price < current_price and ma15 < current_price:
                    auto_trading_class.shopping_basket.append(target_ticker)
                time.sleep(1)
            except Exception as e:
                auto_trading_class.send_slack(f"에러 발생 - {e}")

        if auto_trading_class.shopping_basket:
            auto_trading_class.select_best_ticker()
            auto_trading_class.buy_target_ticker()

    else:
        auto_trading_class.sell_target_ticker()
        time.sleep(5)

    #     post_message(myToken,"#crypto", e)
    #     time.sleep(1)
