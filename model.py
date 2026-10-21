"""
model.py — Общий модуль для ИИ-модели Московской биржи
Теперь с автоматической загрузкой индекса IMOEX
"""

import pandas as pd
import numpy as np
import requests
import time
from datetime import datetime, timedelta
from sklearn.preprocessing import RobustScaler
import logging

try:
    from xgboost import XGBClassifier
    from sklearn.calibration import CalibratedClassifierCV
    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False

logger = logging.getLogger(__name__)



# ============================================================================
# ЗАГРУЗКА СОСТАВА ИНДЕКСА IMOEX
# ============================================================================
def get_imoex_tickers():
    """Автоматическая загрузка состава индекса Мосбиржи"""
    logger.info("🔍 Пытаюсь загрузить состав индекса IMOEX...")

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    # Несколько вариантов URL — Мосбиржа меняет форматы
    urls = [
        "https://iss.moex.com/iss/engines/stock/markets/indexes/securities/IMOEX.json?iss.meta=off&iss.only=components",
        "https://iss.moex.com/iss/engines/stock/markets/indexes/securities/IMOEX/components.json?iss.meta=off",
        "https://iss.moex.com/iss/engines/stock/markets/indexes/securities/IMOEX.json?iss.meta=off",
    ]

    for url in urls:
        try:
            logger.info(f"Пробую URL: {url[:80]}...")
            response = requests.get(url, headers=headers, timeout=15)

            if response.status_code != 200:
                logger.warning(f"Статус {response.status_code}, пропускаю")
                continue

            data = response.json()
            logger.info(f"Ключи ответа: {list(data.keys())}")

            # Вариант 1: блок 'components' с вложенными 'columns' и 'data'
            if 'components' in data:
                comp = data['components']
                columns = comp.get('columns', [])
                rows = comp.get('data', [])

                if rows:
                    columns_lower = [c.lower() for c in columns]
                    if 'secid' in columns_lower:
                        idx = columns_lower.index('secid')
                        tickers = [str(r[idx]).strip() for r in rows if r[idx]]
                        if tickers:
                            logger.info(f"✅ Загружено {len(tickers)} акций (вариант 1)")
                            return list(dict.fromkeys(tickers))

            # Вариант 2: блок 'securities' (для components.json)
            if 'securities' in data:
                sec = data['securities']
                columns = sec.get('columns', [])
                rows = sec.get('data', [])

                if rows:
                    columns_lower = [c.lower() for c in columns]
                    if 'secid' in columns_lower:
                        idx = columns_lower.index('secid')
                        tickers = [str(r[idx]).strip() for r in rows if r[idx]]
                        if tickers:
                            logger.info(f"✅ Загружено {len(tickers)} акций (вариант 2)")
                            return list(dict.fromkeys(tickers))

            logger.warning(f"Данных не найдено в этом URL")

        except Exception as e:
            logger.warning(f"Ошибка {url[:60]}: {e}")

    # Fallback: статический список
    logger.info("📋 Использую расширенный статический список")
    return [
        'SBER', 'GAZP', 'LKOH', 'NVTK', 'ROSN', 'TATN', 'BSPB',
        'VTBR', 'MOEX', 'CBOM', 'TCSG',
        'GMKN', 'NLMK', 'CHMF', 'MAGN', 'ALRS', 'PLZL', 'RUAL',
        'MGNT', 'X5', 'MTSS', 'AFKS', 'OZON', 'YDEX', 'VKCO',
        'AFLT', 'PHOR', 'SNGS', 'IRAO', 'FEES', 'RTKM', 'UPRO',
        'POLY', 'SELG', 'MTLR', 'SGZH', 'FIVE', 'RASP', 'TRMK'
    ]
