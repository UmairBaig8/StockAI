use crate::broker::types::Quote;
use crate::orderbook::book::OrderBook;
use rust_decimal::prelude::ToPrimitive;
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::{mpsc, RwLock};
use tracing::{debug, info};

pub type PriceMap = Arc<RwLock<HashMap<String, f64>>>;

pub struct MarketFeed {
    books: HashMap<String, OrderBook>,
    quote_rx: mpsc::Receiver<Quote>,
    prices: Option<PriceMap>,
}

impl MarketFeed {
    pub fn new(quote_rx: mpsc::Receiver<Quote>) -> Self {
        Self {
            books: HashMap::new(),
            quote_rx,
            prices: None,
        }
    }

    pub fn with_prices(quote_rx: mpsc::Receiver<Quote>, prices: PriceMap) -> Self {
        Self {
            books: HashMap::new(),
            quote_rx,
            prices: Some(prices),
        }
    }

    pub fn get_or_create_book(&mut self, ticker: &str) -> &mut OrderBook {
        self.books
            .entry(ticker.to_string())
            .or_insert_with(|| OrderBook::new(ticker))
    }

    pub fn get_book(&self, ticker: &str) -> Option<&OrderBook> {
        self.books.get(ticker)
    }

    pub fn apply_quote(&mut self, quote: &Quote) {
        let prices = self.prices.clone();
        let book = self.get_or_create_book(&quote.ticker);
        book.update_bid(quote.bid, quote.bid_qty);
        book.update_ask(quote.ask, quote.ask_qty);
        debug!(
            "{} bid={} ask={} spread={:?}",
            quote.ticker,
            quote.bid,
            quote.ask,
            book.spread()
        );
        // Update shared price map with mid price
        if let Some(prices) = prices {
            if let Some(mid) = book.mid_price() {
                let mid_f64: f64 = mid.to_f64().unwrap_or(0.0);
                let ticker = quote.ticker.clone();
                if let Ok(mut map) = prices.try_write() {
                    map.insert(ticker, mid_f64);
                }
            }
        }
    }

    pub async fn run(&mut self) {
        info!("Market feed processor started");
        while let Some(quote) = self.quote_rx.recv().await {
            self.apply_quote(&quote);
        }
        info!("Market feed processor stopped");
    }
}
