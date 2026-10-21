"""
app.py — Streamlit интерфейс для ИИ-Трейдера
"""

import streamlit as st
import pandas as pd
import numpy as np
import sqlite3
from datetime import datetime
import plotly.graph_objects as go
from scipy.stats import spearmanr

# Импорт общей модели
from model import StockModel, get_verdict, calculate_kelly_fraction, format_stock_info

# ... ваши импорты ...

st.set_page_config(page_title="ИИ-Трейдер Мосбиржи", page_icon="📈", layout="wide")

# ============================================================================
# ИНТЕГРАЦИЯ С MINI APP: ПОЛУЧЕНИЕ USER_ID ИЗ URL
# ============================================================================
# Streamlit получает параметры из URL, например: ?user_id=152002422
query_params = st.query_params
user_id = query_params.get("user_id", "Гость")

if user_id != "Гость":
    st.markdown(f"### 👋 Привет! Вы вошли как пользователь **{user_id}**")
    st.markdown("📱 *Вы открыли это приложение из бота MAX. Ваши данные песочницы загружены.*")
else:
    st.markdown("### 👋 Добро пожаловать в ИИ-Трейдер!")
    st.markdown("💡 *Для персонализации откройте это приложение через кнопку в боте MAX.*")

st.markdown("---")

# ... далее идет ваш существующий код инициализации БД и модели ...


