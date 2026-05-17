use crate::broker::types::OrderSide;
use rust_decimal::Decimal;
use std::collections::BTreeMap;

#[derive(Debug, Clone, Default)]
pub struct OrderBook {
    pub ticker: String,
    pub bids: BTreeMap<PriceLevel, u64>,
    pub asks: BTreeMap<PriceLevel, u64>,
}

type PriceLevel = i64;

fn decimal_to_level(price: Decimal) -> PriceLevel {
    (price * Decimal::from(100)).to_string().parse().unwrap_or(0)
}

fn level_to_decimal(level: PriceLevel) -> Decimal {
    Decimal::from(level) / Decimal::from(100)
}

impl OrderBook {
    pub fn new(ticker: &str) -> Self {
        Self {
            ticker: ticker.into(),
            bids: BTreeMap::new(),
            asks: BTreeMap::new(),
        }
    }

    pub fn update_bid(&mut self, price: Decimal, qty: u64) {
        let level = decimal_to_level(price);
        if qty == 0 {
            self.bids.remove(&level);
        } else {
            self.bids.insert(level, qty);
        }
    }

    pub fn update_ask(&mut self, price: Decimal, qty: u64) {
        let level = decimal_to_level(price);
        if qty == 0 {
            self.asks.remove(&level);
        } else {
            self.asks.insert(level, qty);
        }
    }

    pub fn best_bid(&self) -> Option<(Decimal, u64)> {
        self.bids.last_key_value()
            .map(|(k, v)| (level_to_decimal(*k), *v))
    }

    pub fn best_ask(&self) -> Option<(Decimal, u64)> {
        self.asks.first_key_value()
            .map(|(k, v)| (level_to_decimal(*k), *v))
    }

    pub fn spread(&self) -> Option<Decimal> {
        match (self.best_bid(), self.best_ask()) {
            (Some((bid, _)), Some((ask, _))) => Some(ask - bid),
            _ => None,
        }
    }

    pub fn mid_price(&self) -> Option<Decimal> {
        match (self.best_bid(), self.best_ask()) {
            (Some((bid, _)), Some((ask, _))) => Some((bid + ask) / Decimal::from(2)),
            _ => None,
        }
    }

    pub fn depth_at(&self, price: Decimal, side: &OrderSide) -> u64 {
        let level = decimal_to_level(price);
        match side {
            OrderSide::Buy => self.bids.get(&level).copied().unwrap_or(0),
            OrderSide::Sell => self.asks.get(&level).copied().unwrap_or(0),
        }
    }
}
