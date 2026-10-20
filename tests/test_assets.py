from decimal import Decimal

import pytest

from app.services import assets
from app.util import AppError


def type_id(conn, name):
    return conn.execute("SELECT id FROM asset_types WHERE name=?", (name,)).fetchone()["id"]


@pytest.fixture
def setup(conn):
    bank = assets.save_account(conn, {"name": "생활비 통장", "type_id": type_id(conn, "은행 예금·적금"), "institution": "OO은행"})
    broker = assets.save_account(conn, {"name": "카카오페이증권", "type_id": type_id(conn, "주식"), "institution": "카카오페이증권"})
    sec = assets.save_security(conn, {"symbol": "005930", "name": "삼성전자"})
    return conn, bank["id"], broker["id"], sec["id"]


def tx(conn, **kw):
    return assets.create_txn(conn, kw)


def test_transfer_is_not_income(setup):
    conn, bank, broker, _ = setup
    tx(conn, kind="deposit", date="2026-09-01", account_id=bank, amount=1_000_000)
    tx(conn, kind="transfer", date="2026-09-02", account_id=bank, to_account_id=broker, amount=400_000)
    s = assets.summary(conn, "2026-09-30")
    assert s["total"] == 1_000_000
    assert s["external"] == 1_000_000
    assert s["profit"] == 0
    acc = {a["name"]: a for a in s["accounts"]}
    assert acc["생활비 통장"]["value"] == 600_000 and acc["카카오페이증권"]["value"] == 400_000
    assert acc["카카오페이증권"]["profit"] == 0  # 이체 입금은 수익이 아니다


def test_buy_sell_realized_unrealized_identity(setup):
    conn, bank, broker, sec = setup
    tx(conn, kind="deposit", date="2026-01-02", account_id=broker, amount=2_000_000)
    tx(conn, kind="buy", date="2026-01-03", account_id=broker, security_id=sec, quantity="10", price="60000", fee=100)
    tx(conn, kind="buy", date="2026-02-03", account_id=broker, security_id=sec, quantity="10", price="70000", fee=100)
    # 평균단가 = (600100 + 700100) / 20 = 65010
    tx(conn, kind="sell", date="2026-03-03", account_id=broker, security_id=sec, quantity="5", price="80000", fee=500)
    tx(conn, kind="dividend", date="2026-04-01", account_id=broker, security_id=sec, amount=3000)
    tx(conn, kind="fee", date="2026-04-02", account_id=broker, amount=1000)
    assets.set_price(conn, sec, "2026-04-30", "75000")
    s = assets.summary(conn, "2026-04-30")
    a = next(x for x in s["accounts"] if x["name"] == "카카오페이증권")
    # 현금: 2,000,000 - 600,100 - 700,100 + (400,000 - 500) + 3,000 - 1,000
    assert a["cash"] == 1_101_300
    h = next(x for x in s["holdings"] if x["symbol"] == "005930")
    assert h["quantity"] == "15"
    assert Decimal(h["avg_cost"]) == Decimal("65010.00")
    assert h["value"] == 1_125_000
    # 실현손익 = 399,500 - 5*65,010 = 74,450
    assert a["realized"] == 74_450
    assert a["unrealized"] == 1_125_000 - 975_150
    # 항등식: 평가액 - 순투입 = 실현 + 평가 + 배당 + 이자 - 수수료 + 평가액변동
    assert a["profit"] == a["value"] - a["contrib"]
    assert a["profit"] == a["realized"] + a["unrealized"] + a["dividends"] + a["interest"] - a["fees"] + a["valuation_adj"]
    assert s["profit"] == a["profit"]


