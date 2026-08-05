#!/usr/bin/env python3
"""
OzMoEg Money Maker — Webull Official OpenAPI Client
Uses App Key + App Secret with HMAC-SHA256 signatures.
https://developer.webull.com.au/apis/docs/about-open-api
"""
import logging
import time
import hashlib
import hmac
import base64
import json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

def _change_pct_from_ranking(item: Dict) -> float:
    """Extract change percentage from a Webull ranking payload (legacy shape)."""
    if not isinstance(item, dict):
        return 0.0
    t = item.get('ticker', {}) if isinstance(item.get('ticker'), dict) else item
    values = item.get('values', {}) if isinstance(item, dict) else {}
    # Try explicit change ratio fields first
    for key in ('changeRatio', 'change_ratio', 'change'):
        v = values.get(key) if isinstance(values, dict) else t.get(key)
        if v is not None:
            try:
                fv = float(v)
                return (fv - 1) * 100 if fv > 1 else fv * 100
            except (TypeError, ValueError):
                continue
    # Derive from price vs close
    close = float(t.get('close', 0) or 0)
    price = float(t.get('pprice', 0) or values.get('price', 0) or 0)
    if close > 0 and price > 0:
        return (price - close) / close * 100
    return 0.0


class AuthenticationError(Exception):
    pass