# ============================================================================
# КЛАСС МОДЕЛИ
# ============================================================================
class StockModel:
    """Многофакторная модель для анализа акций Мосбиржи"""

    def __init__(self):
        self.df = None
        self.features = ['Return_1M', 'Dist_to_SMA_50', 'Volatility_1M',
                        'PE_Ratio', 'ROE', 'Debt_to_EBITDA', 'Dividend_Yield']
        self.scaler = None
        self.model = None
        self.is_trained = False
        self.is_synthetic = False
        self.tickers = get_imoex_tickers()  # Динамическая загрузка

    def load_data(self, force_reload=False):
        """Загрузка данных с MOEX ISS API"""
        logger.info(f"🔄 Загрузка данных для {len(self.tickers)} акций...")

        # Защита от пустого списка
        if not self.tickers:
            logger.warning("⚠️ Список тикеров пуст! Использую fallback.")
            self.tickers = [
                'SBER', 'GAZP', 'LKOH', 'NVTK', 'ROSN', 'TATN', 'BSPB',
                'VTBR', 'MOEX', 'CBOM', 'TCSG',
                'GMKN', 'NLMK', 'CHMF', 'MAGN', 'ALRS', 'PLZL', 'RUAL',
                'MGNT', 'X5', 'MTSS', 'AFKS', 'OZON', 'YDEX', 'VKCO',
                'AFLT', 'PHOR', 'SNGS', 'IRAO', 'FEES', 'RTKM', 'UPRO',
                'POLY', 'SELG', 'MTLR', 'SGZH', 'FIVE', 'RASP', 'TRMK'
            ]

        all_data = []
        start_date = (datetime.now() - timedelta(days=3 * 365)).strftime('%Y-%m-%d')
        end_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        base_url = "https://iss.moex.com/iss/history/engines/stock/markets/shares/boards/TQBR/securities/{ticker}.json"

        for idx, ticker in enumerate(self.tickers, 1):
            try:
                ticker_data = []
                start_idx = 0
                limit = 100

                while True:
                    params = {'from': start_date, 'till': end_date, 'start': start_idx, 'limit': limit}

                    # 🔑 RETRY-ЛОГИКА при SSL ошибках
                    response = None
                    for attempt in range(3):
                        try:
                            response = requests.get(
                                base_url.format(ticker=ticker),
                                headers=headers,
                                params=params,
                                timeout=20  # Увеличен таймаут
                            )
                            break
                        except (requests.exceptions.ConnectionError,
                                requests.exceptions.SSLError) as e:
                            logger.warning(f"⚠️ {ticker}: попытка {attempt + 1}/3 — {type(e).__name__}")
                            time.sleep(2 * (attempt + 1))  # Экспоненциальная задержка
                        except Exception as e:
                            logger.warning(f"⚠️ {ticker}: {e}")
                            break

                    if response is None or response.status_code != 200:
                        break

                    response_json = response.json()
                    if 'history' not in response_json:
                        break

                    data = response_json['history'].get('data', [])
                    if not data:
                        break

                    ticker_data.extend(data)
                    if len(data) < limit:
                        break

                    start_idx += limit
                    time.sleep(0.2)  # Увеличена пауза

                if ticker_data:
                    cols = response_json['history']['columns']
                    df_ticker = pd.DataFrame(ticker_data, columns=cols)
                    df_ticker['Ticker'] = ticker
                    df_ticker['Date'] = pd.to_datetime(df_ticker['TRADEDATE'])
                    df_ticker['Price'] = pd.to_numeric(df_ticker['CLOSE'], errors='coerce')
                    df_clean = df_ticker[['Date', 'Ticker', 'Price']].dropna(subset=['Price'])

                    if len(df_clean) >= 100:
                        all_data.append(df_clean)
                        if idx <= 3 or idx % 10 == 0:
                            logger.info(f"✅ {ticker}: {len(df_clean)} записей")
                    else:
                        logger.warning(f"⚠️ {ticker}: мало данных ({len(df_clean)})")

            except KeyboardInterrupt:
                logger.info(" Остановка пользователем")
                raise
            except Exception as e:
                if idx <= 3:
                    logger.warning(f"️ {ticker}: {str(e)[:60]}")

            time.sleep(0.15)

        # Fallback на синтетику только если реально ничего не загрузилось
        if len(all_data) == 0:
            logger.warning("❌ Не удалось загрузить данные! Используем синтетику.")
            self.is_synthetic = True
            np.random.seed(42)
            dates = pd.date_range(start=start_date, end=end_date, freq='B')
            for ticker in self.tickers[:15]:
                prices = 100 * np.exp(np.cumsum(np.random.normal(0.0005, 0.02, len(dates))))
                all_data.append(pd.DataFrame({'Date': dates, 'Ticker': ticker, 'Price': prices}))

        self.df = pd.concat(all_data, ignore_index=True).sort_values(['Ticker', 'Date']).reset_index(drop=True)
        logger.info(f"✅ Загружено данных: {len(self.df)} строк для {len(self.df['Ticker'].unique())} акций")
        return self.df

    def add_features(self):
        """Добавление фундаментальных данных и признаков"""
        # Фундаментальные данные (пока случайные, т.к. реальные требуют отдельного API)
        fund_data = pd.DataFrame({
            'Ticker': self.tickers,
            'PE_Ratio': np.random.uniform(3, 20, len(self.tickers)),
            'ROE': np.random.uniform(0.05, 0.35, len(self.tickers)),
            'Debt_to_EBITDA': np.random.uniform(0.5, 3.0, len(self.tickers))
        })
        self.df = self.df.merge(fund_data, on='Ticker', how='left')

        # Дивидендная доходность (примерные значения для крупных компаний)
        div_map = {'SBER': 0.11, 'LKOH': 0.14, 'MTSS': 0.13, 'GAZP': 0.08, 'NVTK': 0.10}
        self.df['Dividend_Yield'] = self.df['Ticker'].map(div_map).fillna(0.05)

        # Технические признаки
        self.df['Return_1M'] = self.df.groupby('Ticker')['Price'].pct_change(21)
        self.df['SMA_50'] = self.df.groupby('Ticker')['Price'].transform(
            lambda x: x.rolling(50, min_periods=20).mean()
        )
        self.df['Dist_to_SMA_50'] = (self.df['Price'] - self.df['SMA_50']) / self.df['SMA_50']
        self.df['Volatility_1M'] = self.df.groupby('Ticker')['Price'].pct_change().rolling(21).std() * np.sqrt(252)

        # Целевая переменная
        self.df['Future_Price'] = self.df.groupby('Ticker')['Price'].shift(-21)
        self.df['Forward_Return'] = (self.df['Future_Price'] - self.df['Price']) / self.df['Price']
        self.df['Target'] = (self.df['Forward_Return'] > self.df['Forward_Return'].quantile(0.60)).astype(int)

        # Очистка и винзоризация
        self.df = self.df.dropna(subset=self.features + ['Target'])
        for col in self.features:
            self.df[col] = np.clip(self.df[col], self.df[col].quantile(0.05), self.df[col].quantile(0.95))

        return self.df

    def train(self):
        """Обучение модели XGBoost"""
        logger.info("🧠 Обучение модели...")

        X = self.df[self.features].astype(float).values
        y = self.df['Target'].values

        for i in range(X.shape[1]):
            if np.isnan(X[:, i]).any():
                X[:, i] = np.nan_to_num(X[:, i], nan=np.nanmedian(X[:, i]))

        self.scaler = RobustScaler()
        X_scaled = self.scaler.fit_transform(X)

        if XGBOOST_AVAILABLE:
            xgb = XGBClassifier(
                n_estimators=50, max_depth=4, learning_rate=0.05,
                random_state=42, eval_metric='auc', n_jobs=-1, tree_method='hist'
            )
            self.model = CalibratedClassifierCV(xgb, method='isotonic', cv=3)
            self.model.fit(X_scaled, y)
            self.is_trained = True
            logger.info("✅ Модель обучена успешно")
        else:
            logger.warning("⚠️ XGBoost не установлен, модель не обучена")

        return self.model

    def predict(self, n=5):
        """Получить топ-N акций по вероятности"""
        if not self.is_trained:
            raise Exception("Модель не обучена. Сначала вызовите train()")

        latest = self.df.sort_values('Date').groupby('Ticker').tail(1).copy()
        X_latest = latest[self.features].astype(float).values.copy()

        for i in range(X_latest.shape[1]):
            if np.isnan(X_latest[:, i]).any():
                X_latest[:, i] = np.nan_to_num(X_latest[:, i], nan=np.nanmedian(X_latest[:, i]))

        raw_probs = self.model.predict_proba(self.scaler.transform(X_latest))[:, 1]
        probs = 0.25 + pd.Series(raw_probs).rank(pct=True).values * 0.60
        latest['Probability'] = probs

        return latest.sort_values('Probability', ascending=False).head(n)

    def get_ticker_info(self, ticker_code):
        """Получить информацию по конкретному тикеру"""
        if not self.is_trained:
            raise Exception("Модель не обучена")

        stock_data = self.df[self.df['Ticker'] == ticker_code.upper()].sort_values('Date').tail(1)
        if len(stock_data) == 0:
            return None

        all_predictions = self.predict(n=len(self.df['Ticker'].unique()))
        ticker_pred = all_predictions[all_predictions['Ticker'] == ticker_code.upper()]

        if len(ticker_pred) > 0:
            stock_data = stock_data.copy()
            stock_data['Probability'] = ticker_pred.iloc[0]['Probability']

        return stock_data.iloc[0]


# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================
def get_verdict(prob):
    if prob >= 0.70: return "🟢 СИЛЬНАЯ ПОКУПКА"
    if prob >= 0.55: return "🟡 ПОКУПКА"
    if prob >= 0.40: return " ДЕРЖАТЬ"
    return "🔴 ИЗБЕГАТЬ"

def calculate_kelly_fraction(probability, win_loss_ratio=1.5):
    q = 1 - probability
    kelly = probability - (q / win_loss_ratio)
    return max(0, min(kelly, 0.20))

def format_stock_info(row):
    prob_pct = row.get('Probability', 0) * 100
    verdict = get_verdict(row.get('Probability', 0))

    return (f"📊 {row['Ticker']}\n"
            f"💰 Цена: {row['Price']:.2f} ₽\n"
            f"📈 Вероятность: {prob_pct:.1f}%\n"
            f"🏷️ {verdict}\n"
            f"💡 P/E: {row['PE_Ratio']:.1f} | ROE: {row['ROE']*100:.1f}% | Див: {row['Dividend_Yield']*100:.1f}%")