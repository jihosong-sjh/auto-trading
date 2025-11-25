/**
 * Custom WebSocket hook for real-time dashboard updates
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type {
  ConnectionStatus,
  DashboardSnapshot,
  OrderStatusChangedData,
  PendingOrder,
  Portfolio,
  Position,
  PositionUpdateData,
  Trade,
  WSMessage,
} from '../types/trading';

const WS_URL = import.meta.env.DEV
  ? 'ws://localhost:8080/ws'
  : `ws://${window.location.host}/ws`;

const RECONNECT_DELAY = 1000;
const MAX_RECONNECT_DELAY = 30000;
const PING_INTERVAL = 30000;

interface UseDashboardWebSocketReturn {
  positions: Position[];
  portfolio: Portfolio | null;
  trades: Trade[];
  pendingOrders: PendingOrder[];
  connectionStatus: ConnectionStatus;
}

export function useDashboardWebSocket(): UseDashboardWebSocketReturn {
  const [positions, setPositions] = useState<Position[]>([]);
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [pendingOrders, setPendingOrders] = useState<PendingOrder[]>([]);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>({
    connected: false,
    lastUpdate: null,
    reconnecting: false,
  });

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectDelayRef = useRef(RECONNECT_DELAY);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const pingIntervalRef = useRef<number | null>(null);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    console.log('Connecting to WebSocket:', WS_URL);
    const ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      console.log('WebSocket connected');
      reconnectDelayRef.current = RECONNECT_DELAY;
      setConnectionStatus({
        connected: true,
        lastUpdate: new Date(),
        reconnecting: false,
      });

      // Start ping interval
      pingIntervalRef.current = window.setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send('ping');
        }
      }, PING_INTERVAL);
    };

    ws.onmessage = (event) => {
      try {
        // Handle pong
        if (event.data === 'pong') {
          return;
        }

        const message: WSMessage = JSON.parse(event.data);
        handleMessage(message);
      } catch (error) {
        console.error('Failed to parse WebSocket message:', error);
      }
    };

    ws.onclose = () => {
      console.log('WebSocket disconnected');
      setConnectionStatus((prev) => ({
        ...prev,
        connected: false,
        reconnecting: true,
      }));

      // Clear ping interval
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current);
      }

      // Schedule reconnect
      reconnectTimeoutRef.current = window.setTimeout(() => {
        reconnectDelayRef.current = Math.min(
          reconnectDelayRef.current * 2,
          MAX_RECONNECT_DELAY
        );
        connect();
      }, reconnectDelayRef.current);
    };

    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };

    wsRef.current = ws;
  }, []);

  const handleMessage = useCallback((message: WSMessage) => {
    setConnectionStatus((prev) => ({
      ...prev,
      lastUpdate: new Date(),
    }));

    switch (message.type) {
      case 'full_snapshot': {
        const snapshot = message.data as DashboardSnapshot;
        setPositions(snapshot.positions);
        setPortfolio(snapshot.portfolio);
        setTrades(snapshot.trades_today);
        setPendingOrders(snapshot.pending_orders || []);
        break;
      }

      case 'position_update': {
        const update = message.data as PositionUpdateData;
        setPositions((prev) =>
          prev.map((pos) =>
            pos.stock_code === update.stock_code
              ? {
                  ...pos,
                  current_price: update.current_price,
                  unrealized_pnl: update.unrealized_pnl,
                  unrealized_pnl_pct: update.unrealized_pnl_pct,
                  evaluation_amount: update.evaluation_amount,
                }
              : pos
          )
        );
        break;
      }

      case 'portfolio_update': {
        const portfolioData = message.data as Portfolio;
        setPortfolio(portfolioData);
        break;
      }

      case 'trade_executed': {
        const trade = message.data as Trade;
        setTrades((prev) => [trade, ...prev]);
        break;
      }

      case 'pending_orders_update': {
        const orders = message.data as PendingOrder[];
        setPendingOrders(orders);
        break;
      }

      case 'order_status_changed': {
        const statusChange = message.data as OrderStatusChangedData;
        // Update specific order in pending orders list
        setPendingOrders((prev) =>
          prev.map((order) =>
            order.order_id === statusChange.order_id
              ? {
                  ...order,
                  status: statusChange.status,
                  filled_quantity: statusChange.filled_quantity,
                  filled_price: statusChange.filled_price,
                }
              : order
          )
        );
        break;
      }

      case 'ping':
        // Server ping, no action needed
        break;

      default:
        console.log('Unknown message type:', message.type);
    }
  }, []);

  // Connect on mount
  useEffect(() => {
    connect();

    return () => {
      // Cleanup
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connect]);

  return {
    positions,
    portfolio,
    trades,
    pendingOrders,
    connectionStatus,
  };
}