class WebullClient:
    """
    Webull Official OpenAPI client.
    Authentication: App Key + App Secret (HMAC-SHA256) + Access Token
    """

    BASE_URL = "https://openapi.webull.com.au/api"
    
    def __init__(self, config: Dict[str, Any]):
        self.cfg = config
        self.region_code = int(config.get('region_code', 6))
        self.market = str(config.get('market', 'us')).lower()
        self.is_au = self.market == 'au' or self.region_code == 18
        self.paper_mode = config.get('paper_mode', True)
        self.use_official = config.get('use_official_api', False)
        self.app_key = config.get('app_key', '')
        self.app_secret = config.get('app_secret', '')
        self.access_token = config.get('access_token', '')
        self.account_id = config.get('account_id', '')
        
        if self.use_official and self.app_key and self.app_secret:
            self._openapi_auth()
        else:
            if self.use_official:
                logger.warning("Official API requested but no App Key/Secret — falling back to legacy")
            else:
                logger.info("Using legacy webull library (community API)")
            self._legacy_login()

    def _openapi_auth(self):
        """Verify OpenAPI credentials."""
        logger.info("Webull OpenAPI mode. Paper: %s", self.paper_mode)
        if not self.access_token:
            logger.warning("No access_token provided — some endpoints may fail")

    def _legacy_login(self):
        """Fallback to unofficial webull library if no official API keys."""
        try:
            # Always use the real webull class so region_code is honoured for data calls.
            # paper_webull does not accept region_code and defaults to US.
            from webull import webull
            self._legacy_wb = webull(region_code=self.region_code)
            logger.info("Legacy Webull client initialized for region_code=%s", self.region_code)
            
            # Try to login (needed for trade/account endpoints, but public data works without it)
            mfa = self.cfg.get('mfa', '')
            result = self._legacy_wb.login(
                self.cfg.get('email', ''),
                self.cfg.get('password', ''),
                mfa=mfa
            )
            if result and 'accessToken' in result:
                logger.info("Legacy Webull login successful")
            else:
                logger.warning("Legacy login returned: %s — continuing in unauthenticated mode (public data only)", result)
        except Exception as e:
            logger.error("Legacy Webull login failed: %s — continuing in unauthenticated mode (public data only)", e)
            # Ensure _legacy_wb is still set so public-data calls can proceed
            if not hasattr(self, '_legacy_wb') or self._legacy_wb is None:
                from webull import paper_webull
                self._legacy_wb = paper_webull()

    def _sign_request(self, method: str, endpoint: str, timestamp: str, body: str = '') -> str:
        """Generate HMAC-SHA256 signature for official API."""
        message = f"{method}{endpoint}{timestamp}{body}"
        signature = hmac.new(
            self.app_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).digest()
        return base64.b64encode(signature).decode('utf-8')

    def _build_headers(self, method: str, endpoint: str, body: str = '') -> Dict[str, str]:
        """Build headers with signature for official API."""
        timestamp = str(int(time.time() * 1000))
        signature = self._sign_request(method, endpoint, timestamp, body)
        headers = {
            'Content-Type': 'application/json',
            'App-Key': self.app_key,
            'Timestamp': timestamp,
            'Signature': signature
        }
        if self.access_token:
            headers['Access-Token'] = self.access_token
        return headers

    def _api_request(self, method: str, endpoint: str, params: Dict = None, 
                     json_data: Dict = None) -> Optional[Dict]:
        """Make a signed API request to Webull OpenAPI."""
        url = f"{self.BASE_URL}{endpoint}"
        body = json.dumps(json_data) if json_data else ''
        headers = self._build_headers(method, endpoint, body)
        
        try:
            if method.upper() == 'GET':
                resp = requests.get(url, headers=headers, params=params, timeout=15)
            elif method.upper() == 'POST':
                resp = requests.post(url, headers=headers, json=json_data, timeout=15)
            else:
                resp = requests.request(method, url, headers=headers, json=json_data, timeout=15)
            
            if resp.status_code == 200:
                return resp.json()
            else:
                logger.error("API error %s: %s", resp.status_code, resp.text)
                return None
        except Exception as e:
            logger.error("API request failed: %s", e)
            return None

    def get_quote(self, ticker: str, tId: int = None) -> Optional[Dict]:
        """Fetch real-time quote via official OpenAPI or legacy library.
        For AU (region 18), the legacy library cannot resolve symbols to tickerIds,
        so callers should pass the Webull tickerId when available.
        """
        if self.use_official and self.app_key and self.app_secret:
            params = {'ticker': ticker}
            if tId:
                params['tickerId'] = tId
            return self._api_request('GET', f'/quote/tickerRealtime', params)
        # Fallback to legacy
        if hasattr(self, '_legacy_wb') and self._legacy_wb:
            try:
                if tId:
                    return self._legacy_wb.get_quote(tId=tId)
                return self._legacy_wb.get_quote(stock=ticker)
            except Exception as e:
                logger.warning("Legacy get_quote failed: %s", e)
        return {}

    def get_quotes(self, tickers: list, max_workers: int = 10, ticker_ids: Dict[str, int] = None) -> Dict[str, Dict]:
        """Fetch detailed quotes for multiple tickers in parallel."""
        if not tickers:
            return {}
        ticker_ids = ticker_ids or {}
        quotes = {}
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            future_to_ticker = {ex.submit(self.get_quote, t, ticker_ids.get(str(t).upper())): t for t in tickers}
            for future in as_completed(future_to_ticker):
                t = future_to_ticker[future]
                try:
                    q = future.result(timeout=10)
                    if q:
                        quotes[t] = q
                except Exception as e:
                    logger.debug("Quote failed for %s: %s", t, e)
        return quotes

    def get_bars(self, ticker: str, tId: int = None, interval: str = 'm1', count: int = 100) -> Optional[list]:
        """Fetch OHLCV bars."""
        if self.use_official and self.app_key and self.app_secret:
            params = {'ticker': ticker, 'type': interval, 'count': count}
            if tId:
                params['tickerId'] = tId
            return self._api_request('GET', '/quote/tickerChart', params)
        if hasattr(self, '_legacy_wb') and self._legacy_wb:
            try:
                if tId:
                    return self._legacy_wb.get_bars(tId=tId, interval=interval, count=count)
                return self._legacy_wb.get_bars(stock=ticker, interval=interval, count=count)
            except Exception as e:
                logger.warning("Legacy get_bars failed: %s", e)
        return []

    def get_news(self, ticker: str, tId: int = None, items: int = 20) -> Optional[list]:
        """Fetch news items."""
        if self.use_official and self.app_key and self.app_secret:
            params = {'ticker': ticker, 'count': items}
            if tId:
                params['tickerId'] = tId
            return self._api_request('GET', '/information/news', params)
        if hasattr(self, '_legacy_wb') and self._legacy_wb:
            try:
                if tId:
                    return self._legacy_wb.get_news(tId=tId, items=items)
                return self._legacy_wb.get_news(stock=ticker, items=items)
            except Exception as e:
                logger.warning("Legacy get_news failed: %s", e)
        return []

    def active_gainer_loser(self, direction: str = 'gainer', region: str = None,
                            rank_type: str = 'rank', num: int = 50,
                            count: int = None) -> Optional[list]:
        """Get top gainers/losers/active, normalised to {gainer_list, loser_list}."""
        # Use count if provided, otherwise num (legacy signature compatibility)
        if count is not None:
            num = count
        # Use the client's configured region/market by default
        if region is None:
            region = str(self.region_code)

        raw = None
        if self.use_official and self.app_key and self.app_secret:
            raw = self._api_request('GET', '/quote/ranking', {
                'direction': direction,
                'region': region,
                'rankType': rank_type,
                'pageSize': num
            })
        elif hasattr(self, '_legacy_wb') and self._legacy_wb:
            try:
                raw = self._legacy_wb.active_gainer_loser(direction=direction, rank_type=rank_type, count=num)
            except (TypeError, ValueError) as te:
                logger.warning("Legacy active_gainer_loser failed: %s", te)

        if not raw:
            return {"gainer_list": [], "loser_list": []}

        # Normalise the multiple response shapes from Webull.
        # Official API returns a list; legacy returns dict with either
        # 'gainer_list'/'loser_list' or 'data' array.
        if isinstance(raw, list):
            return {"gainer_list": raw, "loser_list": []}

        if isinstance(raw, dict):
            if 'gainer_list' in raw or 'loser_list' in raw:
                return {
                    "gainer_list": raw.get('gainer_list', []),
                    "loser_list": raw.get('loser_list', []),
                }
            data = raw.get('data', [])
            # The legacy endpoint returns combined data with positive/negative change.
            # Split by change direction so callers get both lists in one call.
            gainers = [item for item in data if _change_pct_from_ranking(item) >= 0]
            losers = [item for item in data if _change_pct_from_ranking(item) < 0]
            return {"gainer_list": gainers, "loser_list": losers}

        return {"gainer_list": [], "loser_list": []}

    def get_account(self) -> Optional[Dict]:
        """Get account info."""
        if self.use_official and self.app_key and self.app_secret:
            return self._api_request('GET', '/account')
        if hasattr(self, '_legacy_wb') and self._legacy_wb:
            try:
                return self._legacy_wb.get_account()
            except Exception as e:
                logger.warning("Legacy get_account failed: %s", e)
        return {}

    def get_positions(self) -> Optional[list]:
        """Get current positions."""
        if self.use_official and self.app_key and self.app_secret:
            return self._api_request('GET', '/account/positions')
        if hasattr(self, '_legacy_wb') and self._legacy_wb:
            try:
                return self._legacy_wb.get_positions()
            except Exception as e:
                logger.warning("Legacy get_positions failed: %s", e)
        return []

    def place_order(self, stock: str, price: float, action: str, quant: int,
                    order_type: str = 'LMT', time_in_force: str = 'DAY',
                    **kwargs) -> Dict:
        """Place a stock order."""
        if self.paper_mode:
            import uuid
            order_id = 'paper_' + str(uuid.uuid4())[:8]
            logger.info("[PAPER] Order: %s %s %s @ %.2f (ID: %s)",
                        action, quant, stock, price, order_id)
            return {'orderId': order_id, 'status': 'PAPER_FILLED'}

        if self.use_official and self.app_key and self.app_secret:
            return self._api_request('POST', '/trade/order', json_data={
                'ticker': stock,
                'price': price,
                'action': action,
                'quantity': quant,
                'orderType': order_type,
                'timeInForce': time_in_force
            })
        if hasattr(self, '_legacy_wb') and self._legacy_wb:
            try:
                return self._legacy_wb.place_order(
                    stock=stock, price=price, action=action, quant=quant,
                    orderType=order_type, timeInForce=time_in_force, **kwargs
                )
            except Exception as e:
                logger.error("Legacy place_order failed: %s", e)
        return {}

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        if self.paper_mode:
            logger.info("[PAPER] Cancel order %s", order_id)
            return True
        if self.use_official and self.app_key and self.app_secret:
            result = self._api_request('POST', '/trade/order/cancel', json_data={'orderId': order_id})
            return result is not None
        if hasattr(self, '_legacy_wb') and self._legacy_wb:
            try:
                return self._legacy_wb.cancel_order(order_id=order_id)
            except Exception as e:
                logger.error("Legacy cancel_order failed: %s", e)
        return False

    def get_orders(self) -> Optional[list]:
        """Get open orders."""
        if self.use_official and self.app_key and self.app_secret:
            return self._api_request('GET', '/trade/orders')
        if hasattr(self, '_legacy_wb') and self._legacy_wb:
            try:
                return self._legacy_wb.get_current_orders()
            except Exception as e:
                logger.warning("Legacy get_orders failed: %s", e)
        return []
