/**
 * TypeScript type definitions for trading dashboard
 */

export interface Position {
  stock_code: string;
  stock_name: string;
  quantity: number;
  average_buy_price: string;
  current_price: string;
  evaluation_amount: string;
  unrealized_pnl: string;
  unrealized_pnl_pct: string;
  strategy_name: string | null;
  updated_at: string;
}

export interface Portfolio {
  total_evaluation: string;
  total_unrealized_pnl: string;
  daily_realized_pnl: string;
  cash_balance: string;
  total_asset_value: string;
  position_count: number;
  total_return_pct: string;
  updated_at: string;
}

export interface Trade {
  order_id: string;
  stock_code: string;
  stock_name: string;
  order_type: 'BUY' | 'SELL';
  quantity: number;
  filled_price: string;
  filled_at: string;
  strategy_name: string | null;
  realized_pnl: string | null;
}

export interface DashboardSnapshot {
  positions: Position[];
  portfolio: Portfolio;
  trades_today: Trade[];
}

export type WSMessageType =
  | 'full_snapshot'
  | 'position_update'
  | 'portfolio_update'
  | 'trade_executed'
  | 'price_update'
  | 'connection_status'
  | 'ping';

export interface WSMessage {
  type: WSMessageType;
  data: unknown;
  timestamp: string;
}

export interface PositionUpdateData {
  stock_code: string;
  current_price: string;
  unrealized_pnl: string;
  unrealized_pnl_pct: string;
  evaluation_amount: string;
}

export interface ConnectionStatus {
  connected: boolean;
  lastUpdate: Date | null;
  reconnecting: boolean;
}

export function formatKRW(value: string | number): string {
  const num = typeof value === 'string' ? parseFloat(value) : value;
  return new Intl.NumberFormat('ko-KR', {
    style: 'currency',
    currency: 'KRW',
    maximumFractionDigits: 0,
  }).format(num);
}

export function formatPercent(value: string | number): string {
  const num = typeof value === 'string' ? parseFloat(value) : value;
  const sign = num >= 0 ? '+' : '';
  return `${sign}${num.toFixed(2)}%`;
}

export function formatNumber(value: string | number): string {
  const num = typeof value === 'string' ? parseFloat(value) : value;
  return new Intl.NumberFormat('ko-KR').format(num);
}
