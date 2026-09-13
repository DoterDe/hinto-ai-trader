import type { Market } from "../types";
import { numeric } from "./format";

export function latestPrice(market?: Market) {
  if (!market) return { value: null, stream: undefined };
  const values = [
    market.trade && {
      value: market.trade.price,
      event: market.trade.event_time,
      key: "trade",
    },
    market.candle && {
      value: market.candle.close,
      event: market.candle.event_time,
      key: `kline:${market.candle.interval}`,
    },
  ].filter((item): item is NonNullable<typeof item> => item !== null);
  const item = values.sort(
    (a, b) => Date.parse(b.event) - Date.parse(a.event),
  )[0];
  return {
    value: item?.value ?? null,
    stream: item ? market.streams[item.key] : undefined,
  };
}
export function publicContext(market: Market) {
  const bid = numeric(market.book_ticker?.bid_price),
    ask = numeric(market.book_ticker?.ask_price);
  const mark = numeric(market.mark_price?.mark_price),
    index = numeric(market.mark_price?.index_price);
  return {
    spread: bid !== null && ask !== null && ask >= bid ? ask - bid : null,
    basis: mark !== null && index !== null ? mark - index : null,
  };
}