def test_oversell_rejected_and_rolled_back(setup):
    conn, _, broker, sec = setup
    tx(conn, kind="deposit", date="2026-01-02", account_id=broker, amount=1_000_000)
    tx(conn, kind="buy", date="2026-01-03", account_id=broker, security_id=sec, quantity="3", price="1000")
    with pytest.raises(AppError):
        tx(conn, kind="sell", date="2026-01-04", account_id=broker, security_id=sec, quantity="4", price="1000")
    assert conn.execute("SELECT COUNT(*) FROM asset_txns").fetchone()[0] == 2
    # 이전 날짜에 매도하는 것도 거부(시간 순서 검증)
    with pytest.raises(AppError):
        tx(conn, kind="sell", date="2026-01-02", account_id=broker, security_id=sec, quantity="1", price="1000")
    # 매수 기록을 지워서 매도가 모순이 되는 경우도 거부
    tx(conn, kind="sell", date="2026-01-05", account_id=broker, security_id=sec, quantity="3", price="1000")
    buy_id = conn.execute("SELECT id FROM asset_txns WHERE kind='buy'").fetchone()[0]
    with pytest.raises(AppError):
        assets.delete_txn(conn, buy_id)
    assert conn.execute("SELECT COUNT(*) FROM asset_txns WHERE id=?", (buy_id,)).fetchone()[0] == 1


def test_fractional_shares(setup):
    conn, _, broker, sec = setup
    tx(conn, kind="deposit", date="2026-01-02", account_id=broker, amount=100_000)
    tx(conn, kind="buy", date="2026-01-03", account_id=broker, security_id=sec, quantity="0.5", price="61000")
    s = assets.summary(conn, "2026-01-03")
    h = s["holdings"][0]
    assert h["quantity"] == "0.5" and h["value"] == 30500


def test_valuation_and_history(setup):
    conn, bank, broker, sec = setup
    other = assets.save_account(conn, {"name": "전세보증금", "type_id": type_id(conn, "기타 자산")})["id"]
    tx(conn, kind="deposit", date="2026-01-10", account_id=bank, amount=1_000_000)
    tx(conn, kind="adjustment", date="2026-01-10", account_id=other, amount=50_000_000, memo="초기 잔액")
    tx(conn, kind="interest", date="2026-02-25", account_id=bank, amount=1_000)
    tx(conn, kind="deposit", date="2026-02-26", account_id=bank, amount=500_000)
    tx(conn, kind="valuation", date="2026-03-01", account_id=other, amount=-1_000_000)
    h = assets.history(conn, "2026-01", "2026-03")["months"]
    jan, feb, mar = h
    assert jan["total"] == 51_000_000 and jan["flow"] == 51_000_000 and jan["profit"] == 0
    assert feb["change"] == 501_000 and feb["flow"] == 500_000 and feb["profit"] == 1_000
    assert mar["change"] == -1_000_000 and mar["flow"] == 0 and mar["profit"] == -1_000_000
    s = assets.summary(conn, "2026-03-31")
    assert s["by_liquidity"]["cash"] == 1_501_000
    assert s["by_liquidity"]["other"] == 49_000_000
    assert s["change_vs_prev_month"] == -1_000_000 and s["change_profit"] == -1_000_000


def test_cash_vs_investment_split(setup):
    conn, bank, broker, sec = setup
    tx(conn, kind="deposit", date="2026-01-02", account_id=broker, amount=100_000)
    tx(conn, kind="buy", date="2026-01-03", account_id=broker, security_id=sec, quantity="1", price="60000")
    s = assets.summary(conn, "2026-01-03")
    assert s["by_liquidity"]["investment"] == 60_000
    assert s["by_liquidity"]["cash"] == 40_000  # 증권계좌 예수금은 현금성


def test_txn_validation(setup):
    conn, bank, broker, sec = setup
    with pytest.raises(AppError):
        tx(conn, kind="transfer", date="2026-01-02", account_id=bank, to_account_id=bank, amount=1)
    with pytest.raises(AppError):
        tx(conn, kind="deposit", date="2026-01-02", account_id=bank, amount=-5)
    with pytest.raises(AppError):
        tx(conn, kind="buy", date="2026-01-02", account_id=broker, quantity="1", price="1")
    with pytest.raises(AppError):
        tx(conn, kind="deposit", date="2026-01-02", account_id=bank, amount=1, fee=10)


def test_account_delete_deactivates(setup):
    conn, bank, *_ = setup
    tx(conn, kind="deposit", date="2026-01-02", account_id=bank, amount=1)
    assert assets.delete_account(conn, bank)["action"] == "deactivated"