# ============================================================================
# БАЗА ДАННЫХ ПЕСОЧНИЦЫ
# ============================================================================
def init_database():
    conn = sqlite3.connect('paper_trading.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS portfolio
                 (
                     id
                     INTEGER
                     PRIMARY
                     KEY
                     AUTOINCREMENT,
                     ticker
                     TEXT
                     NOT
                     NULL,
                     entry_price
                     REAL
                     NOT
                     NULL,
                     shares
                     INTEGER
                     NOT
                     NULL,
                     entry_date
                     TEXT
                     NOT
                     NULL,
                     exit_price
                     REAL,
                     exit_date
                     TEXT,
                     actual_return
                     REAL,
                     status
                     TEXT
                     DEFAULT
                     'OPEN'
                 )''')
    c.execute('''CREATE TABLE IF NOT EXISTS signals
                 (
                     id
                     INTEGER
                     PRIMARY
                     KEY
                     AUTOINCREMENT,
                     signal_date
                     TEXT
                     NOT
                     NULL,
                     ticker
                     TEXT
                     NOT
                     NULL,
                     price
                     REAL
                     NOT
                     NULL,
                     probability
                     REAL
                     NOT
                     NULL,
                     kelly_fraction
                     REAL
                 )''')
    c.execute('''CREATE TABLE IF NOT EXISTS balance
                 (
                     id
                     INTEGER
                     PRIMARY
                     KEY
                     AUTOINCREMENT,
                     date
                     TEXT
                     NOT
                     NULL,
                     cash
                     REAL
                     NOT
                     NULL,
                     portfolio_value
                     REAL
                     NOT
                     NULL,
                     total_value
                     REAL
                     NOT
                     NULL
                 )''')
    conn.commit()
    conn.close()


def get_portfolio():
    conn = sqlite3.connect('paper_trading.db')
    df = pd.read_sql("SELECT * FROM portfolio WHERE status = 'OPEN'", conn)
    conn.close()
    return df


def get_closed_trades():
    conn = sqlite3.connect('paper_trading.db')
    df = pd.read_sql("SELECT * FROM portfolio WHERE status = 'CLOSED'", conn)
    conn.close()
    return df


def get_balance():
    conn = sqlite3.connect('paper_trading.db')
    df = pd.read_sql("SELECT * FROM balance ORDER BY date", conn)
    conn.close()
    return df


def save_signal(signal_date, ticker, price, probability, kelly_fraction):
    conn = sqlite3.connect('paper_trading.db')
    c = conn.cursor()
    c.execute('INSERT INTO signals (signal_date, ticker, price, probability, kelly_fraction) VALUES (?, ?, ?, ?, ?)',
              (signal_date, ticker, price, probability, kelly_fraction))
    conn.commit()
    conn.close()


def buy_stock(ticker, price, shares, date):
    conn = sqlite3.connect('paper_trading.db')
    c = conn.cursor()
    c.execute('INSERT INTO portfolio (ticker, entry_price, shares, entry_date, status) VALUES (?, ?, ?, ?, "OPEN")',
              (ticker, price, shares, date))
    conn.commit()
    conn.close()


def close_position(ticker, exit_price, exit_date):
    conn = sqlite3.connect('paper_trading.db')
    c = conn.cursor()
    c.execute('SELECT entry_price FROM portfolio WHERE ticker = ? AND status = "OPEN"', (ticker,))
    row = c.fetchone()
    if row:
        entry_price = row[0]
        actual_return = (exit_price - entry_price) / entry_price
        c.execute(
            'UPDATE portfolio SET exit_price = ?, exit_date = ?, actual_return = ?, status = "CLOSED" WHERE ticker = ? AND status = "OPEN"',
            (exit_price, exit_date, actual_return, ticker))
        conn.commit()
    conn.close()


def save_balance(date, cash, portfolio_value):
    conn = sqlite3.connect('paper_trading.db')
    c = conn.cursor()
    c.execute('INSERT INTO balance (date, cash, portfolio_value, total_value) VALUES (?, ?, ?, ?)',
              (date, cash, portfolio_value, cash + portfolio_value))
    conn.commit()
    conn.close()


init_database()


# ============================================================================
# ЗАГРУЗКА МОДЕЛИ
# ============================================================================
@st.cache_resource
def load_model(force_reload=False):
    model = StockModel()
    model.load_data(force_reload)
    model.add_features()
    model.train()
    return model


if 'force_reload' in st.session_state and st.session_state['force_reload']:
    st.cache_resource.clear()
    del st.session_state['force_reload']

model = load_model()

INITIAL_CAPITAL = 1_000_000

st.title("📈 ИИ-Трейдер Мосбиржи — Песочница + Продвинутая аналитика")

# Боковая панель
with st.sidebar:
    st.header("⚙️ Управление")
    st.markdown(f"**💰 Песочница**\nНачальный капитал: {INITIAL_CAPITAL:,} ₽")

    if st.button(" Обновить данные", use_container_width=True):
        st.session_state['force_reload'] = True
        st.rerun()

    st.divider()
    st.markdown("**Источник данных:**")
    if model.is_synthetic:
        st.error(" СИНТЕТИЧЕСКИЕ ДАННЫЕ")
    else:
        st.success("📡 Реальные данные Мосбиржи")
        st.caption(
            f"Диапазон: {model.df['Date'].min().strftime('%Y-%m-%d')} — {model.df['Date'].max().strftime('%Y-%m-%d')}")

# Вкладки
tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Рейтинг и сигналы",
    "🎮 Песочница",
    "📈 Портфель и баланс",
    "🧪 Продвинутая аналитика"
])

# ============================================================================
# ВКЛАДКА 1: РЕЙТИНГ
# ============================================================================
with tab1:
    st.subheader("📊 Текущий рейтинг акций")

    latest = model.predict(n=len(model.df['Ticker'].unique()))

    col1, col2, col3 = st.columns(3)
    with col1:
        min_prob = st.slider("🎯 Мин. вероятность", 0.0, 1.0, 0.40, 0.05,
                             help="Вероятность того, что акция войдёт в топ-40% лучших по доходности за месяц.")
    with col2:
        max_pe = st.slider("💰 Макс. P/E", 1, 100, 100, 5,
                           help="P/E = цена акции ÷ годовая прибыль. Чем ниже — тем 'дешевле' акция.")
    with col3:
        min_div = st.slider("💵 Мин. див. доходность", 0.0, 0.20, 0.0, 0.01,
                            help="Годовая дивидендная доходность. 0.08+ = дивидендные акции.")

    filtered_df = latest[(latest['Probability'] >= min_prob) &
                         (latest['PE_Ratio'] <= max_pe) &
                         (latest['Dividend_Yield'] >= min_div)].copy()

    filtered_df['Рекомендация'] = filtered_df['Probability'].apply(get_verdict)
    filtered_df['Вероятность, %'] = (filtered_df['Probability'] * 100).round(1).astype(str) + '%'
    filtered_df['Цена, руб.'] = filtered_df['Price'].round(2)
    filtered_df['Доля по Келли, %'] = filtered_df['Probability'].apply(
        lambda p: f"{calculate_kelly_fraction(p) * 100:.1f}%")

    display_cols = ['Ticker', 'Цена, руб.', 'Вероятность, %', 'Рекомендация', 'Доля по Келли, %', 'ROE', 'PE_Ratio',
                    'Dividend_Yield']
    rename_map = {'ROE': 'Рентабельность (ROE)', 'PE_Ratio': 'P/E', 'Dividend_Yield': 'Див. доходность'}
    display_df = filtered_df[display_cols].rename(columns=rename_map)
    display_df['Див. доходность'] = (display_df['Див. доходность'] * 100).round(1).astype(str) + '%'
    display_df['Рентабельность (ROE)'] = (display_df['Рентабельность (ROE)'] * 100).round(1).astype(str) + '%'

    st.dataframe(display_df, use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("### 💾 Сохранение сигналов")
    st.caption("Сохраняет Топ-5 акций в базу данных песочницы для последующего анализа.")

    if st.button("💾 Сохранить текущие сигналы в БД", use_container_width=True):
        today = datetime.now().strftime('%Y-%m-%d')
        count = 0
        for _, row in filtered_df.head(5).iterrows():
            save_signal(today, row['Ticker'], row['Price'], row['Probability'],
                        calculate_kelly_fraction(row['Probability']))
            count += 1
        st.success(f"✅ Сохранено {count} сигналов")
        st.info("💡 Теперь купите эти акции во вкладке '🎮 Песочница'")

# ============================================================================
# ВКЛАДКА 2: ПЕСОЧНИЦА
# ============================================================================
with tab2:
    st.subheader("🎮 Песочница — Бумажная торговля")

    portfolio = get_portfolio()
    balance_history = get_balance()

    if len(balance_history) > 0:
        current_balance = balance_history.iloc[-1]['total_value']
    else:
        current_balance = INITIAL_CAPITAL
        save_balance(datetime.now().strftime('%Y-%m-%d'), INITIAL_CAPITAL, 0)

    col1, col2, col3 = st.columns(3)
    col1.metric("💰 Общий капитал", f"{current_balance:,.0f} ₽")
    col2.metric("📊 Позиций открыто", len(portfolio))
    col3.metric("📈 Доходность", f"{((current_balance / INITIAL_CAPITAL) - 1) * 100:.2f}%")

    st.divider()

    st.markdown("### 🛒 Покупка акций")

    buy_col1, buy_col2, buy_col3 = st.columns(3)
    with buy_col1:
        selected_ticker = st.selectbox("Выберите акцию:", model.df['Ticker'].unique())
    with buy_col2:
        shares = st.number_input("Количество акций:", min_value=1, value=10)
    with buy_col3:
        st.write(" ")
        if st.button("🟢 КУПИТЬ", use_container_width=True):
            current_price = latest[latest['Ticker'] == selected_ticker]['Price'].values[0]
            total_cost = current_price * shares

            if total_cost <= current_balance:
                buy_stock(selected_ticker, current_price, shares, datetime.now().strftime('%Y-%m-%d'))
                new_cash = current_balance - total_cost
                save_balance(datetime.now().strftime('%Y-%m-%d'), new_cash, 0)
                st.success(f"✅ Куплено {shares} акций {selected_ticker} по {current_price:.2f} ₽")
                st.rerun()
            else:
                st.error(f"❌ Недостаточно средств. Нужно: {total_cost:,.0f} ₽")

    st.divider()

    st.markdown("### 📋 Открытые позиции")

    if len(portfolio) > 0:
        portfolio_display = portfolio[['ticker', 'entry_price', 'shares', 'entry_date']].copy()
        portfolio_display.columns = ['Тикер', 'Цена входа', 'Кол-во', 'Дата покупки']

        current_prices = []
        pnl = []
        for _, row in portfolio.iterrows():
            current_price = latest[latest['Ticker'] == row['ticker']]['Price'].values[0]
            current_prices.append(current_price)
            pnl.append((current_price - row['entry_price']) * row['shares'])

        portfolio_display['Текущая цена'] = current_prices
        portfolio_display['P&L, ₽'] = pnl
        portfolio_display['P&L, %'] = (
                    (portfolio_display['Текущая цена'] - portfolio_display['Цена входа']) / portfolio_display[
                'Цена входа'] * 100).round(2)

        st.dataframe(portfolio_display, use_container_width=True, hide_index=True)

        st.markdown("###  Продажа позиций")
        sell_ticker = st.selectbox("Выберите позицию для продажи:", portfolio['ticker'].unique())

        if st.button(" ПРОДАТЬ", use_container_width=True):
            current_price = latest[latest['Ticker'] == sell_ticker]['Price'].values[0]
            position = portfolio[portfolio['ticker'] == sell_ticker].iloc[0]
            proceeds = current_price * position['shares']

            close_position(sell_ticker, current_price, datetime.now().strftime('%Y-%m-%d'))

            new_cash = current_balance + proceeds
            save_balance(datetime.now().strftime('%Y-%m-%d'), new_cash, 0)
            st.success(f"✅ Продано {position['shares']} акций {sell_ticker} по {current_price:.2f} ₽")
            st.rerun()
    else:
        st.info("📭 Портфель пуст. Купите акции выше.")

# ============================================================================
# ВКЛАДКА 3: ПОРТФЕЛЬ И БАЛАНС
# ============================================================================
with tab3:
    st.subheader(" История портфеля")

    balance_history = get_balance()
    closed_trades = get_closed_trades()

    if len(balance_history) > 0:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=pd.to_datetime(balance_history['date']),
            y=balance_history['total_value'],
            mode='lines+markers',
            name='Общий капитал',
            line=dict(color='green', width=3)
        ))
        fig.add_hline(y=INITIAL_CAPITAL, line_dash="dash", line_color="gray", annotation_text="Начальный капитал")
        fig.update_layout(title="Рост капитала портфеля", xaxis_title="Дата", yaxis_title="Капитал, ₽", height=400,
                          template='plotly_white')
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("📊 История баланса пуста.")

    st.divider()

    st.markdown("### 📝 История сделок")

    if len(closed_trades) > 0:
        trades_display = closed_trades[
            ['ticker', 'entry_price', 'exit_price', 'shares', 'entry_date', 'exit_date', 'actual_return']].copy()
        trades_display.columns = ['Тикер', 'Цена входа', 'Цена выхода', 'Кол-во', 'Дата покупки', 'Дата продажи',
                                  'Доходность']
        trades_display['Доходность'] = (trades_display['Доходность'] * 100).round(2).astype(str) + '%'
        trades_display['Прибыль, ₽'] = (
                    (trades_display['Цена выхода'] - trades_display['Цена входа']) * trades_display['Кол-во']).round(0)

        st.dataframe(trades_display, use_container_width=True, hide_index=True)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Всего сделок", len(closed_trades))
        col2.metric("Прибыльных", len(closed_trades[closed_trades['actual_return'] > 0]))
        col3.metric("Win Rate",
                    f"{len(closed_trades[closed_trades['actual_return'] > 0]) / len(closed_trades) * 100:.1f}%")
        col4.metric("Средняя доходность", f"{closed_trades['actual_return'].mean() * 100:.2f}%")
    else:
        st.info("📝 Закрытых сделок пока нет.")

# ============================================================================
# ВКЛАДКА 4: ПРОДВИНУТАЯ АНАЛИТИКА
# ============================================================================
with tab4:
    st.subheader("🧪 Продвинутая аналитика модели")

    signals_db = pd.read_sql("SELECT * FROM signals", sqlite3.connect('paper_trading.db'))
    closed_trades = get_closed_trades()

    if len(signals_db) < 10:
        st.warning("⚠️ Недостаточно данных. Накопите минимум 10 сигналов.")
    else:
        st.markdown("### 1️⃣ Information Coefficient (IC)")
        st.caption("Корреляция Спирмена между предсказанной вероятностью и фактической доходностью. > 0.05 = хорошо.")

        if len(closed_trades) > 5:
            merged = signals_db.merge(closed_trades[['ticker', 'entry_date', 'actual_return']],
                                      left_on=['ticker', 'signal_date'],
                                      right_on=['ticker', 'entry_date'],
                                      how='inner')

            if len(merged) > 5:
                ic, p_value = spearmanr(merged['probability'], merged['actual_return'])

                col1, col2, col3 = st.columns(3)
                col1.metric("IC (Spearman)", f"{ic:.4f}")
                col2.metric("p-value", f"{p_value:.4f}")
                col3.metric("Оценка", "✅ Хороший" if ic > 0.05 else "️ Слабый")
            else:
                st.info("Недостаточно сопоставленных данных.")
        else:
            st.info("Нужно минимум 5 закрытых сделок.")

        st.divider()

        st.markdown("### 2️⃣ Hit Rate по квантилям")
        st.caption("Разделяем сигналы на 5 групп по вероятности и смотрим монотонность доходности.")

        if len(closed_trades) > 10:
            signals_with_returns = signals_db.merge(closed_trades[['ticker', 'entry_date', 'actual_return']],
                                                    left_on=['ticker', 'signal_date'],
                                                    right_on=['ticker', 'entry_date'],
                                                    how='inner')

            if len(signals_with_returns) > 10:
                signals_with_returns['quantile'] = pd.qcut(signals_with_returns['probability'], 5,
                                                           labels=['Q1 (низкая)', 'Q2', 'Q3', 'Q4', 'Q5 (высокая)'])

                quantile_stats = signals_with_returns.groupby('quantile').agg({
                    'actual_return': ['mean', 'count', lambda x: (x > 0).mean()]
                }).round(4)
                quantile_stats.columns = ['Средняя доходность', 'Кол-во', 'Hit Rate']

                st.dataframe(quantile_stats, use_container_width=True)

                returns = quantile_stats['Средняя доходность'].values
                if all(returns[i] <= returns[i + 1] for i in range(len(returns) - 1)):
                    st.success("✅ Монотонный рост — модель работает корректно!")
                else:
                    st.warning("️ Немонотонный рост — модель требует доработки.")
            else:
                st.info("Недостаточно данных.")
        else:
            st.info("Нужно минимум 10 закрытых сделок.")

st.markdown("---")
st.caption("Инструмент для количественного анализа. Используйте данные ответственно.")