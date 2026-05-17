use crate::broker::types::Quote;
use crate::orderbook::book::OrderBook;
use std::collections::HashMap;
use tokio::sync::mpsc;
use tracing::{debug, info};

pub struct MarketFeed {
    books: HashMap<String, OrderBook>,
    quote_rx: mpsc::Receiver<Quote>,
}

impl MarketFeed {
    pub fn new(quote_rx: mpsc::Receiver<Quote>) -> Self {
        Self {
            books: HashMap::new(),
            quote_rx,
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
    }

    pub async fn run(&mut self) {
        info!("Market feed processor started");
        while let Some(quote) = self.quote_rx.recv().await {
            self.apply_quote(&quote);
        }
        info!("Market feed processor stopped");
    }
}
