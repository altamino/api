"""GET /g/s/wallet/coin/history — coin statement read by CoinHistoryFragment (APK 3.4)."""

from time import time as timestamp

from fastapi import APIRouter, Request
from pymongo import DESCENDING

from helpers.routers.cachable import CachableRoute
from helpers.community_access import page, paging
from helpers.database.mongo import Database
from helpers.decorators.validauth import validauth_required
from objects import Base

wallet_history = APIRouter()
wallet_history.route_class = CachableRoute

# reason -> (sourceType, {lang: description})
REASONS = {
    "tip_sent": (
        3,
        {
            "en": "Coins sent as a tip",
            "pt": "Moedas enviadas como gorjeta",
            "es": "Monedas enviadas como propina",
        },
    ),
    "tip_received": (
        4,
        {
            "en": "Coins received as a tip",
            "pt": "Moedas recebidas de gorjeta",
            "es": "Monedas recibidas como propina",
        },
    ),
    "daily_reward": (
        1,
        {
            "en": "Daily check-in reward",
            "pt": "Recompensa do check-in diário",
            "es": "Recompensa del check-in diario",
        },
    ),
    "lottery_reward": (
        6,
        {
            "en": "Lucky Draw reward",
            "pt": "Prêmio do sorteio diário",
            "es": "Premio del sorteo diario",
        },
    ),
    "checkin_repair": (
        2,
        {
            "en": "Check-in streak repair",
            "pt": "Reparo da sequência de check-in",
            "es": "Reparación de la racha de check-in",
        },
    ),
    "active_time_reward": (
        1,
        {
            "en": "Reward for time online",
            "pt": "Recompensa por tempo online",
            "es": "Recompensa por tiempo en línea",
        },
    ),
    "store_purchase": (
        7,
        {"en": "Store purchase", "pt": "Compra na loja", "es": "Compra en la tienda"},
    ),
    "fan_subscription": (
        16,
        {
            "en": "Fan club subscription",
            "pt": "Assinatura de fã-clube",
            "es": "Suscripción al club de fans",
        },
    ),
    "fan_income": (
        16,
        {
            "en": "Fan club income",
            "pt": "Ganhos do fã-clube",
            "es": "Ingresos del club de fans",
        },
    ),
    "amino_plus_subscription": (
        0,
        {
            "en": "Amino+ membership",
            "pt": "Assinatura Amino+",
            "es": "Membresía Amino+",
        },
    ),
}
DEFAULT = (
    0,
    {
        "en": "Coin transaction",
        "pt": "Movimentação de moedas",
        "es": "Movimiento de monedas",
    },
)


def _lang(request: Request) -> str:
    lang = (getattr(request.state, "lang", "en") or "en").lower()
    return "pt" if lang.startswith("pt") else "es" if lang.startswith("es") else "en"


@wallet_history.get("/g/s/wallet/coin/history")
@validauth_required
async def coin_history(
    request: Request, start: int = 0, size: int = 25, pageToken: str | None = None
):
    t1 = timestamp()
    uid = request.state.session["uid"]
    start, size = page(start, size, pageToken)
    lang = _lang(request)

    db = await Database().init()
    try:
        table = db.get(table="CoinHistory")
        total = await table.count_documents({"uid": uid})
        rows = [
            row
            async for row in table.find({"uid": uid})
            .sort([("seq", DESCENDING)])
            .skip(start)
            .limit(size)
        ]
    finally:
        db.close()

    items = []
    for row in rows:
        source_type, texts = REASONS.get(row.get("reason"), DEFAULT)
        amount = float(row.get("amount", 0))
        ext = row.get("ext") or {}
        items.append(
            {
                "uid": uid,
                "sourceType": source_type,
                "createdTime": row.get("createdTime"),
                "changedCoins": int(round(amount)),
                "originCoinsFloat": amount,
                "taxCoinsFloat": 0.0,
                "bonusCoinsFloat": 0.0,
                "totalCoins": int(row.get("balanceAfter", 0)),
                "extData": {
                    "description": texts.get(lang, texts["en"]),
                    "subtitle": str(ext.get("title") or "")[:120],
                    "objectDeeplinkUrl": None,
                },
            }
        )
    return Base.Answer(
        {
            "coinHistoryList": items,
            "allItemCount": total,
            "paging": paging(start, size, items),
        },
        spent_time=timestamp() - t1,
    )
